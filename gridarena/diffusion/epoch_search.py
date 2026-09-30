"""Epoch-selection sweep — find the best number of training epochs.

Trains a single run up to ``max_epochs``, pausing at a grid of checkpoint epochs
to score the in-memory model (no re-training) against a held-out temporal
validation split, using the same five statistics as the diffusion validation
metrics. The checkpoint with the best composite score wins; it is re-scored at
full sampling fidelity, saved as the run's model (so it can be generated from /
downloaded), and a per-epoch report + comparison figure are written to the run
directory.

Cost is roughly one training run + (num checkpoints) coarse sampling passes +
one full-fidelity pass for the winner — not one training run per candidate.
"""

import io
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np

from gridarena.diffusion.job_common import load_snapshots_and_config, update_run_config

logger = logging.getLogger(__name__)

_METRIC_NAMES = ["temporal_frobenius", "spatial_frobenius", "acf_mae", "mean_mae", "std_mae"]


def _composite_scores(history: List[dict]) -> None:
    """Add a 'composite_score' to each history entry in place: the unweighted
    mean of the five metrics, each normalised by that metric's max across the
    swept checkpoints (lower is better; all are distance-from-real metrics)."""
    max_per_metric = {m: (max(h[m] for h in history) or 1.0) for m in _METRIC_NAMES}
    for h in history:
        normed = [h[m] / max_per_metric[m] for m in _METRIC_NAMES]
        h["composite_score"] = sum(normed) / len(normed)


def _write_sweep_figure(history: List[dict], best_epoch: int, path: Path) -> None:
    import matplotlib.pyplot as plt
    epochs = [h["epoch"] for h in history]
    fig, ax = plt.subplots(figsize=(9, 5))
    for m in _METRIC_NAMES:
        values = [h[m] for h in history]
        vmax = max(values) or 1.0
        ax.plot(epochs, [v / vmax for v in values], marker="o", label=m)
    ax.axvline(best_epoch, color="gray", linestyle="--", alpha=0.6, label=f"best epoch = {best_epoch}")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("metric / max(metric) across sweep")
    ax.set_title("Validation metrics vs. epoch")
    ax.legend(fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    path.write_bytes(buf.getvalue())


def _train_with_checkpoints(config, p_train, p_val, checkpoint_epochs, sweep_inference_steps):
    """Train up to config.num_epochs, scoring against p_val at each checkpoint
    epoch. Returns (history, saved_states) where saved_states maps epoch ->
    cpu state dict clone."""
    import torch
    import torch.nn.functional as F
    from accelerate import Accelerator
    from tqdm.auto import tqdm

    from gridarena.diffusion.model_core import (
        _predict_noise,
        build_training_pipeline,
        compute_metrics,
        generate_samples,
    )

    model, noise_scheduler, optimizer, dataloader, lr_scheduler = build_training_pipeline(p_train, config)

    accelerator = Accelerator(
        mixed_precision=config.mixed_precision,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        project_dir=os.path.join("logs"),
    )
    model, optimizer, dataloader, lr_scheduler = accelerator.prepare(
        model, optimizer, dataloader, lr_scheduler,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint_set = set(checkpoint_epochs)
    history: List[Dict[str, float]] = []
    saved_states: Dict[int, dict] = {}
    p_val_real = p_val.astype("float32")

    for epoch in range(config.num_epochs):
        progress = tqdm(total=len(dataloader), disable=not accelerator.is_local_main_process)
        progress.set_description(f"Epoch {epoch}")
        epoch_loss_sum, epoch_loss_count = 0.0, 0

        for batch in dataloader:
            clean_images = batch["images"]
            noise = torch.randn_like(clean_images)
            bs = clean_images.shape[0]
            timesteps = torch.randint(
                0, noise_scheduler.config.num_train_timesteps, (bs,),
                device=clean_images.device, dtype=torch.int64,
            )
            noisy_images = noise_scheduler.add_noise(clean_images, noise, timesteps)

            with accelerator.accumulate(model):
                noise_pred = _predict_noise(model, noisy_images, timesteps)
                loss = F.mse_loss(noise_pred, noise)
                accelerator.backward(loss)
                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad()

            progress.update(1)
            progress.set_postfix(loss=loss.detach().item())
            epoch_loss_sum += loss.detach().item()
            epoch_loss_count += 1

        progress.close()
        epoch_num = epoch + 1
        avg_loss = epoch_loss_sum / max(1, epoch_loss_count)

        if epoch_num in checkpoint_set and accelerator.is_main_process:
            unwrapped = accelerator.unwrap_model(model)
            unwrapped.eval()
            p_gen = generate_samples(
                unwrapped, config, batch_size=max(8, len(p_val_real)),
                num_inference_steps=sweep_inference_steps, device=device,
            ).astype("float32")
            metrics = compute_metrics(p_val_real, p_gen)
            saved_states[epoch_num] = {k: v.detach().clone().cpu() for k, v in unwrapped.state_dict().items()}
            unwrapped.train()
            history.append({"epoch": epoch_num, "train_loss": avg_loss, **metrics})

    accelerator.end_training()
    return history, saved_states


def run_epoch_search(run_dir: str) -> dict:
    """Top-level picklable function executed in a subprocess. Reads run_config,
    runs the checkpoint sweep, saves the best checkpoint as the run's model, and
    writes epoch_search_report.json + metrics_vs_epoch.png."""
    import matplotlib
    matplotlib.use("Agg")

    run_path = Path(run_dir)
    with open(run_path / "run_config.json") as f:
        run_data = json.load(f)

    update_run_config(run_dir, {"status": "running"})

    try:
        from gridarena.diffusion.model_core import (
            build_model,
            compute_metrics,
            generate_samples,
            save_model_weights,
            split_power_dataset,
            write_model_metadata,
        )

        power_snapshots, config, _, _ = load_snapshots_and_config(run_data)

        max_epochs = int(run_data.get("max_epochs", run_data.get("num_epochs", 75)))
        checkpoint_interval = int(run_data.get("checkpoint_interval", 10))
        val_frac = run_data.get("val_frac", 0.2)
        buffer_days = run_data.get("buffer_days", 7)
        sweep_inference_steps = int(run_data.get("sweep_inference_steps", 100))

        config.num_epochs = max_epochs
        p_train, p_val = split_power_dataset(power_snapshots, val_frac=val_frac, buffer_days=buffer_days)

        checkpoint_epochs = sorted(
            set(range(checkpoint_interval, max_epochs + 1, checkpoint_interval)) | {max_epochs}
        )

        history, saved_states = _train_with_checkpoints(
            config, p_train, p_val, checkpoint_epochs, sweep_inference_steps,
        )

        if not history:
            raise RuntimeError("Epoch sweep produced no checkpoints — increase max_epochs.")

        _composite_scores(history)
        best = min(history, key=lambda h: h["composite_score"])
        best_epoch = int(best["epoch"])

        # Full-fidelity re-evaluation of the winning checkpoint, then persist it
        # as the run's shippable model.
        device = "cuda" if _cuda_available() else "cpu"
        best_model = build_model(config)
        best_model.load_state_dict(saved_states[best_epoch])
        best_model.eval()

        p_gen_final = generate_samples(best_model, config, batch_size=max(8, len(p_val)), device=device).astype("float32")
        final_metrics = compute_metrics(p_val.astype("float32"), p_gen_final)

        model_dir = run_path / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        save_model_weights(best_model, str(model_dir))
        write_model_metadata(model_dir, config, extra={"selected_epoch": best_epoch})
        shutil.make_archive(str(run_path / "diffusion_model"), "zip", root_dir=str(run_path), base_dir="model")

        _write_sweep_figure(history, best_epoch, run_path / "metrics_vs_epoch.png")

        report = {
            "architecture": config.architecture,
            "max_epochs_trained": max_epochs,
            "checkpoint_interval": checkpoint_interval,
            "sweep_inference_steps": sweep_inference_steps,
            "val_frac": val_frac,
            "buffer_days": buffer_days,
            "num_train_days": int(len(p_train)),
            "num_val_days": int(len(p_val)),
            "methodology": (
                "Each checkpoint's composite_score is the unweighted mean of its five "
                "validation metrics, each normalised by that metric's max across the sweep "
                "(lower is better). Sweep checkpoints use sweep_inference_steps for speed; "
                "the winner is re-scored at full inference steps and saved as the run's model."
            ),
            "history": history,
            "best_epoch": best_epoch,
            "best_epoch_final_metrics": final_metrics,
            "figures": ["metrics_vs_epoch.png"],
        }
        with open(run_path / "epoch_search_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        metrics = {
            "architecture": config.architecture,
            "best_epoch": best_epoch,
            "max_epochs_trained": max_epochs,
            "best_composite_score": float(best["composite_score"]),
            "best_epoch_final_metrics": final_metrics,
            "image_size": list(config.image_size),
        }
        update_run_config(run_dir, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "dataset_size": int(power_snapshots.shape[0]),
        })
        return {"status": "completed", "metrics": metrics}

    except Exception as e:
        logger.error("Epoch search failed: %s", e, exc_info=True)
        update_run_config(run_dir, {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        })
        return {"status": "failed", "error": str(e)}


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

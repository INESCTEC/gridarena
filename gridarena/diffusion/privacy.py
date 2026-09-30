"""Empirical privacy audit for the diffusion model — does it protect training data?

Trains a diagnostic model on a held-out-aware split with a handful of synthetic
canary days injected, then runs two measurements against it:

1. Membership-inference (loss-threshold attack): per-day denoising MSE, averaged
   over a fixed grid of timesteps with a fixed noise draw, is the attack
   statistic (lower loss -> scored as more likely a training member). Reports
   ROC AUC with a bootstrap 95% CI. Pass bar: AUC <= 0.55. With few held-out
   days the CI is wide by construction — read the interval, not just the point.

2. Canary insertion test: structurally-distinctive synthetic days are injected
   into training; after training a batch of samples is generated and each
   canary's nearest-neighbour distance to that batch is compared against the
   natural held-out days' distances. A canary below the natural 5th percentile
   is flagged as memorised.

The audited model has canaries mixed into its training set purely to test for
memorisation. It is NOT saved and must never be shipped — use a normal training
run (and, optionally, an epoch search) for the model you actually deploy.

This is the empirical counterpart to the preventive DP-SGD option available on
the normal training path.
"""

import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import numpy as np

from gridarena.diffusion.job_common import load_snapshots_and_config, update_run_config

logger = logging.getLogger(__name__)


# ── Membership inference: loss-threshold attack ─────────────────────────────


def _compute_per_day_losses(model, config, p_days, noise_scheduler, timesteps_grid,
                            seed: int = 0, batch_size: int = 64) -> np.ndarray:
    """Average denoising MSE per day over a fixed grid of timesteps, computed
    deterministically (fixed timesteps, fixed noise seed). Lower = the model fits
    this day better = more likely a training member."""
    import torch

    from gridarena.diffusion.model_core import _predict_noise

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    model.eval()

    x = torch.as_tensor(p_days, dtype=torch.float32)
    x = (x - config.power_subtract) / config.power_rescale
    x = x.unsqueeze(1).to(device)  # (n_days, 1, H, W)

    n_days = x.shape[0]
    per_day_loss = torch.zeros(n_days, device=device)
    generator = torch.Generator(device=device).manual_seed(seed)

    with torch.no_grad():
        for t in timesteps_grid:
            for start in range(0, n_days, batch_size):
                end = min(start + batch_size, n_days)
                xb = x[start:end]
                bs = xb.shape[0]
                noise = torch.randn(xb.shape, generator=generator, device=device)
                t_batch = torch.full((bs,), int(t), device=device, dtype=torch.long)
                noisy = noise_scheduler.add_noise(xb, noise, t_batch)
                noise_pred = _predict_noise(model, noisy, t_batch)
                per_day_loss[start:end] += ((noise_pred - noise) ** 2).flatten(1).mean(dim=1)

    return (per_day_loss / len(timesteps_grid)).detach().cpu().numpy()


def _compute_auc(member_scores: np.ndarray, nonmember_scores: np.ndarray) -> float:
    """Mann-Whitney U estimator of ROC AUC: P(member scores rank higher)."""
    greater = (member_scores[:, None] > nonmember_scores[None, :]).sum()
    ties = (member_scores[:, None] == nonmember_scores[None, :]).sum()
    return float((greater + 0.5 * ties) / (member_scores.size * nonmember_scores.size))


def _bootstrap_auc_ci(member_scores, nonmember_scores, n_boot: int = 2000, seed: int = 0) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    n_m, n_n = len(member_scores), len(nonmember_scores)
    aucs = np.empty(n_boot)
    for i in range(n_boot):
        m_sample = member_scores[rng.integers(0, n_m, n_m)]
        n_sample = nonmember_scores[rng.integers(0, n_n, n_n)]
        aucs[i] = _compute_auc(m_sample, n_sample)
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


# ── Canary insertion test ───────────────────────────────────────────────────


def _make_canaries(p_train: np.ndarray, num_canaries: int, seed: int = 0) -> np.ndarray:
    """Deterministic double-spike canary days at fixed unusual time positions,
    scaled into the real data's per-node value range with small jitter. A real
    day cannot plausibly resemble this pattern by chance, so a close reproduction
    is unambiguous evidence of memorisation."""
    _, n_nodes, n_timestamps = p_train.shape
    rng = np.random.default_rng(seed)

    node_min = p_train.min(axis=(0, 2))
    node_max = p_train.max(axis=(0, 2))
    node_range = np.clip(node_max - node_min, 1e-6, None)

    spike_a = n_timestamps // 5
    spike_b = (4 * n_timestamps) // 5

    canaries = np.tile((node_min + 0.1 * node_range)[None, :, None], (num_canaries, 1, n_timestamps))
    canaries[:, :, spike_a] = (node_min + 0.9 * node_range)[None, :]
    canaries[:, :, spike_b] = node_max[None, :]
    canaries = canaries + rng.normal(scale=(0.01 * node_range)[None, :, None], size=canaries.shape)
    return canaries.astype(p_train.dtype)


def _nn_distances(queries: np.ndarray, pool: np.ndarray) -> np.ndarray:
    """For each query snapshot, Euclidean distance to its nearest neighbour in pool."""
    q = queries.reshape(len(queries), -1)
    p = pool.reshape(len(pool), -1)
    dists = np.linalg.norm(q[:, None, :] - p[None, :, :], axis=-1)
    return dists.min(axis=1)


# ── Figures ─────────────────────────────────────────────────────────────────


def _fig_to_png(fig, path: Path) -> None:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    path.write_bytes(buf.getvalue())


def _write_mi_figure(member, nonmember, auc, ci, path: Path) -> None:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bins = np.histogram_bin_edges(np.concatenate([member, nonmember]), bins=25)
    ax.hist(member, bins=bins, alpha=0.55, color="steelblue", label="train (members)", density=True)
    ax.hist(nonmember, bins=bins, alpha=0.55, color="tomato", label="held-out (non-members)", density=True)
    ax.set_xlabel("per-day denoising loss (fixed timestep grid)")
    ax.set_ylabel("density")
    ax.set_title(f"Membership-inference loss distributions — AUC={auc:.3f}  95% CI=[{ci[0]:.3f}, {ci[1]:.3f}]")
    ax.legend()
    fig.tight_layout()
    _fig_to_png(fig, path)


def _write_canary_figure(natural_nn, canary_nn, threshold_p5, path: Path) -> None:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(natural_nn, bins=20, color="steelblue", alpha=0.6, label="natural held-out days")
    ax.axvline(threshold_p5, color="gray", linestyle="--", label="natural 5th percentile")
    for i, d in enumerate(canary_nn):
        ax.axvline(d, color="tomato", linewidth=2, alpha=0.8, label="canary" if i == 0 else None)
    ax.set_xlabel("nearest-neighbour distance to generated batch")
    ax.set_ylabel("count")
    ax.set_title("Canary vs. natural nearest-neighbour distance to generated samples")
    ax.legend()
    fig.tight_layout()
    _fig_to_png(fig, path)


# ── Subprocess entry point ──────────────────────────────────────────────────


def run_privacy_check(run_dir: str) -> dict:
    """Top-level picklable function executed in a subprocess. Reads run_config,
    trains a diagnostic model, runs the MI + canary audits, and writes
    privacy_report.json + two figures into the run directory."""
    import matplotlib
    matplotlib.use("Agg")

    run_path = Path(run_dir)
    with open(run_path / "run_config.json") as f:
        run_data = json.load(f)

    update_run_config(run_dir, {"status": "running"})

    try:
        from gridarena.diffusion.model_core import (
            build_noise_scheduler,
            generate_samples,
            split_power_dataset,
            train_diffusion_model,
        )

        power_snapshots, config, _, _ = load_snapshots_and_config(run_data)

        val_frac = run_data.get("val_frac", 0.2)
        buffer_days = run_data.get("buffer_days", 7)
        num_canaries = run_data.get("num_canaries", 5)
        mi_num_timestep_samples = run_data.get("mi_num_timestep_samples", 20)
        num_generated_samples = run_data.get("num_generated_samples", 128)
        canary_inference_steps = run_data.get("canary_inference_steps", 250)

        p_train, p_val = split_power_dataset(power_snapshots, val_frac=val_frac, buffer_days=buffer_days)

        canaries = _make_canaries(p_train, num_canaries)
        p_train_with_canaries = np.concatenate([p_train, canaries], axis=0)

        # Diagnostic model: never saved (save_artifacts=False).
        trained_model, _ = train_diffusion_model(
            p_dataset=p_train_with_canaries, config=config, output_dir=run_dir, save_artifacts=False,
        )

        # --- Membership inference ---
        noise_scheduler = build_noise_scheduler()
        timesteps_grid = np.linspace(
            0, noise_scheduler.config.num_train_timesteps - 1, mi_num_timestep_samples, dtype=int,
        )
        member_losses = _compute_per_day_losses(trained_model, config, p_train, noise_scheduler, timesteps_grid)
        nonmember_losses = _compute_per_day_losses(trained_model, config, p_val, noise_scheduler, timesteps_grid)

        auc = _compute_auc(-member_losses, -nonmember_losses)
        ci_low, ci_high = _bootstrap_auc_ci(-member_losses, -nonmember_losses)
        mi_passed = auc <= 0.55

        # --- Canary memorisation ---
        p_gen = generate_samples(
            trained_model, config, batch_size=num_generated_samples,
            num_inference_steps=canary_inference_steps,
            device="cuda" if _cuda_available() else "cpu",
        ).astype("float32")

        natural_nn = _nn_distances(p_val.astype("float32"), p_gen)
        canary_nn = _nn_distances(canaries.astype("float32"), p_gen)
        threshold_p5 = float(np.percentile(natural_nn, 5))
        canaries_below_p5 = (canary_nn < threshold_p5).tolist()
        canary_passed = not any(canaries_below_p5)

        _write_mi_figure(member_losses, nonmember_losses, auc, (ci_low, ci_high),
                         run_path / "mi_loss_distributions.png")
        _write_canary_figure(natural_nn, canary_nn, threshold_p5,
                             run_path / "canary_nn_distances.png")

        report = {
            "architecture": config.architecture,
            "num_epochs": config.num_epochs,
            "val_frac": val_frac,
            "buffer_days": buffer_days,
            "num_train_days": int(len(p_train)),
            "num_val_days": int(len(p_val)),
            "num_canaries": num_canaries,
            "warning": (
                "This model's training set included synthetic canaries injected for this "
                "audit. It was NOT saved and must not be used as a production artifact — "
                "use a normal training run for the model you ship."
            ),
            "membership_inference": {
                "method": (
                    "Loss-threshold attack: per-day denoising MSE averaged over a fixed grid "
                    "of timesteps and a fixed noise seed. Attack score = -loss. AUC is "
                    "P(a random member scores higher than a random non-member)."
                ),
                "mi_num_timestep_samples": mi_num_timestep_samples,
                "auc": auc,
                "auc_ci_95": [ci_low, ci_high],
                "pass_threshold": 0.55,
                "passed": bool(mi_passed),
                "note": "With few held-out days the CI is wide — treat the interval as the result.",
                "member_loss_mean": float(member_losses.mean()),
                "nonmember_loss_mean": float(nonmember_losses.mean()),
            },
            "canary_memorisation": {
                "method": (
                    "For each canary and each natural held-out day, the nearest-neighbour "
                    "Euclidean distance to a freshly generated batch is computed. A canary is "
                    "flagged as memorised if its distance falls below the natural-day 5th percentile."
                ),
                "num_generated_samples": num_generated_samples,
                "canary_inference_steps": canary_inference_steps,
                "natural_nn_distance_p5": threshold_p5,
                "natural_nn_distance_mean": float(natural_nn.mean()),
                "canary_nn_distances": [float(d) for d in canary_nn],
                "canaries_below_p5": canaries_below_p5,
                "passed": bool(canary_passed),
            },
            "overall_passed": bool(mi_passed and canary_passed),
            "figures": ["mi_loss_distributions.png", "canary_nn_distances.png"],
        }

        with open(run_path / "privacy_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Surface headline numbers on the run row.
        metrics = {
            "architecture": config.architecture,
            "overall_passed": report["overall_passed"],
            "mi_auc": auc,
            "mi_auc_ci_95": [ci_low, ci_high],
            "canaries_memorised": int(sum(canaries_below_p5)),
            "num_canaries": num_canaries,
        }

        update_run_config(run_dir, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "dataset_size": int(power_snapshots.shape[0]),
        })
        return {"status": "completed", "metrics": metrics}

    except Exception as e:
        logger.error("Privacy check failed: %s", e, exc_info=True)
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

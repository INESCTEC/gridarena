"""Diffusion model training, generation and validation logic.

Structure mirrors the standalone diffusion_p_analysis project (Flyte/S3 removed):

  * Four selectable backbones dispatched by ``config.architecture``:
      "unet2d"   — diffusers UNet2DModel (2D conv; needs an even, /8-divisible
                   node count — legacy, kept for backwards compatibility)
      "deepsets" — Deep Sets permutation-invariant node mixing
      "axial"    — cross-node self-attention (recommended default)
      "gnn"      — GCN message passing over an edge topology
  * The three custom backbones operate on (B, 1, H, W) tensors with H = grid
    nodes (never downsampled) so they train on any node count.
  * Training happens directly on the daily power snapshots — no synthetic grid /
    power-flow step (the old ``prepare_training_data`` computed a voltage dataset
    that the trainer never consumed).

All heavy statistics helpers (``compute_metrics`` and friends) are pure numpy so
the epoch-search sweep and privacy audit can call them without a GPU.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F
from datasets import Dataset
from diffusers import DDPMScheduler, UNet2DModel
from diffusers.optimization import get_cosine_schedule_with_warmup
from tqdm.auto import tqdm

from gridarena.diffusion.architectures import (
    AxialDiffusionUNet,
    DeepSetsDiffusionUNet,
    GraphDiffusionUNet,
)
from gridarena.diffusion.schemas import DiffusionTrainingConfig

logger = logging.getLogger(__name__)

# Architectures whose node axis is never downsampled — they accept any node count.
CUSTOM_ARCHITECTURES = ("deepsets", "axial", "gnn")
ALL_ARCHITECTURES = ("axial", "deepsets", "gnn", "unet2d")


# ── Model construction ──────────────────────────────────────────────────────


def build_unet2d_model() -> UNet2DModel:
    # UNet2DModel applies 2D conv downsampling on both H and W, so both
    # dimensions must be divisible by 8. Use a custom architecture for grids
    # whose node count is not a multiple of 8.
    return UNet2DModel(
        sample_size=None,
        in_channels=1,
        out_channels=1,
        layers_per_block=3,
        block_out_channels=(128, 256, 512, 512),
        down_block_types=("DownBlock2D", "DownBlock2D", "AttnDownBlock2D", "DownBlock2D"),
        up_block_types=("UpBlock2D", "AttnUpBlock2D", "UpBlock2D", "UpBlock2D"),
    )


def build_model(config: DiffusionTrainingConfig, **extra):
    """Dispatch to the backbone selected by ``config.architecture``."""
    arch = getattr(config, "architecture", "axial")
    if arch == "unet2d":
        return build_unet2d_model()
    if arch == "deepsets":
        return DeepSetsDiffusionUNet(in_channels=config.num_channels, **extra)
    if arch == "axial":
        return AxialDiffusionUNet(in_channels=config.num_channels, **extra)
    if arch == "gnn":
        h, _ = config.image_size
        return GraphDiffusionUNet(in_channels=config.num_channels, num_nodes=h, **extra)
    raise ValueError(
        f"Unknown architecture {arch!r}. Choose from {ALL_ARCHITECTURES}."
    )


def _predict_noise(model, noisy: torch.Tensor, timesteps: torch.Tensor) -> torch.Tensor:
    """Call the noise-prediction model regardless of backbone or wrapper.

    Accelerate (``.module``) and Opacus (``._module``) both wrap the model; we
    dispatch on the *underlying* module type so a wrapped UNet2DModel is not
    misclassified as a custom backbone.
    """
    base = model
    for attr in ("module", "_module"):
        if hasattr(base, attr):
            base = getattr(base, attr)
    if isinstance(base, UNet2DModel):
        return model(noisy, timesteps, return_dict=False)[0]
    # Custom backbones: (B,1,H,W) input, returns (B,1,H,W)
    return model(noisy, timesteps)


def build_noise_scheduler(clip_sample: bool = False, clip_sample_range: float = 1.0) -> DDPMScheduler:
    """Single source of truth for the DDPM scheduler config, shared by training
    and inference so the two can't silently drift apart. Sampling passes
    ``clip_sample=True``."""
    return DDPMScheduler(
        num_train_timesteps=1000,
        beta_schedule="squaredcos_cap_v2",
        clip_sample=clip_sample,
        clip_sample_range=clip_sample_range,
    )


# ── Dataset construction ────────────────────────────────────────────────────


def _prepare_snapshot_tensor(arr) -> torch.Tensor:
    t = torch.as_tensor(arr, dtype=torch.float32)
    if t.ndim == 2:
        return t
    if t.ndim == 3 and t.shape[0] == 1:
        return t.squeeze(0)
    raise ValueError(f"Expected shape (H,W) or (1,H,W), got {tuple(t.shape)}")


def _normalize_power(t: torch.Tensor, subtract: float, rescale: float) -> torch.Tensor:
    if rescale == 0:
        raise ValueError("power_rescale must not be zero.")
    return (t - subtract) / rescale


def _transform_examples(examples, power_subtract, power_rescale):
    power_values = []
    for p_arr in examples["power"]:
        p_t = _prepare_snapshot_tensor(p_arr)
        p_t = _normalize_power(p_t, power_subtract, power_rescale)
        power_values.append(p_t.unsqueeze(0))
    examples["images"] = power_values
    return examples


def build_training_pipeline(p_dataset, config: DiffusionTrainingConfig):
    """Build dataset, model, optimizer, scheduler — everything needed for training."""
    if len(p_dataset) == 0:
        raise ValueError("Empty power dataset.")

    dataset = Dataset.from_dict({"power": p_dataset, "id": list(range(len(p_dataset)))})
    dataset = dataset.map(
        _transform_examples,
        batched=True,
        fn_kwargs={"power_subtract": config.power_subtract, "power_rescale": config.power_rescale},
    )
    dataset.set_format(type="torch", columns=["images", "id"])

    dataloader = torch.utils.data.DataLoader(dataset, batch_size=config.train_batch_size, shuffle=True)
    model = build_model(config)
    noise_scheduler = build_noise_scheduler()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
    lr_scheduler = get_cosine_schedule_with_warmup(
        optimizer=optimizer,
        num_warmup_steps=config.lr_warmup_steps,
        num_training_steps=len(dataloader) * config.num_epochs,
    )

    return model, noise_scheduler, optimizer, dataloader, lr_scheduler


def split_power_dataset(
    p_dataset: np.ndarray,
    val_frac: float = 0.2,
    buffer_days: int = 7,
) -> Tuple[np.ndarray, np.ndarray]:
    """Temporal train/val split: a contiguous training prefix and a contiguous
    validation suffix, with ``buffer_days`` discarded between them to reduce
    leakage from day-to-day autocorrelation.

    p_dataset: (num_days, num_nodes, daily_meas), ordered chronologically.
    Returns (p_train, p_val).
    """
    n = len(p_dataset)
    n_val = max(1, round(n * val_frac))
    val_start = n - n_val
    train_end = max(0, val_start - buffer_days)

    if train_end == 0:
        raise ValueError(
            f"val_frac={val_frac} and buffer_days={buffer_days} leave no training "
            f"days out of {n} total days. Provide more data or reduce val_frac/buffer_days."
        )

    return p_dataset[:train_end], p_dataset[val_start:]


# ── Model persistence ───────────────────────────────────────────────────────


def _to_jsonable(x):
    if x is None:
        return None
    if isinstance(x, torch.Tensor):
        return x.detach().cpu().tolist()
    if hasattr(x, "tolist"):
        return x.tolist()
    if isinstance(x, (list, tuple)):
        return [_to_jsonable(item) for item in x]
    raise TypeError(f"Cannot serialize {type(x).__name__}")


def save_model_weights(model, dest_dir: str) -> None:
    """Persist weights in a format ``load_trained_model`` can read: diffusers
    native for UNet2DModel, a plain state dict otherwise."""
    os.makedirs(dest_dir, exist_ok=True)
    if isinstance(model, UNet2DModel):
        model.save_pretrained(dest_dir)
    else:
        torch.save(model.state_dict(), os.path.join(str(dest_dir), "pytorch_model.bin"))


def write_model_metadata(model_dir: Path, config: DiffusionTrainingConfig, extra: Optional[dict] = None) -> None:
    payload = {
        "architecture": getattr(config, "architecture", "axial"),
        "num_channels": config.num_channels,
        "channel_order": ["power"],
        "image_size": list(config.image_size),
        "power_subtract": config.power_subtract,
        "power_rescale": config.power_rescale,
    }
    if extra:
        payload.update(extra)
    with open(model_dir / "model_config.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _read_model_metadata(model_dir: Path) -> dict:
    # New runs write model_config.json; fall back to the legacy filename.
    for name in ("model_config.json", "grid_admittance.json"):
        meta_path = model_dir / name
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"No model metadata (model_config.json) found in {model_dir}")


def load_trained_model(model_dir: str, device: str = "cpu"):
    """Reconstruct a trained model + config from a run's ``model/`` directory,
    dispatching on the recorded architecture."""
    model_path = Path(model_dir) / "model"
    if not model_path.exists():
        raise FileNotFoundError(f"No model found at {model_path}")

    meta = _read_model_metadata(model_path)
    config = DiffusionTrainingConfig(
        architecture=meta.get("architecture", "unet2d"),
        image_size=tuple(meta["image_size"]),
        power_subtract=meta["power_subtract"],
        power_rescale=meta["power_rescale"],
        num_channels=meta.get("num_channels", 1),
    )

    if config.architecture == "unet2d":
        model = UNet2DModel.from_pretrained(str(model_path))
    else:
        model = build_model(config)
        state_dict = torch.load(model_path / "pytorch_model.bin", map_location="cpu")
        model.load_state_dict(state_dict)

    return model.to(device).eval(), config


# ── Training loop ───────────────────────────────────────────────────────────


def train_diffusion_model(
    p_dataset,
    config: DiffusionTrainingConfig,
    output_dir: str,
    save_artifacts: bool = True,
) -> Tuple[object, dict]:
    """Train the DDPM model on daily power snapshots and (optionally) save
    artifacts to ``output_dir``. Returns (trained_model, metrics).

    ``save_artifacts=False`` skips writing the model weights / zip — used by the
    privacy audit, whose model is trained with canaries injected and must never
    be shipped."""
    from accelerate import Accelerator

    model, noise_scheduler, optimizer, dataloader, lr_scheduler = build_training_pipeline(p_dataset, config)

    # ── DP-SGD setup (optional, preventive privacy) ──
    privacy_engine = None
    dp_enabled = config.dp_enabled

    if dp_enabled:
        from opacus import PrivacyEngine
        from opacus.validators import ModuleValidator

        if not ModuleValidator.is_valid(model):
            model = ModuleValidator.fix(model)

        privacy_engine = PrivacyEngine()
        model, optimizer, dataloader = privacy_engine.make_private(
            module=model,
            optimizer=optimizer,
            data_loader=dataloader,
            noise_multiplier=config.dp_noise_multiplier,
            max_grad_norm=config.dp_max_grad_norm,
        )

    # When DP is on, Opacus owns model/optimizer/dataloader — Accelerator is logging only.
    if dp_enabled:
        accelerator = Accelerator(mixed_precision="no", project_dir=os.path.join(output_dir, "logs"))
        device = accelerator.device
        model = model.to(device)
    else:
        accelerator = Accelerator(
            mixed_precision=config.mixed_precision,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            project_dir=os.path.join(output_dir, "logs"),
        )
        model, optimizer, dataloader, lr_scheduler = accelerator.prepare(
            model, optimizer, dataloader, lr_scheduler,
        )

    os.makedirs(output_dir, exist_ok=True)
    if accelerator.is_main_process:
        accelerator.init_trackers("diffusion_training")

    global_step = 0
    loss_history = []

    for epoch in range(config.num_epochs):
        epoch_losses = []
        progress = tqdm(total=len(dataloader), disable=not accelerator.is_local_main_process)
        progress.set_description(f"Epoch {epoch}")

        for batch in dataloader:
            clean_images = batch["images"]
            if dp_enabled:
                clean_images = clean_images.to(device)

            noise = torch.randn_like(clean_images)
            bs = clean_images.shape[0]

            timesteps = torch.randint(
                0, noise_scheduler.config.num_train_timesteps, (bs,),
                device=clean_images.device, dtype=torch.int64,
            )
            noisy_images = noise_scheduler.add_noise(clean_images, noise, timesteps)

            if dp_enabled:
                noise_pred = _predict_noise(model, noisy_images, timesteps)
                loss = F.mse_loss(noise_pred, noise)
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()
            else:
                with accelerator.accumulate(model):
                    noise_pred = _predict_noise(model, noisy_images, timesteps)
                    loss = F.mse_loss(noise_pred, noise)

                    accelerator.backward(loss)
                    if accelerator.sync_gradients:
                        accelerator.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    lr_scheduler.step()
                    optimizer.zero_grad()

            epoch_losses.append(loss.detach().item())
            progress.update(1)
            progress.set_postfix(loss=loss.detach().item())
            global_step += 1

        loss_history.append(float(np.mean(epoch_losses)))
        progress.close()

    # ── Extract privacy budget spent ──
    dp_metrics = {}
    if privacy_engine is not None:
        epsilon = privacy_engine.get_epsilon(delta=config.dp_target_delta)
        dp_metrics = {
            "dp_epsilon": float(epsilon),
            "dp_delta": config.dp_target_delta,
            "dp_max_grad_norm": config.dp_max_grad_norm,
            "dp_noise_multiplier": config.dp_noise_multiplier,
        }

    # ── Unwrap model ──
    if dp_enabled:
        trained_model = model._module
    else:
        trained_model = accelerator.unwrap_model(model)

    accelerator.end_training()

    if save_artifacts and accelerator.is_main_process:
        model_dir = Path(output_dir) / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        save_model_weights(trained_model, str(model_dir))
        write_model_metadata(
            model_dir, config,
            extra={"differential_privacy": dp_metrics} if dp_metrics else None,
        )
        shutil.make_archive(str(Path(output_dir) / "diffusion_model"), "zip",
                            root_dir=output_dir, base_dir="model")

    accelerator.wait_for_everyone()

    metrics = {
        "architecture": getattr(config, "architecture", "axial"),
        "total_epochs": config.num_epochs,
        "final_loss": loss_history[-1] if loss_history else None,
        "loss_history": loss_history,
        "global_steps": global_step,
        **dp_metrics,
    }

    return trained_model, metrics


# ── Sample generation ───────────────────────────────────────────────────────


def denormalize_power(p_norm: torch.Tensor, config: DiffusionTrainingConfig) -> torch.Tensor:
    return p_norm * config.power_rescale + config.power_subtract


@torch.no_grad()
def generate_samples(
    model,
    config: DiffusionTrainingConfig,
    batch_size: int = 1,
    num_inference_steps: int = 1000,
    device: str = "cpu",
) -> np.ndarray:
    """Standard unguided DDPM sampling for any backbone. Returns a host numpy
    array of shape (batch_size, n_nodes, n_timesteps) in physical units."""
    model = model.to(device)
    model.eval()

    scheduler = build_noise_scheduler(clip_sample=True, clip_sample_range=5.0)
    scheduler.set_timesteps(num_inference_steps)

    h, w = config.image_size
    x = torch.randn(batch_size, config.num_channels, h, w, device=device)

    for t in scheduler.timesteps:
        t_batch = torch.full((batch_size,), int(t), device=device, dtype=torch.long)
        noise_pred = _predict_noise(model, x, t_batch)
        x = scheduler.step(noise_pred, t, x).prev_sample

    p_phys = denormalize_power(x[:, 0, :, :], config)
    return p_phys.detach().cpu().numpy()


def generate_snapshot(model_dir: str, num_inference_steps: int = 1000, device: str = "cpu") -> dict:
    """Load a trained model and generate a single synthetic daily snapshot.

    Returns a dict with the (n_nodes, n_timesteps) power matrix and metadata.
    """
    model, config = load_trained_model(model_dir, device=device)
    samples = generate_samples(
        model, config, batch_size=1, num_inference_steps=num_inference_steps, device=device,
    )
    snapshot = samples[0]

    return {
        "architecture": getattr(config, "architecture", "unet2d"),
        "n_nodes": int(snapshot.shape[0]),
        "n_timesteps": int(snapshot.shape[1]),
        "snapshot": snapshot.tolist(),
        "summary": {
            "mean": float(snapshot.mean()),
            "std": float(snapshot.std()),
            "min": float(snapshot.min()),
            "max": float(snapshot.max()),
        },
    }


# ── Validation statistics (pure numpy — used by epoch search & privacy audit) ─


def _safe_corrcoef(x: np.ndarray) -> np.ndarray:
    """np.corrcoef with NaN (zero-variance rows) replaced by 0."""
    return np.nan_to_num(np.corrcoef(x), nan=0.0)


def compute_correlation_matrices(snapshots: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """snapshots: (n_samples, n_nodes, n_timestamps).

    Returns (T_avg (n_timestamps, n_timestamps), S_avg (n_nodes, n_nodes)) — the
    mean temporal and spatial correlation matrices."""
    n_samples, n_nodes, n_timestamps = snapshots.shape
    T_sum = np.zeros((n_timestamps, n_timestamps))
    S_sum = np.zeros((n_nodes, n_nodes))
    for x in snapshots:                 # x: (n_nodes, n_timestamps)
        T_sum += _safe_corrcoef(x.T)    # corrcoef over timestamps
        S_sum += _safe_corrcoef(x)      # corrcoef over nodes
    return T_sum / n_samples, S_sum / n_samples


def acf_numpy(x: np.ndarray, nlags: int) -> np.ndarray:
    """Autocorrelation of 1-D array x at lags 0..nlags (inclusive)."""
    x = x - x.mean()
    full = np.correlate(x, x, mode="full")
    norm = full[len(x) - 1]
    if norm == 0:
        return np.zeros(nlags + 1)
    return (full[len(x) - 1:] / norm)[: nlags + 1]


def mean_node_acf(snapshots: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (mean_acf, std_acf) over nodes and samples."""
    n_samples, n_nodes, n_timestamps = snapshots.shape
    nlags = n_timestamps // 2
    all_acf = []
    for x in snapshots:
        for node_ts in x:
            all_acf.append(acf_numpy(node_ts, nlags))
    all_acf = np.array(all_acf)
    return all_acf.mean(axis=0), all_acf.std(axis=0)


def compute_metrics(p_real: np.ndarray, p_gen: np.ndarray) -> dict:
    """Five scalar distance-from-real metrics (lower = better) comparing real vs
    generated snapshot batches, each (n_samples, n_nodes, n_timestamps)."""
    T_real, S_real = compute_correlation_matrices(p_real)
    T_gen, S_gen = compute_correlation_matrices(p_gen)

    acf_real, _ = mean_node_acf(p_real)
    acf_gen, _ = mean_node_acf(p_gen)

    mean_real, mean_gen = p_real.mean(axis=(0, 1)), p_gen.mean(axis=(0, 1))
    std_real, std_gen = p_real.std(axis=(0, 1)), p_gen.std(axis=(0, 1))

    return {
        "temporal_frobenius": float(np.linalg.norm(T_real - T_gen, "fro")),
        "spatial_frobenius": float(np.linalg.norm(S_real - S_gen, "fro")),
        "acf_mae": float(np.mean(np.abs(acf_real - acf_gen))),
        "mean_mae": float(np.mean(np.abs(mean_real - mean_gen))),
        "std_mae": float(np.mean(np.abs(std_real - std_gen))),
    }

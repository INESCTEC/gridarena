"""Shared helpers for the diffusion subprocess jobs (train / privacy / epoch search).

Each job runs in a spawned subprocess, reads its ``run_config.json``, loads the
power snapshots from the database and builds a ``DiffusionTrainingConfig`` the
same way — this module centralises that so the three entry points can't drift.
"""

import json
import logging
from pathlib import Path
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


def update_run_config(run_dir: str, updates: dict) -> None:
    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        data = json.load(f)
    data.update(updates)
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)


def load_snapshots_and_config(run_data: dict) -> Tuple[np.ndarray, "object", int, int]:
    """Load daily power snapshots from the DB and build a training config.

    Returns (power_snapshots, config, n_nodes, n_daily_timesteps).
    """
    from gridarena.diffusion.data_loader import load_power_data_from_db
    from gridarena.diffusion.schemas import DiffusionTrainingConfig

    architecture = run_data.get("architecture", "axial")
    # Only the legacy UNet2D backbone needs an even node count.
    require_even = architecture == "unet2d"

    power_snapshots, n_nodes, n_daily_timesteps = load_power_data_from_db(
        grid_ids=run_data["grid_ids"],
        phase=run_data.get("phase"),
        start=run_data.get("start"),
        end=run_data.get("end"),
        p_min=run_data.get("p_min"),
        p_max=run_data.get("p_max"),
        require_even_nodes=require_even,
    )

    # Resolve "auto" normalisation from the training data.
    raw_subtract = run_data.get("power_subtract", "auto")
    raw_rescale = run_data.get("power_rescale", "auto")
    power_subtract = float(np.mean(power_snapshots)) if raw_subtract == "auto" else float(raw_subtract)
    power_rescale = float(np.std(power_snapshots)) if raw_rescale == "auto" else float(raw_rescale)
    if power_rescale == 0:
        power_rescale = 1.0

    dp_enabled = run_data.get("dp_enabled", False)

    config = DiffusionTrainingConfig(
        architecture=architecture,
        num_epochs=run_data.get("num_epochs", 75),
        train_batch_size=run_data.get("train_batch_size", 16),
        eval_batch_size=run_data.get("num_generated_samples", 16),
        learning_rate=run_data.get("learning_rate", 1e-4),
        lr_warmup_steps=run_data.get("lr_warmup_steps", 500),
        gradient_accumulation_steps=1 if dp_enabled else run_data.get("gradient_accumulation_steps", 1),
        mixed_precision="no" if dp_enabled else run_data.get("mixed_precision", "no"),
        power_subtract=power_subtract,
        power_rescale=power_rescale,
        image_size=(n_nodes, n_daily_timesteps),
        dp_enabled=dp_enabled,
        dp_max_grad_norm=run_data.get("dp_max_grad_norm", 1.0),
        dp_noise_multiplier=run_data.get("dp_noise_multiplier", 1.0),
        dp_target_delta=run_data.get("dp_target_delta", 1e-5),
    )

    return power_snapshots, config, n_nodes, n_daily_timesteps

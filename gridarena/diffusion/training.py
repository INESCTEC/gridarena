"""Top-level picklable training entry point for subprocess execution."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from gridarena.diffusion.job_common import load_snapshots_and_config, update_run_config

logger = logging.getLogger(__name__)


def run_diffusion_training(run_dir: str) -> dict:
    """Top-level picklable function executed in a subprocess.

    Reads config from run_dir/run_config.json, loads data from the DB, trains the
    diffusion model directly on the daily power snapshots, saves artifacts, and
    updates status.
    """
    import matplotlib
    matplotlib.use("Agg")

    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        run_data = json.load(f)

    update_run_config(run_dir, {"status": "running"})

    try:
        from gridarena.diffusion.model_core import train_diffusion_model

        power_snapshots, config, n_nodes, n_daily_timesteps = load_snapshots_and_config(run_data)

        # Train directly on the daily snapshots (n_days, n_nodes, n_daily_timesteps).
        _, metrics = train_diffusion_model(
            p_dataset=power_snapshots,
            config=config,
            output_dir=run_dir,
        )

        metrics["dataset_shape"] = list(power_snapshots.shape)
        metrics["image_size"] = [n_nodes, n_daily_timesteps]

        update_run_config(run_dir, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "dataset_size": int(power_snapshots.shape[0]),
        })

        return {"status": "completed", "metrics": metrics}

    except Exception as e:
        logger.error("Diffusion training failed: %s", e, exc_info=True)
        update_run_config(run_dir, {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        })
        return {"status": "failed", "error": str(e)}

"""Manages training runs: lifecycle, background execution, status tracking."""

import json
import logging
import multiprocessing
import re
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gridarena.rl.schemas import RunStatus, TrainRequest

logger = logging.getLogger(__name__)

RUNS_DIR = Path(__file__).resolve().parent / "runs"

# run_id is always server-generated as uuid.uuid4().hex[:8]; enforced here as
# defense-in-depth before the id is used to build a filesystem path.
_RUN_ID_RE = re.compile(r"^[0-9a-f]{8}$")


class RunRegistry:
    def __init__(self, max_workers: int = 2):
        self._runs: dict[str, RunStatus] = {}
        self._pool: Optional[ProcessPoolExecutor] = None
        self._max_workers = max_workers

    def startup(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        ctx = multiprocessing.get_context("spawn")
        self._pool = ProcessPoolExecutor(max_workers=self._max_workers, mp_context=ctx)
        self._rebuild_from_disk()
        logger.info("RunRegistry started with %d workers (spawn)", self._max_workers)

    def shutdown(self):
        if self._pool:
            # cancel_futures only drops queued (not-yet-started) work; a
            # worker already training is otherwise orphaned on restart, so
            # forcefully terminate any live worker processes too. This
            # relies on ProcessPoolExecutor's private _processes attribute --
            # concurrent.futures has no public API for this.
            for p in list(getattr(self._pool, "_processes", {}).values()):
                if p.is_alive():
                    p.terminate()
            self._pool.shutdown(wait=False, cancel_futures=True)
            logger.info("RunRegistry shut down")

    def _rebuild_from_disk(self):
        for config_file in RUNS_DIR.glob("*/run_config.json"):
            try:
                with open(config_file) as f:
                    data = json.load(f)
                run_id = data["run_id"]
                status = data.get("status", "unknown")
                if status == "running":
                    status = "failed"
                    data["status"] = "failed"
                    data["error"] = "Server restarted during training"
                    with open(config_file, "w") as f:
                        json.dump(data, f, indent=2)

                self._runs[run_id] = RunStatus(
                    run_id=run_id,
                    grid_id=data["grid_id"],
                    agent_type=data["agent_type"],
                    status=status,
                    created_at=data["created_at"],
                    completed_at=data.get("completed_at"),
                    timesteps=data.get("timesteps", 0),
                    error=data.get("error"),
                    metrics=data.get("metrics"),
                )
            except Exception as e:
                logger.warning("Failed to load run config %s: %s", config_file, e)

    def start_training(self, request: TrainRequest, grid_config_dict: dict) -> str:
        from gridarena.rl.training import run_training

        run_id = str(uuid.uuid4())[:8]
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        run_config = {
            "run_id": run_id,
            "grid_id": request.grid_id,
            "agent_type": request.agent_type,
            "timesteps": request.timesteps,
            "status": "queued",
            "created_at": now,
            "device": request.device,
            "active_wrappers": request.active_wrappers,
            "wrapper_config": request.wrapper_config.model_dump(),
            "grid_config": grid_config_dict,
        }

        config_path = run_dir / "run_config.json"
        with open(config_path, "w") as f:
            json.dump(run_config, f, indent=2)

        self._runs[run_id] = RunStatus(
            run_id=run_id,
            grid_id=request.grid_id,
            agent_type=request.agent_type,
            status="queued",
            created_at=now,
            timesteps=request.timesteps,
        )

        future = self._pool.submit(run_training, str(run_dir))

        def _on_done(fut):
            try:
                result = fut.result()
                with open(config_path) as f:
                    data = json.load(f)
                self._runs[run_id] = RunStatus(
                    run_id=run_id,
                    grid_id=request.grid_id,
                    agent_type=request.agent_type,
                    status=data.get("status", "completed"),
                    created_at=now,
                    completed_at=data.get("completed_at"),
                    timesteps=request.timesteps,
                    error=data.get("error"),
                    metrics=data.get("metrics"),
                )
                logger.info("Run %s finished: %s", run_id, data.get("status"))
            except Exception as e:
                self._runs[run_id].status = "failed"
                self._runs[run_id].error = str(e)
                logger.error("Run %s crashed: %s", run_id, e, exc_info=True)

        future.add_done_callback(_on_done)
        return run_id

    def get_run(self, run_id: str) -> Optional[RunStatus]:
        if run_id in self._runs:
            return self._runs[run_id]
        if not _RUN_ID_RE.match(run_id):
            return None
        config_path = RUNS_DIR / run_id / "run_config.json"
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            return RunStatus(
                run_id=run_id,
                grid_id=data["grid_id"],
                agent_type=data["agent_type"],
                status=data.get("status", "unknown"),
                created_at=data["created_at"],
                completed_at=data.get("completed_at"),
                timesteps=data.get("timesteps", 0),
                error=data.get("error"),
                metrics=data.get("metrics"),
            )
        return None

    def list_runs(self) -> list[RunStatus]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    def get_run_dir(self, run_id: str) -> Path:
        if not _RUN_ID_RE.match(run_id):
            raise ValueError(f"Invalid run_id: {run_id!r}")
        return RUNS_DIR / run_id


registry = RunRegistry()

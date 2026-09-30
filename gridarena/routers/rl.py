"""RL Training Router — configure, train, evaluate voltage control models."""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.database as db
from gridarena.rl.grid_loader import build_grid_config_from_db
from gridarena.rl.run_manager import registry
from gridarena.rl.schemas import EvaluateRequest, TrainRequest, TrainResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.post("/train")
async def start_training(request: TrainRequest):
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (request.grid_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Grid '{request.grid_id}' not found.")
    finally:
        conn.close()

    grid_config = build_grid_config_from_db(
        grid_id=request.grid_id,
        volt_ref=request.volt_ref,
        p_min_kw=request.p_min_kw,
        p_max_kw=request.p_max_kw,
        violation_threshold=request.violation_threshold,
        reward_scale=request.reward_scale,
        admittance_scale=request.admittance_scale,
    )

    run_id = registry.start_training(request, grid_config.to_dict())

    return TrainResponse(
        run_id=run_id,
        status="queued",
        message=f"Training started for grid '{request.grid_id}' ({request.agent_type} agent, {request.timesteps} timesteps).",
    )


@router.get("/runs")
async def list_runs():
    runs = registry.list_runs()
    return [r.model_dump() for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run.model_dump()


@router.get("/runs/{run_id}/model")
async def download_model(run_id: str):
    run = registry.get_run(run_id)
    if run is None or run.status != "completed":
        raise HTTPException(status_code=404, detail="Model not available.")

    run_dir = registry.get_run_dir(run_id)
    for name in ["ppo_grid.zip", "ppo_multiagent.zip"]:
        path = run_dir / name
        if path.exists():
            return FileResponse(path, media_type="application/zip", filename=name)

    raise HTTPException(status_code=404, detail="Model file not found.")


@router.post("/evaluate/{run_id}")
async def evaluate_run(run_id: str, request: EvaluateRequest = None):
    run = registry.get_run(run_id)
    if run is None or run.status != "completed":
        raise HTTPException(status_code=400, detail="Run not completed.")

    run_dir = str(registry.get_run_dir(run_id))
    loads = request.loads if request else None

    try:
        from gridarena.rl.evaluation import evaluate_model

        result = evaluate_model(run_dir, loads=loads)
        return result
    except Exception as e:
        logger.error("Evaluation failed for run %s: %s", run_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Evaluation failed. See server logs for details.")


def _fetch_grid_ids() -> list[str]:
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        return [str(r[0]) for r in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def rl_train_page(request: Request):
    grids = _fetch_grid_ids()
    runs = registry.list_runs()
    return templates.TemplateResponse("rl/train.html", {
        "request": request,
        "title": "RL Training",
        "active": "rl",
        "grids": grids,
        "runs": runs,
    })


@router.get("/ui/{run_id}", response_class=HTMLResponse, include_in_schema=False)
async def rl_run_detail_page(request: Request, run_id: str):
    run = registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return templates.TemplateResponse("rl/run_detail.html", {
        "request": request,
        "title": f"Run: {run_id}",
        "active": "rl",
        "run": run.model_dump(),
    })

"""Diffusion Model Router — train generative models, generate synthetic power
data, audit privacy, and search for the best number of epochs."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.database as db
from gridarena.diffusion.run_manager import diffusion_registry
from gridarena.diffusion.schemas import (
    DiffusionEpochSearchRequest,
    DiffusionPrivacyCheckRequest,
    DiffusionTrainRequest,
    DiffusionTrainResponse,
    GenerateSnapshotRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# Selectable backbones surfaced to the UI (kept in sync with schemas.Architecture).
ARCHITECTURES = [
    {"value": "axial", "label": "Axial (cross-node attention) — recommended"},
    {"value": "deepsets", "label": "Deep Sets (pooling) — cheapest"},
    {"value": "gnn", "label": "Graph (GCN message passing)"},
    {"value": "unet2d", "label": "UNet2D (legacy 2D conv; needs even node count)"},
]

# Jobs that persist a generatable/downloadable model.
_MODEL_JOB_TYPES = ("train", "epoch_search")

# Whitelisted report figure filenames per job type.
_FIGURE_FILES = {
    "mi_loss_distributions.png",
    "canary_nn_distances.png",
    "metrics_vs_epoch.png",
}


def _validate_grids(grid_ids):
    conn, cursor = db.get_db_connection()
    try:
        for grid_id in grid_ids:
            cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (grid_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Grid '{grid_id}' not found.")
    finally:
        conn.close()


# ── Training ────────────────────────────────────────────────────────────────


@router.post("/train")
async def start_diffusion_training(request: DiffusionTrainRequest):
    _validate_grids(request.grid_ids)
    run_id = diffusion_registry.start_training(request)
    return DiffusionTrainResponse(
        run_id=run_id,
        status="queued",
        message=f"Diffusion training started for grids {request.grid_ids} "
                f"({request.architecture}, {request.num_epochs} epochs).",
    )


@router.post("/privacy-check")
async def start_privacy_check(request: DiffusionPrivacyCheckRequest):
    """Run the empirical privacy audit (membership inference + canary memorisation)."""
    _validate_grids(request.grid_ids)
    run_id = diffusion_registry.start_privacy_check(request)
    return DiffusionTrainResponse(
        run_id=run_id,
        status="queued",
        message=f"Privacy check started for grids {request.grid_ids} ({request.architecture}).",
    )


@router.post("/epoch-search")
async def start_epoch_search(request: DiffusionEpochSearchRequest):
    """Run the epoch-selection sweep to find the best number of epochs."""
    _validate_grids(request.grid_ids)
    run_id = diffusion_registry.start_epoch_search(request)
    return DiffusionTrainResponse(
        run_id=run_id,
        status="queued",
        message=f"Epoch search started for grids {request.grid_ids} "
                f"({request.architecture}, up to {request.max_epochs} epochs).",
    )


# ── Run queries ─────────────────────────────────────────────────────────────


@router.get("/runs")
async def list_diffusion_runs():
    return [r.model_dump() for r in diffusion_registry.list_runs()]


@router.get("/runs/{run_id}")
async def get_diffusion_run(run_id: str):
    run = diffusion_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run.model_dump()


@router.get("/runs/{run_id}/model")
async def download_diffusion_model(run_id: str):
    run = diffusion_registry.get_run(run_id)
    if run is None or run.status != "completed" or run.job_type not in _MODEL_JOB_TYPES:
        raise HTTPException(status_code=404, detail="Model not available.")

    zip_path = diffusion_registry.get_run_dir(run_id) / "diffusion_model.zip"
    if zip_path.exists():
        return FileResponse(zip_path, media_type="application/zip", filename=f"diffusion_model_{run_id}.zip")
    raise HTTPException(status_code=404, detail="Model file not found.")


def _load_report(run_id: str, filename: str) -> dict:
    run = diffusion_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    report_path = diffusion_registry.get_run_dir(run_id) / filename
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not available yet.")
    with open(report_path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/runs/{run_id}/privacy-report")
async def get_privacy_report(run_id: str):
    return _load_report(run_id, "privacy_report.json")


@router.get("/runs/{run_id}/epoch-report")
async def get_epoch_report(run_id: str):
    return _load_report(run_id, "epoch_search_report.json")


@router.get("/runs/{run_id}/figure/{name}")
async def get_run_figure(run_id: str, name: str):
    if name not in _FIGURE_FILES:
        raise HTTPException(status_code=404, detail="Unknown figure.")
    fig_path = diffusion_registry.get_run_dir(run_id) / name
    if not fig_path.exists():
        raise HTTPException(status_code=404, detail="Figure not available.")
    return FileResponse(fig_path, media_type="image/png")


@router.post("/generate/{run_id}")
async def generate_snapshot(run_id: str, request: GenerateSnapshotRequest = None):
    """Generate a single synthetic daily power snapshot from a trained model."""
    run = diffusion_registry.get_run(run_id)
    if run is None or run.status != "completed" or run.job_type not in _MODEL_JOB_TYPES:
        raise HTTPException(status_code=400, detail="Run has no generatable model.")

    run_dir = str(diffusion_registry.get_run_dir(run_id))
    try:
        from gridarena.diffusion.model_core import generate_snapshot as _generate

        req = request or GenerateSnapshotRequest()
        return _generate(model_dir=run_dir, num_inference_steps=req.num_inference_steps, device=req.device)
    except Exception as e:
        logger.error("Snapshot generation failed for run %s: %s", run_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Generation failed. See server logs for details.")


# ── UI ──────────────────────────────────────────────────────────────────────


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
async def diffusion_train_page(request: Request):
    grids = _fetch_grid_ids()
    runs = diffusion_registry.list_runs()
    return templates.TemplateResponse("diffusion/train.html", {
        "request": request,
        "title": "Diffusion Models",
        "active": "diffusion",
        "grids": grids,
        "runs": runs,
        "architectures": ARCHITECTURES,
    })


@router.get("/ui/{run_id}", response_class=HTMLResponse, include_in_schema=False)
async def diffusion_run_detail_page(request: Request, run_id: str):
    run = diffusion_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    run_dir = diffusion_registry.get_run_dir(run_id)
    privacy_report = None
    epoch_report = None
    if run.job_type == "privacy_check":
        p = run_dir / "privacy_report.json"
        if p.exists():
            privacy_report = json.loads(p.read_text(encoding="utf-8"))
    elif run.job_type == "epoch_search":
        p = run_dir / "epoch_search_report.json"
        if p.exists():
            epoch_report = json.loads(p.read_text(encoding="utf-8"))

    return templates.TemplateResponse("diffusion/run_detail.html", {
        "request": request,
        "title": f"Diffusion Run: {run_id}",
        "active": "diffusion",
        "run": run.model_dump(),
        "privacy_report": privacy_report,
        "epoch_report": epoch_report,
    })

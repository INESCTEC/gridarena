"""MV Power-Flow Data-Generation Router -- JSON API only.

There is no HTML page under this router: the feature is reached entirely
from the MV grid detail page (/mv_grid/ui/{mv_grid_id}), whose JS calls the
endpoints below directly. See gridarena/pf_datagen/ for the pipeline itself.
"""

import io
import logging
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

import gridarena.database as db
from gridarena.pf_datagen.run_manager import pf_datagen_registry
from gridarena.pf_datagen.schemas import PFDataGenRequest, PFDataGenStartResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_mv_grid(mv_grid_id: str, cursor):
    cursor.execute('SELECT 1 FROM "MVGrid" WHERE mv_grid_id = %s', (mv_grid_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"MV Grid '{mv_grid_id}' not found.")


@router.post("/mv/{mv_grid_id}/run")
async def start_pf_datagen_run(mv_grid_id: str, request: PFDataGenRequest):
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        _require_mv_grid(mv_grid_id, cursor)
    finally:
        conn.close()

    run_id = pf_datagen_registry.start_run(mv_grid_id, request)
    return PFDataGenStartResponse(
        run_id=run_id, status="queued",
        message=f"PF data-generation run started for MV grid '{mv_grid_id}'.",
    )


@router.get("/mv/{mv_grid_id}/runs")
async def list_pf_datagen_runs_for_grid(mv_grid_id: str):
    return [r.model_dump() for r in pf_datagen_registry.list_runs(mv_grid_id=mv_grid_id)]


@router.get("/runs")
async def list_all_pf_datagen_runs():
    """All runs across every MV grid -- backs the PF Data Generation tab on the MV grids home page."""
    return [r.model_dump() for r in pf_datagen_registry.list_runs()]


@router.get("/runs/{run_id}")
async def get_pf_datagen_run(run_id: str):
    run = pf_datagen_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    payload = run.model_dump()
    if run.status == "completed":
        conn, cursor = db.get_db_connection()
        try:
            db.create_pf_datagen_database(conn, cursor)
            payload["summary"] = db.get_pf_datagen_summary(run_id, cursor)
        finally:
            conn.close()
    return payload


@router.get("/runs/{run_id}/results")
async def get_pf_datagen_run_results(
    run_id: str,
    table: Literal["bus", "branch", "ybus", "runtime"] = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    run = pf_datagen_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    conn, cursor = db.get_db_connection()
    try:
        db.create_pf_datagen_database(conn, cursor)
        rows, columns = db.get_pf_datagen_results(run_id, table, cursor, limit=limit, offset=offset)
    except Exception as e:
        logger.error("PF datagen results fetch failed for run %s/%s: %s", run_id, table, e, exc_info=True)
        raise HTTPException(status_code=400, detail="Could not fetch results. See server logs for details.")
    finally:
        conn.close()

    return {"run_id": run_id, "table": table, "columns": columns, "rows": rows}


@router.get("/runs/{run_id}/export.csv")
async def export_pf_datagen_run(run_id: str, table: Literal["bus", "branch", "ybus", "runtime"] = Query(...)):
    run = pf_datagen_registry.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    conn, cursor = db.get_db_connection()
    try:
        db.create_pf_datagen_database(conn, cursor)
        rows, columns = db.get_pf_datagen_all_rows(run_id, table, cursor)
    except Exception as e:
        logger.error("PF datagen export failed for run %s/%s: %s", run_id, table, e, exc_info=True)
        raise HTTPException(status_code=400, detail="Could not export results. See server logs for details.")
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=columns)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    filename = f"pf_datagen_{run_id}_{table}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

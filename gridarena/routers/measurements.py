"""Measurements Router with endpoints to register, access and delete node/grid-scoped measurement data"""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

import gridarena.database as db
from gridarena.schemas import MeasurementsData

from ._upload_guard import ensure_upload_size_ok

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# Safety cap for unbounded list queries (e.g. no start/end filter given) --
# prevents a single request from serializing the entire Measurements table.
MAX_RECORDS_PER_REQUEST = 50_000


@router.post("/")
async def register_measurements_data(file: UploadFile = File(...)):
    """
    Uploads and inserts measurement data into the database from a JSON file.

    Parameters:
        file (UploadFile): A JSON file containing the measurement data to be uploaded.

    Raises:
        HTTPException 400: If the file is not valid JSON.
        HTTPException 422: If the file does not conform to the MeasurementsData schema.
        HTTPException 500: If a database error occurs during the insertion.

    Returns:
        dict: A success message with the grid ID.
    """
    ensure_upload_size_ok(file)
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        measurements_data = MeasurementsData(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    conn, cursor = db.get_db_connection()

    try:
        db.create_measurements_tables(cursor)
        db.insert_measurements_data(measurements_data, conn, cursor)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {
        "message": f"Measurement data for grid '{measurements_data.grid_id}' inserted successfully."
    }


@router.delete("/{grid_id}")
async def delete_measurements(
    grid_id: str,
    start: Optional[str] = Query(None, description="Start datetime ISO (inclusive)"),
    end: Optional[str] = Query(None, description="End datetime ISO (exclusive)"),
    node_id: Optional[str] = Query(None, description="Optional node_id filter"),
    phase: Optional[Literal["R", "S", "T"]] = Query(
        None, description="Optional phase filter; omit to delete aggregated + all phases"
    ),
):
    """
    Deletes measurement records for a given grid.

    Parameters:
        grid_id (str): The unique identifier for the grid.
        start (str, optional): ISO start datetime (inclusive).
        end (str, optional): ISO end datetime (exclusive).
        node_id (str, optional): Filter by node.
        phase (str, optional): Filter by phase (R/S/T).

    Raises:
        HTTPException 400: If an invalid datetime format is provided.
        HTTPException 500: If a database error occurs.

    Returns:
        dict: A message indicating how many records were deleted.
    """
    try:
        start_dt = datetime.fromisoformat(start) if start else None
        end_dt = datetime.fromisoformat(end) if end else None

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime format. Use ISO format (e.g. 2025-07-31T00:00:00)",
        )

    conn, cursor = db.get_db_connection()

    try:
        query = 'DELETE FROM "Measurements" WHERE grid_id = %s'
        params: list[object] = [grid_id]

        if node_id:
            query += " AND node_id = %s"
            params.append(node_id)
        if phase is not None:
            query += " AND phase = %s"
            params.append(phase)
        if start_dt:
            query += " AND datetime >= %s"
            params.append(start_dt)
        if end_dt:
            query += " AND datetime < %s"
            params.append(end_dt)

        cursor.execute(query, tuple(params))
        deleted_count = cursor.rowcount
        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {"message": f"{deleted_count} measurement(s) deleted for grid '{grid_id}'."}


@router.get("/data/{grid_id}")
async def get_measurements_data(
    grid_id: str,
    node_id: Optional[str] = Query(None, description="Filter by node_id (optional)"),
    start: Optional[str] = Query(None, description="Start datetime (inclusive, ISO format)"),
    end: Optional[str] = Query(None, description="End datetime (exclusive, ISO format)"),
    per_phase: bool = Query(
        True,
        description="If true, returns rows with phase in {'R','S','T'}; if false, returns aggregated (phase IS NULL).",
    ),
    phase: Optional[Literal["R", "S", "T"]] = Query(
        None, description="When per_phase=true, filter a single phase (R/S/T)"
    ),
):
    """
    Retrieves measurement records for a given grid.

    Parameters:
        grid_id (str): The grid to retrieve measurements for.
        node_id (str, optional): Filter by node.
        start / end (str, optional): ISO datetime range.
        per_phase (bool): If true returns per-phase rows; if false returns aggregated.
        phase (str, optional): Single phase filter when per_phase=true.

    Raises:
        HTTPException 400/404/500 as appropriate.

    Returns:
        dict: Grid data with records and count.
    """
    try:
        start_dt = datetime.fromisoformat(start) if start else None
        end_dt = datetime.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO format.")

    if phase and not per_phase:
        raise HTTPException(status_code=400, detail="Parameter 'phase' requires per_phase=true.")

    conn, cursor = db.get_db_connection()

    try:
        sql = """
            SELECT node_id, datetime, phase,
                   power_active, power_reactive, voltage_magnitude, voltage_angle
            FROM "Measurements"
            WHERE grid_id = %s
        """
        params: list[object] = [grid_id]

        if node_id:
            sql += " AND node_id = %s"
            params.append(node_id)
        if start_dt:
            sql += " AND datetime >= %s"
            params.append(start_dt)
        if end_dt:
            sql += " AND datetime < %s"
            params.append(end_dt)

        if per_phase:
            sql += " AND phase IS NOT NULL"
            if phase:
                sql += " AND phase = %s"
                params.append(phase)
        else:
            sql += " AND phase IS NULL"

        sql += " ORDER BY datetime ASC LIMIT %s"
        params.append(MAX_RECORDS_PER_REQUEST + 1)

        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(
                status_code=404, detail="No measurements found matching the criteria."
            )

        truncated = len(rows) > MAX_RECORDS_PER_REQUEST
        if truncated:
            rows = rows[:MAX_RECORDS_PER_REQUEST]

        columns = [
            "node_id",
            "datetime",
            "phase",
            "power_active",
            "power_reactive",
            "voltage_magnitude",
            "voltage_angle",
        ]
        data = [dict(zip(columns, row)) for row in rows]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {
        "grid_id": grid_id,
        "node_id": node_id,
        "per_phase": per_phase,
        "phase": phase,
        "datetime_range": {"start": start, "end": end},
        "records": data,
        "count": len(data),
        "truncated": truncated,
        **({"truncation_hint": f"Result capped at {MAX_RECORDS_PER_REQUEST} records; narrow with start/end."} if truncated else {}),
    }


def _fetch_grid_ids() -> list[str]:
    """Get all the available grid_ids in the database."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute('SELECT grid_id FROM grids ORDER BY grid_id COLLATE "C" ASC')
        rows = cursor.fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ---------- UI: ROOT ----------


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def measurements_ui_root(request: Request) -> HTMLResponse:
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            """
            SELECT g.grid_id,
                   COUNT(m.measurement_id) AS n_records,
                   COUNT(DISTINCT m.node_id) AS n_nodes,
                   MIN(m.datetime) AS first_ts,
                   MAX(m.datetime) AS last_ts
            FROM grids g
            LEFT JOIN "Measurements" m ON m.grid_id = g.grid_id
            GROUP BY g.grid_id
            ORDER BY g.grid_id COLLATE "C" ASC
            """
        )
        items = [{
            "grid_id": r[0],
            "n_records": r[1],
            "n_nodes": r[2],
            "first_ts": str(r[3])[:16] if r[3] else None,
            "last_ts": str(r[4])[:16] if r[4] else None,
        } for r in cursor.fetchall()]
    except Exception:
        items = []
    finally:
        conn.close()

    total_records = sum(g["n_records"] for g in items)
    grids_with_data = sum(1 for g in items if g["n_records"] > 0)

    return templates.TemplateResponse("measurements/list.html", {
        "request": request,
        "title": "Measurements",
        "active": "measurements",
        "items": items,
        "total_records": total_records,
        "grids_with_data": grids_with_data,
    })


# ---------- UI: GRID DETAIL ----------


@router.get("/ui/{grid_id}", response_class=HTMLResponse, include_in_schema=False)
def measurements_ui_grid(
    request: Request,
    grid_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    phase: list[str] | None = Query(None),
) -> HTMLResponse:
    """Dashboard view for measurements of a grid."""
    conn, _ = db.get_db_connection()

    selected_phases = [p for p in (phase or []) if p in {"R", "S", "T"}]

    query = (
        "SELECT datetime, node_id, phase, power_active, power_reactive, voltage_magnitude "
        'FROM "Measurements" WHERE grid_id = %s'
    )
    params: list[object] = [grid_id]

    if start:
        query += " AND datetime >= %s"
        params.append(start)
    if end:
        query += " AND datetime <= %s"
        params.append(end)
    if selected_phases:
        query += " AND phase = ANY(%s)"
        params.append(selected_phases)

    query += " ORDER BY datetime ASC, node_id ASC, phase ASC LIMIT %s"
    params.append(MAX_RECORDS_PER_REQUEST)

    try:
        df = pd.read_sql_query(query, conn, params=params)
    except Exception:
        conn.close()
        raise HTTPException(status_code=404, detail=f"No data found for grid '{grid_id}'.")
    finally:
        conn.close()

    if df.empty:
        return templates.TemplateResponse("measurements/detail.html", {
            "request": request,
            "title": f"Measurements: {grid_id}",
            "active": "measurements",
            "grid_id": grid_id,
            "empty": True,
        })

    df["datetime"] = df["datetime"].astype(str)
    df["phase"] = df["phase"].fillna("N/A").astype(str)

    records = df.to_dict(orient="records")
    all_nodes = sorted(df["node_id"].unique().tolist())
    all_phases = sorted([p for p in df["phase"].unique().tolist() if p != "N/A"])

    checked_r = not selected_phases or "R" in selected_phases
    checked_s = not selected_phases or "S" in selected_phases
    checked_t = not selected_phases or "T" in selected_phases

    return templates.TemplateResponse("measurements/detail.html", {
        "request": request,
        "title": f"Measurements: {grid_id}",
        "active": "measurements",
        "grid_id": grid_id,
        "empty": False,
        "start": start,
        "end": end,
        "checked_r": checked_r,
        "checked_s": checked_s,
        "checked_t": checked_t,
        "records": records,
        "all_nodes": all_nodes,
        "all_phases": all_phases,
        "record_count": len(records),
    })

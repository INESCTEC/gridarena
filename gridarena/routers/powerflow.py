"""Power Flow Router"""

from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.database as db
import gridarena.powerflow.get_grid_info as gd
import gridarena.powerflow.get_measurement_info as ms
from gridarena.powerflow.powerflow_algorithm import full_pf
from gridarena.database import NotFoundError

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def single_timestamp_power_flow(cursor, grid_id, timestamp, phase):
    """
    Executes the power flow calculation for a specific grid, timestamp, and electrical phase.

    Parameters:
        cursor: Active database cursor for executing queries.
        grid_id (str): The identifier of the grid.
        timestamp (str): ISO 8601 formatted timestamp for which to run the power flow.
        phase (str): Electrical phase to consider ("R", "S", or "T").

    Returns:
        np.ndarray: A complex-valued array of nodal voltages (V) resulting from the power flow.
    """

    node_id_to_index = gd.get_nodes_from_grid(grid_id, cursor)
    S_array = ms.get_measurement_from_timestamp(cursor, grid_id, node_id_to_index, timestamp, phase)
    connections, conn_data = gd.get_grid_connections(cursor, grid_id, node_id_to_index)
    admittances = gd.get_grid_admitances(cursor, conn_data)
    reference_voltage = ms.get_pt_voltage(cursor, grid_id, timestamp, phase)

    volt_values = full_pf(np.array(S_array), connections, np.array(admittances), reference_voltage)

    db.insert_pf_data(node_id_to_index, volt_values, grid_id, phase, timestamp, cursor)


@router.post("/{grid_id}/run")
async def run_power_flow(
    grid_id: str,
    phase: Literal["R", "S", "T"] = Query(),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
):
    """
    Runs the power flow algorithm for all timestamps within a specified range.

    Parameters:
        grid_id (str): The unique identifier of the grid to analyse.
        phase (str): The phase ("R", "S", or "T") to use.
        start_time (str, optional): Lower bound for the timestamp range (ISO 8601).
        end_time (str, optional): Upper bound for the timestamp range (ISO 8601).

    Returns:
        dict: Dictionary with message.

    Raises:
        HTTPException: If there is a problem with input parameters or database access.
    """

    conn, cursor = db.get_db_connection()

    try:
        db.create_pf_database(cursor)

        query = """
            SELECT DISTINCT datetime
            FROM "Measurements"
            WHERE grid_id = %s AND phase = %s
        """
        params = [grid_id, phase]

        if start_time:
            query += " AND datetime >= %s"
            params.append(start_time)
        if end_time:
            query += " AND datetime <= %s"
            params.append(end_time)

        query += " ORDER BY datetime"

        cursor.execute(query, params)
        timestamps = [row[0] for row in cursor.fetchall()]

        if not timestamps:
            raise NotFoundError("No measurement timestamps found for the given range.")

        for timestamp in timestamps:
            single_timestamp_power_flow(cursor, grid_id, timestamp, phase)
            conn.commit()

        return {"message": "Power flow has been run successfully."}

    except NotFoundError as e:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error: {e}")

    finally:
        conn.close()


@router.get("/data/{grid_id}/results")
async def get_power_flow_results(grid_id: str, phase: Literal["R", "S", "T"] = Query(...)):
    """
    Retrieve stored power flow results for a given grid and phase.

    Parameters:
        grid_id (str): The unique identifier of the grid.
        phase (str): The electrical phase ("R", "S", or "T").

    Returns:
        dict: Dictionary with grid, phase, and a list of results.

    Raises:
        HTTPException: If no results are found or a database error occurs.
    """
    conn, cursor = db.get_db_connection()
    try:
        query = """
            SELECT node_id, datetime, voltage_real, voltage_imag
            FROM "PowerFlowResults"
            WHERE grid_id = %s AND phase = %s
            ORDER BY datetime, node_id
        """

        try:
            cursor.execute(query, (grid_id, phase))
            rows = cursor.fetchall()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {e}",
            ) from e

        if not rows:
            raise HTTPException(status_code=404, detail="No power flow results found.")

        results = [
            {"timestamp": row[1], "node_id": row[0], "voltage": {"real": row[2], "imag": row[3]}}
            for row in rows
        ]

        return {"grid_id": grid_id, "phase": phase, "results": results}

    finally:
        conn.close()


# ---------- HELPERS ----------


def _fetch_grid_data_for_ui(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT g.grid_id,
               COUNT(DISTINCT n."NodeId") AS n_nodes,
               CASE WHEN EXISTS (
                   SELECT 1 FROM "Measurements" m WHERE m.grid_id = g.grid_id LIMIT 1
               ) THEN TRUE ELSE FALSE END AS has_historical,
               CASE WHEN EXISTS (
                   SELECT 1 FROM "PowerFlowResults" p WHERE p.grid_id = g.grid_id LIMIT 1
               ) THEN TRUE ELSE FALSE END AS has_results
        FROM grids g
        LEFT JOIN "Node" n ON n.grid_id = g.grid_id
        GROUP BY g.grid_id
        ORDER BY g.grid_id ASC
        """
    )
    return [{
        "grid_id": r[0], "n_nodes": r[1],
        "has_historical": r[2], "has_results": r[3],
    } for r in cursor.fetchall()]


# ---------- ROOT PAGE ----------


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def powerflow_ui_root(request: Request) -> HTMLResponse:
    """Power Flow Simulator workspace."""
    conn, cursor = db.get_db_connection()
    try:
        grids = _fetch_grid_data_for_ui(cursor)
    except Exception:
        grids = []
    finally:
        conn.close()

    grids_with_results = sum(1 for g in grids if g["has_results"])

    return templates.TemplateResponse("powerflow/list.html", {
        "request": request,
        "title": "Power Flow Simulator",
        "active": "algorithms",
        "grids": grids,
        "grids_with_results": grids_with_results,
    })


# ---------- RESULTS PAGE ----------


@router.get("/ui/{grid_id}", response_class=HTMLResponse, include_in_schema=False)
def powerflow_ui_results(
    request: Request,
    grid_id: str,
    phase: str = Query("R", description="Phase (R/S/T)"),
):
    """Page showing Power Flow results with phase selector."""
    conn, cursor = db.get_db_connection()
    try:
        query = """
            SELECT node_id, datetime, voltage_real, voltage_imag
            FROM "PowerFlowResults"
            WHERE grid_id = %s AND phase = %s
            ORDER BY datetime, node_id
        """
        cursor.execute(query, (grid_id, phase))
        df = pd.DataFrame(cursor.fetchall(), columns=["node_id", "datetime", "real", "imag"])
    finally:
        conn.close()

    if df.empty:
        return templates.TemplateResponse("powerflow/results.html", {
            "request": request,
            "title": f"Power Flow: {grid_id}",
            "active": "algorithms",
            "grid_id": grid_id,
            "phase": phase,
            "empty": True,
        })

    df["datetime"] = df["datetime"].astype(str)
    df["magnitude"] = (df["real"] ** 2 + df["imag"] ** 2) ** 0.5
    df["angle"] = np.degrees(np.arctan2(df["imag"], df["real"]))

    traces_mag, traces_ang = [], []
    for node in sorted(df["node_id"].unique()):
        subset = df[df["node_id"] == node]
        traces_mag.append({
            "x": subset["datetime"].tolist(),
            "y": subset["magnitude"].tolist(),
            "mode": "lines",
            "name": f"{node}",
        })
        traces_ang.append({
            "x": subset["datetime"].tolist(),
            "y": subset["angle"].tolist(),
            "mode": "lines",
            "name": f"{node}",
        })

    table_html = df.to_html(index=False, classes="data-table", border=0)

    return templates.TemplateResponse("powerflow/results.html", {
        "request": request,
        "title": f"Power Flow: {grid_id}",
        "active": "algorithms",
        "grid_id": grid_id,
        "phase": phase,
        "empty": False,
        "traces_mag": traces_mag,
        "traces_ang": traces_ang,
        "table_html": table_html,
    })

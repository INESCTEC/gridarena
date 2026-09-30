"""Grid Router with endpoints to register, access and delete grids"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import List, Literal

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError
from starlette.status import HTTP_302_FOUND

import gridarena.database as db
import gridarena.schemas as schema
from gridarena.database import NotFoundError

from ._upload_guard import ensure_upload_size_ok

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

_TABLE_MAP = {
    "Node": '"Node"',
    "Cable": '"Cable"',
    "Connection": '"Connection"',
    "grids": "grids",
}


# ---------- Validation helpers --------------------------------------------------


def _validate_grid(grid: schema.Grid) -> List[str]:
    """Validate internal references in a grid. Returns list of error strings."""
    errors = []
    node_ids = {n.node_id for n in grid.nodes}

    if not grid.grid_id:
        errors.append("grid_id is required.")

    if not grid.nodes:
        errors.append("At least one node is required.")

    node_id_counts = {}
    for n in grid.nodes:
        node_id_counts[n.node_id] = node_id_counts.get(n.node_id, 0) + 1
    for nid, count in node_id_counts.items():
        if count > 1:
            errors.append(f"Duplicate node_id '{nid}'.")

    cable_ids = set()
    if grid.cables:
        for c in grid.cables:
            if c.cable_id in cable_ids:
                errors.append(f"Duplicate cable_id '{c.cable_id}'.")
            cable_ids.add(c.cable_id)

    if grid.connections:
        conn_ids = set()
        for c in grid.connections:
            if c.connection_id in conn_ids:
                errors.append(f"Duplicate connection_id '{c.connection_id}'.")
            conn_ids.add(c.connection_id)

            if c.from_node_id not in node_ids:
                errors.append(f"Connection '{c.connection_id}': from_node_id '{c.from_node_id}' not found in nodes.")
            if c.to_node_id not in node_ids:
                errors.append(f"Connection '{c.connection_id}': to_node_id '{c.to_node_id}' not found in nodes.")
            if c.cable_id not in cable_ids:
                errors.append(f"Connection '{c.connection_id}': cable_id '{c.cable_id}' not found in cables.")

    return errors


def _compute_lv_graph_layout(grid_data: dict) -> dict:
    """Build a NetworkX graph and return node positions + edges for frontend rendering."""
    G = nx.Graph()
    nodes = grid_data.get("nodes", [])
    connections = grid_data.get("connections", [])

    for n in nodes:
        nid = n.get("node_id", "")
        G.add_node(nid)

    for c in connections:
        fid = c.get("from_node_id", "")
        tid = c.get("to_node_id", "")
        if fid and tid:
            G.add_edge(fid, tid)

    has_coords = all(n.get("coord_lat") is not None and n.get("coord_lon") is not None for n in nodes)

    if has_coords:
        pos = {n["node_id"]: (float(n["coord_lon"]), float(n["coord_lat"])) for n in nodes}
    else:
        pos = nx.spring_layout(G, seed=42)
        pos = {k: (float(v[0]), float(v[1])) for k, v in pos.items()}

    graph_nodes = []
    for nid in G.nodes():
        x, y = pos.get(nid, (0, 0))
        ntype = "pt" if nid == "PT" else "normal"
        graph_nodes.append({"id": nid, "x": x, "y": y, "type": ntype})

    graph_edges = [{"from": u, "to": v} for u, v in G.edges()]

    return {"nodes": graph_nodes, "edges": graph_edges}


# ---------- API Endpoints -------------------------------------------------------


@router.post("/validate")
async def validate_grid(file: UploadFile = File(...)):
    """Validate a grid JSON without saving. Returns parsed grid, graph layout, or errors."""
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        grid = schema.Grid(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    errors = _validate_grid(grid)
    if errors:
        return {"valid": False, "errors": errors}

    grid_dump = grid.model_dump()
    graph_data = _compute_lv_graph_layout(grid_dump)

    return {"valid": True, "grid": grid_dump, "graph": graph_data}


@router.post("/")
async def register_grid(
    file: UploadFile = File(None),
    phase_detection_test: Literal["YES", "NO"] = Query(),
    phase_detection_train: Literal["YES", "NO"] = Query(),
    topology_detection_test: Literal["YES", "NO"] = Query(),
    topology_detection_train: Literal["YES", "NO"] = Query(),
    voltage_control_test: Literal["YES", "NO"] = Query(),
    voltage_control_train: Literal["YES", "NO"] = Query(),
    state_estimation_test: Literal["YES", "NO"] = Query(),
    state_estimation_train: Literal["YES", "NO"] = Query(),
):
    """Register a new Grid from a JSON file with usage flags."""
    if file is None:
        raise HTTPException(status_code=400, detail="A grid JSON file is required.")
    ensure_upload_size_ok(file)
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        grid = schema.Grid(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    errors = _validate_grid(grid)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    conn, cursor = db.get_db_connection()
    try:
        db.create_grid_database(grid.grid_id, conn, cursor)

        usage_dict = {
            "phase_detection_test": 1 if phase_detection_test == "YES" else 0,
            "phase_detection_train": 1 if phase_detection_train == "YES" else 0,
            "topology_detection_test": 1 if topology_detection_test == "YES" else 0,
            "topology_detection_train": 1 if topology_detection_train == "YES" else 0,
            "voltage_control_test": 1 if voltage_control_test == "YES" else 0,
            "voltage_control_train": 1 if voltage_control_train == "YES" else 0,
            "state_estimation_test": 1 if state_estimation_test == "YES" else 0,
            "state_estimation_train": 1 if state_estimation_train == "YES" else 0,
        }

        db.insert_grid_data(grid, conn, cursor, usage_dict)

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {"message": f"Grid '{grid.grid_id}' registered successfully."}


@router.delete("/{grid_id}")
async def delete_grid(grid_id: str):
    """
    Deletes a grid and all associated data from the database.

    Parameters:
        grid_id (str): Unique identifier of the grid to be deleted.

    Raises:
        HTTPException 404: If the grid does not exist.
        HTTPException 500: If a database error occurs during the deletion process.

    Returns:
        dict: A success message confirming the deletion of the grid and its data.
    """

    conn, cursor = db.get_db_connection()
    try:
        db.delete_grid(grid_id, conn, cursor)
    except NotFoundError as e:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"{e}")
    finally:
        conn.close()

    return {"message": f"Grid '{grid_id}' and all associated data were deleted successfully."}


@router.get("/data/{grid_id}")
async def get_grid(
    grid_id: str,
    table: Literal["Node", "Cable", "Connection", "grids"] = Query(...),
):
    """
    Retrieves records from a specific table associated with a given grid ID.

    Parameters:
        grid_id (str): Unique identifier of the grid whose data is being queried.
        table (Literal): The name of the table to query.

    Raises:
        HTTPException 404: If no records are found for the specified grid ID.
        HTTPException 500: If a database error occurs during the query.

    Returns:
        dict: A dictionary containing the queried table, grid ID, and records.
    """
    table_sql = _TABLE_MAP[table]

    conn, cursor = db.get_db_connection()
    try:
        if table == "grids":
            cursor.execute("SELECT * FROM grids WHERE grid_id = %s", (grid_id,))
        else:
            cursor.execute(f"SELECT * FROM {table_sql} WHERE grid_id = %s", (grid_id,))

        rows = cursor.fetchall()
        columns = [desc.name for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in rows]

        if not results:
            raise HTTPException(
                status_code=404, detail=f"No data found in table '{table}' for grid_id '{grid_id}'."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {"table": table, "grid_id": grid_id, "records": results}


# ---------- UI Routers -----------------------------------------------------------


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def ui_list_grids(request: Request) -> HTMLResponse:
    """LV Grid management dashboard."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            """
            SELECT g.grid_id,
                   COALESCE(n.cnt, 0) AS n_nodes,
                   COALESCE(c.cnt, 0) AS n_connections,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM "Measurements" m WHERE m.grid_id = g.grid_id LIMIT 1
                   ) THEN TRUE ELSE FALSE END AS has_historical
            FROM grids g
            LEFT JOIN (SELECT grid_id, COUNT(*) AS cnt FROM "Node" GROUP BY grid_id) n
                ON n.grid_id = g.grid_id
            LEFT JOIN (SELECT grid_id, COUNT(*) AS cnt FROM "Connection" GROUP BY grid_id) c
                ON c.grid_id = g.grid_id
            ORDER BY g.grid_id COLLATE "C" ASC
            """
        )
        items = [{"grid_id": r[0], "n_nodes": r[1], "n_connections": r[2], "has_historical": r[3]}
                 for r in cursor.fetchall()]
    except Exception:
        items = []
    finally:
        conn.close()

    total_nodes = sum(g["n_nodes"] for g in items)

    return templates.TemplateResponse("grid/list.html", {
        "request": request,
        "title": "Low Voltage Grids",
        "active": "grid",
        "items": items,
        "total_nodes": total_nodes,
    })


@router.get("/ui/{grid_id}", response_class=HTMLResponse)
def grid_detail_ui(request: Request, grid_id: str):
    """HTML page showing the interactive graph and data tables for a grid."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute('SELECT "NodeId", "CoordLat", "CoordLon" FROM "Node" WHERE grid_id = %s', (grid_id,))
        nodes = [{"node_id": r[0], "coord_lat": r[1], "coord_lon": r[2]} for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT c."ConnectionId", c."FromNodeId", c."ToNodeId", c."CableId", c."Length",
                   cb."RImpReal", cb."RImpImag"
            FROM "Connection" c
            LEFT JOIN "Cable" cb ON cb."CableId" = c."CableId" AND cb.grid_id = c.grid_id
            WHERE c.grid_id = %s
            """,
            (grid_id,),
        )
        connections = []
        for r in cursor.fetchall():
            length = r[4] or 0
            r_real = r[5] or 0
            r_imag = r[6] or 0
            # R/X are specified in ohm/km while length is in metres, so convert
            # the length to km before multiplying to get the total impedance in ohm.
            length_km = length / 1000.0
            z_total_real = round(r_real * length_km, 4)
            z_total_imag = round(r_imag * length_km, 4)
            connections.append({
                "connection_id": r[0],
                "from_node_id": r[1],
                "to_node_id": r[2],
                "cable_id": r[3],
                "length": length,
                "z_real": z_total_real,
                "z_imag": z_total_imag,
            })

        cursor.execute(
            'SELECT "CableId", "RImpReal", "RImpImag", "RNomCurr" FROM "Cable" WHERE grid_id = %s',
            (grid_id,),
        )
        cables = [{"cable_id": r[0], "imp_real": r[1], "imp_imag": r[2], "nom_curr": r[3]} for r in cursor.fetchall()]
    finally:
        conn.close()

    grid_data = {"nodes": nodes, "connections": connections}
    graph_data = _compute_lv_graph_layout(grid_data)

    return templates.TemplateResponse("grid/detail.html", {
        "request": request,
        "title": f"Grid: {html.escape(grid_id)}",
        "active": "grid",
        "grid_id": grid_id,
        "nodes": nodes,
        "connections": connections,
        "cables": cables,
        "graph_data": graph_data,
    })


# ---------- Helpers --------------------------------------------------------------

IMG_DIR = Path("data/previews/png")


def create_grid_image(grid_id: str) -> Path:
    """Create a PNG for a grid's network using edges from the Connection table."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            'SELECT "FromNodeId", "ToNodeId" FROM "Connection" WHERE grid_id = %s',
            (grid_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            raise ValueError(f"No connections found for grid '{grid_id}'.")

        G = nx.Graph()
        for u, v in rows:
            if u and v and u != v:
                G.add_edge(str(u), str(v))

        pos = nx.spring_layout(G, seed=42)
        plt.figure(figsize=(8, 6))
        nx.draw(
            G,
            pos,
            with_labels=True,
            node_color="#2563eb",
            node_size=400,
            font_size=8,
            font_color="white",
            edge_color="#94a3b8",
        )
        plt.axis("off")

        IMG_DIR.mkdir(parents=True, exist_ok=True)
        output_path = IMG_DIR / f"{grid_id}.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        return output_path
    finally:
        conn.close()


def _fetch_table_as_html(table_name: str, grid_id: str) -> str:
    table_sql = _TABLE_MAP.get(table_name)
    if not table_sql:
        return f"<p class='muted'>Unknown table '{html.escape(table_name)}'.</p>"

    conn, _ = db.get_db_connection()
    try:
        q = f"SELECT * FROM {table_sql} WHERE grid_id = %s"
        df = pd.read_sql_query(q, conn, params=(grid_id,))
    except Exception:
        return f"<p class='muted'>Table '{html.escape(table_name)}' not found or empty.</p>"
    finally:
        conn.close()

    if df.empty:
        return (
            f"<p class='muted'>No records found in table '{table_name}' for grid '{grid_id}'.</p>"
        )

    med_visible_cols = [c for c in df.columns if "anonymised" not in c.lower()]
    visible_cols = [c for c in med_visible_cols if "grid_id" not in c.lower()]

    if not visible_cols:
        return (
            f"<h3>{table_name} (0 visible columns)</h3>"
            f"<p class='muted'>All columns are anonymised and were hidden for grid '{grid_id}'.</p>"
        )

    html_table = df[visible_cols].to_html(index=False, classes="data-table", border=0)
    return f"<h3>{table_name} ({len(df)}) rows</h3>{html_table}"

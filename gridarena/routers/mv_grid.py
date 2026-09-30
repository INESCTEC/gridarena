"""MV Grid Router — register, view, connect/disconnect LV grids via transformers."""

import html
import json
import uuid
from pathlib import Path
from typing import List

import networkx as nx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

import gridarena.database as db
import gridarena.schemas as schema
from gridarena.database import NotFoundError

from ._upload_guard import ensure_upload_size_ok

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


# ── Validation helper ──


def _validate_mv_grid(mv_grid: schema.MVGrid) -> List[str]:
    """Validate internal references in an MV grid. Returns list of error strings."""
    errors = []
    node_ids = {n.node_id for n in mv_grid.nodes}

    if mv_grid.cables:
        cable_ids = {c.cable_id for c in mv_grid.cables}
    else:
        cable_ids = set()

    if mv_grid.connections:
        for c in mv_grid.connections:
            if c.from_node_id not in node_ids:
                errors.append(f"Connection '{c.connection_id}': from_node_id '{c.from_node_id}' not found in nodes.")
            if c.to_node_id not in node_ids:
                errors.append(f"Connection '{c.connection_id}': to_node_id '{c.to_node_id}' not found in nodes.")
            if c.cable_id not in cable_ids:
                errors.append(f"Connection '{c.connection_id}': cable_id '{c.cable_id}' not found in cables.")

    cp_ids = set()
    if mv_grid.connection_points:
        for cp in mv_grid.connection_points:
            if cp.node_id not in node_ids:
                errors.append(f"Connection point '{cp.connection_point_id}': node_id '{cp.node_id}' not found in nodes.")
            if cp.connection_point_id in cp_ids:
                errors.append(f"Duplicate connection_point_id '{cp.connection_point_id}'.")
            cp_ids.add(cp.connection_point_id)

    if mv_grid.transformers:
        for t in mv_grid.transformers:
            if t.connection_point_id not in cp_ids:
                errors.append(f"Transformer '{t.transformer_id}': connection_point_id '{t.connection_point_id}' not found.")
            if t.primary_voltage_kv != mv_grid.nominal_voltage_kv:
                errors.append(f"Transformer '{t.transformer_id}': primary_voltage_kv ({t.primary_voltage_kv}) does not match grid nominal ({mv_grid.nominal_voltage_kv}).")

    return errors


def _compute_graph_layout(grid_data: dict) -> dict:
    """Build a NetworkX graph and return node positions + edge list for frontend rendering."""
    G = nx.Graph()
    for n in grid_data.get("nodes", []):
        nid = n.get("node_id") or n.get("NodeId", "")
        G.add_node(nid)

    for c in grid_data.get("connections", []):
        fid = c.get("from_node_id") or c.get("FromNodeId", "")
        tid = c.get("to_node_id") or c.get("ToNodeId", "")
        if fid and tid:
            G.add_edge(fid, tid)

    cp_ids = set()
    for cp in grid_data.get("connection_points", []):
        cpn = cp.get("node_id") or cp.get("NodeId", "")
        cp_ids.add(cpn)

    lv_by_cp = {}
    for t in grid_data.get("transformers", []):
        cpid = t.get("connection_point_id") or t.get("ConnectionPointId", "")
        lv = t.get("lv_grid_id")
        if cpid and lv:
            lv_by_cp.setdefault(cpid, []).append(lv)

    has_coords = all(
        (n.get("coord_lat") or n.get("CoordLat")) is not None
        for n in grid_data.get("nodes", [])
    )

    if has_coords:
        pos = {}
        for n in grid_data.get("nodes", []):
            nid = n.get("node_id") or n.get("NodeId", "")
            lon = n.get("coord_lon") or n.get("CoordLon") or 0.0
            lat = n.get("coord_lat") or n.get("CoordLat") or 0.0
            pos[nid] = (float(lon), float(lat))
    else:
        pos = nx.spring_layout(G, seed=42)
        pos = {k: (float(v[0]), float(v[1])) for k, v in pos.items()}

    cp_point_ids = {}
    for cp in grid_data.get("connection_points", []):
        nid = cp.get("node_id") or cp.get("NodeId", "")
        cpid = cp.get("connection_point_id") or cp.get("ConnectionPointId", "")
        cp_point_ids[nid] = cpid

    graph_nodes = []
    for nid in G.nodes():
        x, y = pos.get(nid, (0, 0))
        ntype = "normal"
        nt = None
        for n in grid_data.get("nodes", []):
            if (n.get("node_id") or n.get("NodeId", "")) == nid:
                nt = n.get("node_type") or n.get("NodeType")
                break
        if nid in cp_ids:
            ntype = "connection_point"
        elif nt == "substation":
            ntype = "substation"

        node_entry = {"id": nid, "x": x, "y": y, "type": ntype}
        if nid in cp_point_ids:
            node_entry["connection_point_id"] = cp_point_ids[nid]
            connected = lv_by_cp.get(cp_point_ids[nid], [])
            if connected:
                node_entry["connected_lv"] = connected
        graph_nodes.append(node_entry)

    graph_edges = [{"from": u, "to": v} for u, v in G.edges()]

    return {"nodes": graph_nodes, "edges": graph_edges}


# ── API Endpoints ──


@router.post("/validate")
async def validate_mv_grid(file: UploadFile = File(...)):
    """Validate an MV grid JSON without saving. Returns parsed grid, graph layout, or errors."""
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        mv_grid = schema.MVGrid(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    errors = _validate_mv_grid(mv_grid)
    if errors:
        return {"valid": False, "errors": errors}

    grid_dump = mv_grid.model_dump()
    graph_data = _compute_graph_layout(grid_dump)

    return {"valid": True, "mv_grid": grid_dump, "graph": graph_data}


@router.post("/")
async def register_mv_grid(file: UploadFile = File(...)):
    """Register a new MV grid from a JSON file."""
    ensure_upload_size_ok(file)
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        mv_grid = schema.MVGrid(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    errors = _validate_mv_grid(mv_grid)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        db.insert_mv_grid_data(mv_grid, conn, cursor)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {"message": f"MV Grid '{mv_grid.mv_grid_id}' registered successfully."}


@router.get("/list")
async def list_mv_grids():
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        return db.get_mv_grid_list(cursor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/data/{mv_grid_id}")
async def get_mv_grid(mv_grid_id: str):
    """Get full MV grid with nodes, connections, connection points, and transformers."""
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        return db.get_mv_grid_detail(mv_grid_id, cursor)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{e}")
    finally:
        conn.close()


@router.delete("/{mv_grid_id}")
async def delete_mv_grid(mv_grid_id: str):
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        db.delete_mv_grid(mv_grid_id, conn, cursor)
    except NotFoundError as e:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"{e}")
    finally:
        conn.close()
    return {"message": f"MV Grid '{mv_grid_id}' and all associated data deleted."}


# ── LV Connection Endpoints ──


@router.get("/lv-grids")
async def list_available_lv_grids():
    """List existing LV grids from the database that can be connected."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        return [{"grid_id": r[0]} for r in cursor.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.post("/{mv_grid_id}/connect/{connection_point_id}")
async def connect_lv_grid(mv_grid_id: str, connection_point_id: str, request: schema.ConnectLVRequest):
    """Connect an LV grid to an MV connection point via a transformer bridge."""
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        transformer_id = request.transformer_id or f"TR-{uuid.uuid4().hex[:8]}"
        db.connect_lv_to_mv(
            mv_grid_id=mv_grid_id,
            connection_point_id=connection_point_id,
            lv_grid_id=request.lv_grid_id,
            transformer_id=transformer_id,
            rated_power_kva=request.rated_power_kva or 400.0,
            primary_voltage_kv=request.primary_voltage_kv or 20.0,
            secondary_voltage_v=request.secondary_voltage_v or 230.0,
            imp_real=request.imp_real,
            imp_imag=request.imp_imag,
            name=request.name,
            conn=conn,
            cursor=cursor,
        )
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"{e}")
    finally:
        conn.close()

    return {"message": f"LV grid '{request.lv_grid_id}' connected to point '{connection_point_id}' via transformer '{transformer_id}'."}


@router.delete("/{mv_grid_id}/disconnect/{connection_point_id}/{lv_grid_id}")
async def disconnect_lv_grid(mv_grid_id: str, connection_point_id: str, lv_grid_id: str):
    """Remove the transformer bridge between an MV connection point and an LV grid."""
    conn, cursor = db.get_db_connection()
    try:
        db.disconnect_lv_from_mv(mv_grid_id, connection_point_id, lv_grid_id, conn, cursor)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"{e}")
    finally:
        conn.close()
    return {"message": f"LV grid '{lv_grid_id}' disconnected from point '{connection_point_id}'."}


@router.get("/{mv_grid_id}/pv/{lv_grid_id}")
async def get_lv_aggregated_pv(mv_grid_id: str, lv_grid_id: str, limit: int = Query(500, ge=1, le=10000)):
    """Get aggregated P/V pairs for a connected LV grid.

    Returns the average power_active and voltage_magnitude per timestamp across all nodes,
    representing the grid-level load profile at the MV/LV boundary.
    """
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            'SELECT 1 FROM "MVTransformer" WHERE mv_grid_id = %s AND lv_grid_id = %s',
            (mv_grid_id, lv_grid_id),
        )
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"LV grid '{lv_grid_id}' is not connected to MV grid '{mv_grid_id}'.")

        pv_pairs = db.get_aggregated_pv(lv_grid_id, cursor, limit=limit)
        if not pv_pairs:
            raise HTTPException(status_code=404, detail=f"No measurement data found for LV grid '{lv_grid_id}'.")

        cursor.execute("SELECT COUNT(DISTINCT node_id) FROM \"Node\" WHERE grid_id = %s", (lv_grid_id,))
        n_nodes = cursor.fetchone()[0]

        return {
            "mv_grid_id": mv_grid_id,
            "lv_grid_id": lv_grid_id,
            "n_nodes": n_nodes,
            "aggregation": "avg_per_timestamp_across_all_nodes",
            "count": len(pv_pairs),
            "pv_pairs": pv_pairs,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


# ── UI Endpoints ──


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def mv_grid_ui(request: Request):
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)

        cursor.execute(
            """
            SELECT g.mv_grid_id, g.name, g.nominal_voltage_kv, g.region,
                   COALESCE(n.cnt, 0) AS n_nodes,
                   COALESCE(c.cnt, 0) AS n_connections,
                   COALESCE(cp.cnt, 0) AS n_cps,
                   COALESCE(t.cnt, 0) AS n_connected
            FROM "MVGrid" g
            LEFT JOIN (SELECT mv_grid_id, COUNT(*) AS cnt FROM "MVNode" GROUP BY mv_grid_id) n
                ON n.mv_grid_id = g.mv_grid_id
            LEFT JOIN (SELECT mv_grid_id, COUNT(*) AS cnt FROM "MVConnection" GROUP BY mv_grid_id) c
                ON c.mv_grid_id = g.mv_grid_id
            LEFT JOIN (SELECT mv_grid_id, COUNT(*) AS cnt FROM "MVConnectionPoint" GROUP BY mv_grid_id) cp
                ON cp.mv_grid_id = g.mv_grid_id
            LEFT JOIN (SELECT mv_grid_id, COUNT(*) AS cnt FROM "MVTransformer"
                       WHERE lv_grid_id IS NOT NULL GROUP BY mv_grid_id) t
                ON t.mv_grid_id = g.mv_grid_id
            ORDER BY g.mv_grid_id
            """
        )
        mv_grids = [{
            "mv_grid_id": r[0], "name": r[1], "nominal_voltage_kv": r[2], "region": r[3],
            "n_nodes": r[4], "n_connections": r[5], "n_cps": r[6], "n_connected": r[7],
        } for r in cursor.fetchall()]

        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        lv_grids = [r[0] for r in cursor.fetchall()]
    except Exception:
        mv_grids = []
        lv_grids = []
    finally:
        conn.close()

    total_nodes = sum(g["n_nodes"] for g in mv_grids)
    total_cps = sum(g["n_cps"] for g in mv_grids)
    total_connected = sum(g["n_connected"] for g in mv_grids)

    from gridarena.pf_datagen.run_manager import pf_datagen_registry
    pf_datagen_runs = [r.model_dump() for r in pf_datagen_registry.list_runs()]

    return templates.TemplateResponse("mv_grid/list.html", {
        "request": request,
        "title": "MV Grids",
        "active": "mv_grid",
        "mv_grids": mv_grids,
        "lv_grids": lv_grids,
        "total_nodes": total_nodes,
        "total_cps": total_cps,
        "total_connected": total_connected,
        "pf_datagen_runs": pf_datagen_runs,
    })


@router.get("/ui/{mv_grid_id}", response_class=HTMLResponse, include_in_schema=False)
async def mv_grid_detail_ui(request: Request, mv_grid_id: str):
    conn, cursor = db.get_db_connection()
    try:
        db.create_mv_database(conn, cursor)
        grid = db.get_mv_grid_detail(mv_grid_id, cursor)
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        lv_grids = [r[0] for r in cursor.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()

    graph_data = _compute_graph_layout(grid)

    return templates.TemplateResponse("mv_grid/detail.html", {
        "request": request,
        "title": f"MV Grid: {mv_grid_id}",
        "active": "mv_grid",
        "grid": grid,
        "lv_grids": lv_grids,
        "graph_data": graph_data,
    })

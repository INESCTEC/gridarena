"""Offline Scenario Router — clone digital twins, modify grids, run scenario PF."""

import json
import logging
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.database as db
from gridarena.schemas.offline_scenario import ConnectionChange, CloneRequest, PowerLimitsUpdate
from gridarena.database.create_offline_scenario_database import create_offline_scenario_tables
from gridarena.database.offline_scenario_crud import (
    delete_offline_scenario,
    get_offline_scenario,
    get_scenario_violations,
    get_scenario_voltage_timeseries,
    insert_offline_scenario,
    list_offline_scenarios,
    list_scenario_results,
    update_scenario_changes,
    update_scenario_power_limits,
)
from gridarena.database.digital_twin_crud import (
    get_digital_twin,
    list_digital_twin_results,
)
from gridarena.digital_twin.scenario_runner import scenario_runner

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _ensure_tables():
    conn, cursor = db.get_db_connection()
    try:
        create_offline_scenario_tables(cursor)
        conn.commit()
    except Exception:
        logger.error("Failed to ensure offline scenario tables exist", exc_info=True)
        conn.rollback()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
#  UI (before catch-all)
# ══════════════════════════════════════════════════════════════


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def scenario_list_page(request: Request):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        scenarios = list_offline_scenarios(cursor)
    except Exception:
        scenarios = []
    finally:
        conn.close()

    return templates.TemplateResponse("digital_twin/scenarios.html", {
        "request": request,
        "title": "Offline Scenarios",
        "active": "digital_twin_scenarios",
        "scenarios": scenarios,
    })


@router.get("/ui/{scenario_id}", response_class=HTMLResponse, include_in_schema=False)
async def scenario_detail_page(request: Request, scenario_id: str):
    import networkx as nx

    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        results = list_scenario_results(scenario_id, cursor, limit=500)
    finally:
        conn.close()

    snapshot = sc.get("grid_snapshot", {})
    nodes = snapshot.get("nodes", [])
    connections = snapshot.get("connections", [])

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["node_id"])
    for c in connections:
        G.add_edge(c.get("from_node_id", ""), c.get("to_node_id", ""))

    pos = nx.spring_layout(G, seed=42)
    pos = {k: (float(v[0]), float(v[1])) for k, v in pos.items()}
    graph_nodes = [{"id": nid, "x": pos.get(nid, (0, 0))[0], "y": pos.get(nid, (0, 0))[1],
                    "type": "pt" if nid == "PT" else "normal"} for nid in G.nodes()]
    graph_edges = [{"from": u, "to": v} for u, v in G.edges()]

    dt = None
    conn2, cursor2 = db.get_db_connection()
    try:
        dt = get_digital_twin(sc["source_dt_id"], cursor2)
    except Exception:
        logger.warning("Failed to load source digital twin for scenario %s", scenario_id, exc_info=True)
    finally:
        conn2.close()

    return templates.TemplateResponse("digital_twin/scenario_detail.html", {
        "request": request,
        "title": f"Scenario: {sc['name'] or scenario_id}",
        "active": "digital_twin_scenarios",
        "sc": sc,
        "dt": dt,
        "results": results,
        "graph_data": {"nodes": graph_nodes, "edges": graph_edges},
    })


# ══════════════════════════════════════════════════════════════
#  Fixed-path endpoints
# ══════════════════════════════════════════════════════════════


@router.get("/")
async def list_scenarios(source_dt_id: str = None):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        return list_offline_scenarios(cursor, source_dt_id=source_dt_id)
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
#  Parameterised endpoints
# ══════════════════════════════════════════════════════════════


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return sc
    finally:
        conn.close()


@router.delete("/{scenario_id}")
async def remove_scenario(scenario_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        delete_offline_scenario(scenario_id, conn, cursor)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
    return {"message": f"Scenario '{scenario_id}' deleted."}


@router.post("/{scenario_id}/changes/connections")
async def set_connection_changes(scenario_id: str, changes: List[ConnectionChange]):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        if sc["simulation_status"] == "running":
            raise HTTPException(status_code=400, detail="Cannot modify while simulation is running.")

        snapshot = sc.get("grid_snapshot", {})
        node_ids = {n["node_id"] for n in snapshot.get("nodes", [])}
        cable_ids = {c["cable_id"] for c in snapshot.get("cables", [])}
        conn_ids = {c["connection_id"] for c in snapshot.get("connections", [])}

        errors = []
        for c in changes:
            if c.action == "add":
                if not c.from_node_id or c.from_node_id not in node_ids:
                    errors.append(f"Add '{c.connection_id}': from_node_id '{c.from_node_id}' not in grid.")
                if not c.to_node_id or c.to_node_id not in node_ids:
                    errors.append(f"Add '{c.connection_id}': to_node_id '{c.to_node_id}' not in grid.")
                if c.cable_id and c.cable_id not in cable_ids:
                    errors.append(f"Add '{c.connection_id}': cable_id '{c.cable_id}' not in grid.")
            elif c.action in ("remove", "disable", "enable", "update"):
                if c.connection_id not in conn_ids:
                    errors.append(f"{c.action.capitalize()} '{c.connection_id}': connection not in grid.")
            else:
                errors.append(f"Unknown action '{c.action}' for '{c.connection_id}'.")

        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

        update_scenario_changes(scenario_id, [c.model_dump() for c in changes], conn, cursor)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {"message": f"{len(changes)} connection change(s) applied."}


@router.post("/{scenario_id}/changes/power-limits")
async def set_power_limits(scenario_id: str, body: PowerLimitsUpdate):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        if sc["simulation_status"] == "running":
            raise HTTPException(status_code=400, detail="Cannot modify while simulation is running.")

        node_ids = {n["node_id"] for n in sc.get("grid_snapshot", {}).get("nodes", [])}
        errors = []
        for nid, limit in body.power_limits.items():
            if nid not in node_ids:
                errors.append(f"Node '{nid}' not in grid.")
            if not isinstance(limit, (int, float)) or limit < 0:
                errors.append(f"Node '{nid}': power limit must be a non-negative number.")
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

        update_scenario_power_limits(scenario_id, body.power_limits, conn, cursor)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {"message": f"Power limits set for {len(body.power_limits)} node(s)."}


@router.post("/{scenario_id}/run-powerflow-timeseries")
async def run_scenario_pf(scenario_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        if sc["simulation_status"] == "running":
            raise HTTPException(status_code=400, detail="Simulation already running.")
    finally:
        conn.close()

    scenario_runner.start(scenario_id)
    return {"message": f"Simulation started for scenario '{scenario_id}'.", "status": "running"}


@router.get("/{scenario_id}/results")
async def get_results(scenario_id: str, limit: int = Query(500, ge=1, le=5000)):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return list_scenario_results(scenario_id, cursor, limit=limit)
    finally:
        conn.close()


@router.get("/{scenario_id}/voltage-timeseries")
async def get_voltage_ts(scenario_id: str, node_id: str = None):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return get_scenario_voltage_timeseries(scenario_id, cursor, node_id=node_id)
    finally:
        conn.close()


@router.get("/{scenario_id}/violations")
async def get_violations(scenario_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        sc = get_offline_scenario(scenario_id, cursor)
        if sc is None:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        pf_config = sc.get("powerflow_config", {})
        v_ref = pf_config.get("voltage_ref", 230.0)
        return get_scenario_violations(scenario_id, cursor, voltage_ref=v_ref)
    finally:
        conn.close()

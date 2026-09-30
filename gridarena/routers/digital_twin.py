"""Digital Twin Router — create, manage, run and monitor digital twins."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.database as db
from gridarena.database.create_digital_twin_database import create_digital_twin_tables
from gridarena.database.digital_twin_crud import (
    delete_digital_twin,
    get_digital_twin,
    get_digital_twin_metrics,
    get_latest_digital_twin_result,
    insert_digital_twin,
    insert_digital_twin_event,
    list_digital_twin_events,
    list_digital_twin_results,
    list_digital_twins,
    update_digital_twin,
    update_digital_twin_status,
)
from gridarena.digital_twin import broker, connector, field_mapper
from gridarena.digital_twin.runner import dt_runner
from gridarena.digital_twin.schemas import (
    DigitalTwinCreate,
    DigitalTwinStatus,
    DigitalTwinUpdate,
    LatestStateResponse,
    StreamedMeasurementBatch,
    TestSourceResponse,
    ValidateFieldMappingRequest,
    ValidateFieldMappingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _ensure_tables():
    conn, cursor = db.get_db_connection()
    try:
        create_digital_twin_tables(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
#  UI  (must be registered before /{digital_twin_id} catch-all)
# ══════════════════════════════════════════════════════════════


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def digital_twin_list_page(request: Request):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        twins = list_digital_twins(cursor)
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        grids = [r[0] for r in cursor.fetchall()]
    except Exception:
        twins = []
        grids = []
    finally:
        conn.close()

    running = sum(1 for t in twins if t["status"] == "running")
    stopped = sum(1 for t in twins if t["status"] in ("created", "stopped"))
    return templates.TemplateResponse("digital_twin/list.html", {
        "request": request,
        "title": "Digital Twins",
        "active": "digital_twin",
        "twins": twins,
        "grids": grids,
        "running_count": running,
        "stopped_count": stopped,
    })


@router.get("/ui/new", response_class=HTMLResponse, include_in_schema=False)
async def digital_twin_create_page(request: Request):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id ASC")
        grids = [r[0] for r in cursor.fetchall()]
    except Exception:
        grids = []
    finally:
        conn.close()

    return templates.TemplateResponse("digital_twin/create.html", {
        "request": request,
        "title": "New Digital Twin",
        "active": "digital_twin_create",
        "grids": grids,
    })


@router.get("/ui/{digital_twin_id}", response_class=HTMLResponse, include_in_schema=False)
async def digital_twin_detail_page(request: Request, digital_twin_id: str):
    import logging
    import networkx as nx

    logger = logging.getLogger(__name__)

    _ensure_tables()

    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        events = list_digital_twin_events(digital_twin_id, cursor, limit=20)
        results = list_digital_twin_results(digital_twin_id, cursor, limit=20)
    finally:
        conn.close()

    grid_id = dt["grid_id"]
    nodes = []
    connections = []
    conn2, cursor2 = db.get_db_connection()
    try:
        cursor2.execute(
            'SELECT "NodeId", "CoordLat", "CoordLon" FROM "Node" WHERE grid_id = %s',
            (grid_id,),
        )
        nodes = [{"node_id": r[0], "coord_lat": r[1], "coord_lon": r[2]} for r in cursor2.fetchall()]

        cursor2.execute(
            'SELECT "FromNodeId", "ToNodeId" FROM "Connection" WHERE grid_id = %s',
            (grid_id,),
        )
        connections = [{"from_node": r[0], "to_node": r[1]} for r in cursor2.fetchall()]
        logger.info("Grid %s: loaded %d nodes, %d connections", grid_id, len(nodes), len(connections))
    except Exception as e:
        logger.error("Failed to load grid graph for %s: %s", grid_id, e)
    finally:
        conn2.close()

    graph_data = {"nodes": [], "edges": []}
    if nodes:
        G = nx.Graph()
        for n in nodes:
            G.add_node(n["node_id"])
        for c in connections:
            if c["from_node"] and c["to_node"]:
                G.add_edge(c["from_node"], c["to_node"])

        pos = nx.spring_layout(G, seed=42)
        pos = {k: (float(v[0]), float(v[1])) for k, v in pos.items()}

        graph_nodes = []
        for nid in G.nodes():
            x, y = pos.get(nid, (0, 0))
            graph_nodes.append({"id": nid, "x": x, "y": y, "type": "pt" if nid == "PT" else "normal"})
        graph_edges = [{"from": u, "to": v} for u, v in G.edges()]
        graph_data = {"nodes": graph_nodes, "edges": graph_edges}

    return templates.TemplateResponse("digital_twin/detail.html", {
        "request": request,
        "title": f"Digital Twin: {dt['name'] or digital_twin_id}",
        "active": "digital_twin",
        "dt": dt,
        "events": events,
        "results": results,
        "graph_data": graph_data,
    })


# ══════════════════════════════════════════════════════════════
#  Fixed-path endpoints (before catch-all)
# ══════════════════════════════════════════════════════════════


@router.post("/")
async def create_digital_twin(request: DigitalTwinCreate):
    conn, cursor = db.get_db_connection()
    try:
        create_digital_twin_tables(cursor)
        conn.commit()

        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (request.grid_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Grid '{request.grid_id}' not found.")

        dt_id = str(uuid.uuid4())[:12]
        topic = request.broker_topic or broker.topic_for_digital_twin(dt_id)

        dt_data = {
            "digital_twin_id": dt_id,
            "grid_id": request.grid_id,
            "name": request.name,
            "description": request.description,
            "status": "created",
            "update_interval_seconds": request.update_interval_seconds,
            "broker_type": request.broker_type,
            "broker_topic": topic,
            "source_config": request.source_config.model_dump(),
            "field_mapping": request.field_mapping.model_dump() if request.field_mapping else None,
            "node_assignments": [na.model_dump() for na in request.node_assignments] if request.node_assignments else None,
            "powerflow_config": request.powerflow_config.model_dump(),
        }
        insert_digital_twin(dt_data, conn, cursor)
        insert_digital_twin_event(dt_id, "created", "Digital twin created.", conn, cursor)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("Failed to create digital twin %s: %s", dt_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error while creating the digital twin.")
    finally:
        conn.close()

    return {"digital_twin_id": dt_id, "message": f"Digital twin '{dt_id}' created."}


@router.get("/")
async def list_all_digital_twins():
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        return list_digital_twins(cursor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/diagnose/{digital_twin_id}")
async def diagnose(digital_twin_id: str):
    """Full diagnostic of stored data for a digital twin."""
    _ensure_tables()
    from gridarena.database.digital_twin_crud import diagnose_digital_twin
    return diagnose_digital_twin(digital_twin_id)


@router.post("/validate-field-mapping")
async def validate_field_mapping(body: ValidateFieldMappingRequest):
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (body.grid_id,))
        if cursor.fetchone() is None:
            return ValidateFieldMappingResponse(
                success=False, errors=[f"Grid '{body.grid_id}' not found."],
            )

        cursor.execute('SELECT DISTINCT "NodeId" FROM "Node" WHERE grid_id = %s', (body.grid_id,))
        grid_nodes = {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()

    batch, errors, warnings = field_mapper.map_payload(
        body.source_sample, body.field_mapping, body.grid_id,
    )

    resp = ValidateFieldMappingResponse(
        success=batch is not None and len(errors) == 0,
        mapped_payload=batch,
        errors=errors,
        warnings=warnings,
    )

    if batch is not None:
        invalid_nodes, invalid_phases, _ = field_mapper.validate_against_grid(batch, grid_nodes)
        resp.invalid_nodes = invalid_nodes
        resp.invalid_phases = invalid_phases
        if invalid_nodes:
            resp.warnings.append(f"{len(invalid_nodes)} nodes not found in grid.")

    return resp


@router.get("/grid-graph/{grid_id}")
async def get_grid_graph_for_wizard(grid_id: str):
    """Return grid nodes, connections and graph layout for the creation wizard."""
    import networkx as nx

    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (grid_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Grid '{grid_id}' not found.")

        cursor.execute(
            'SELECT "NodeId", "CoordLat", "CoordLon" FROM "Node" WHERE grid_id = %s',
            (grid_id,),
        )
        nodes = [{"node_id": r[0], "coord_lat": r[1], "coord_lon": r[2]} for r in cursor.fetchall()]

        cursor.execute(
            'SELECT "ConnectionId", "FromNodeId", "ToNodeId", "CableId", "Length" '
            'FROM "Connection" WHERE grid_id = %s',
            (grid_id,),
        )
        connections = [
            {"connection_id": r[0], "from_node_id": r[1], "to_node_id": r[2], "cable_id": r[3], "length": r[4]}
            for r in cursor.fetchall()
        ]
    finally:
        conn.close()

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["node_id"])
    for c in connections:
        if c["from_node_id"] and c["to_node_id"]:
            G.add_edge(c["from_node_id"], c["to_node_id"])

    has_coords = all(n["coord_lat"] is not None and n["coord_lon"] is not None for n in nodes)
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

    graph_edges = [{"source": u, "target": v} for u, v in G.edges()]

    return {
        "grid_id": grid_id,
        "nodes": nodes,
        "connections": connections,
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
    }


# ══════════════════════════════════════════════════════════════
#  Parameterised endpoints: /{digital_twin_id}/...
# ══════════════════════════════════════════════════════════════


@router.get("/{digital_twin_id}")
async def get_digital_twin_detail(digital_twin_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        return dt
    finally:
        conn.close()


@router.patch("/{digital_twin_id}")
async def patch_digital_twin(digital_twin_id: str, body: DigitalTwinUpdate):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        if dt["status"] == "running":
            raise HTTPException(status_code=400, detail="Cannot update a running digital twin. Stop it first.")

        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        if body.update_interval_seconds is not None:
            updates["update_interval_seconds"] = body.update_interval_seconds
        if body.source_config is not None:
            updates["source_config"] = body.source_config.model_dump()
        if body.field_mapping is not None:
            updates["field_mapping"] = body.field_mapping.model_dump()
        if body.powerflow_config is not None:
            updates["powerflow_config"] = body.powerflow_config.model_dump()

        if updates:
            update_digital_twin(digital_twin_id, updates, conn, cursor)

        return {"message": "Digital twin updated."}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("Failed to update digital twin %s: %s", digital_twin_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error while updating the digital twin.")
    finally:
        conn.close()


@router.delete("/{digital_twin_id}")
async def remove_digital_twin(digital_twin_id: str):
    _ensure_tables()
    if dt_runner.is_running(digital_twin_id):
        dt_runner.stop(digital_twin_id)

    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        delete_digital_twin(digital_twin_id, conn, cursor)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("Failed to delete digital twin %s: %s", digital_twin_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error while deleting the digital twin.")
    finally:
        conn.close()

    try:
        broker.delete_stream(digital_twin_id)
    except Exception:
        pass
    return {"message": f"Digital twin '{digital_twin_id}' deleted."}


# ── Lifecycle ──


@router.post("/{digital_twin_id}/start")
async def start_digital_twin(digital_twin_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        if dt["status"] == "running":
            raise HTTPException(status_code=400, detail="Digital twin is already running.")
    finally:
        conn.close()

    dt_runner.start(digital_twin_id)
    return {"message": f"Digital twin '{digital_twin_id}' started."}


@router.post("/{digital_twin_id}/stop")
async def stop_digital_twin(digital_twin_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
    finally:
        conn.close()

    dt_runner.stop(digital_twin_id)
    return {"message": f"Digital twin '{digital_twin_id}' stopped."}


@router.post("/{digital_twin_id}/clone-offline")
async def clone_as_offline_scenario(digital_twin_id: str, body: dict = None):
    """Clone a digital twin into an offline scenario for what-if analysis."""
    from pydantic import BaseModel
    import uuid as _uuid

    _ensure_tables()
    from gridarena.database.create_offline_scenario_database import create_offline_scenario_tables
    from gridarena.database.offline_scenario_crud import insert_offline_scenario

    conn, cursor = db.get_db_connection()
    try:
        create_offline_scenario_tables(cursor)
        conn.commit()

        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")

        grid_id = dt["grid_id"]

        cursor.execute(
            'SELECT "NodeId", "CoordLat", "CoordLon" FROM "Node" WHERE grid_id = %s',
            (grid_id,),
        )
        nodes = [{"node_id": r[0], "coord_lat": r[1], "coord_lon": r[2]} for r in cursor.fetchall()]

        cursor.execute(
            'SELECT "ConnectionId", "FromNodeId", "ToNodeId", "CableId", "Length" '
            'FROM "Connection" WHERE grid_id = %s',
            (grid_id,),
        )
        connections = [
            {"connection_id": r[0], "from_node_id": r[1], "to_node_id": r[2], "cable_id": r[3], "length": r[4]}
            for r in cursor.fetchall()
        ]

        cursor.execute(
            'SELECT "CableId", "RImpReal", "RImpImag", "SImpReal", "SImpImag", '
            '"TImpReal", "TImpImag", "RNomCurr", "SNomCurr", "TNomCurr" '
            'FROM "Cable" WHERE grid_id = %s',
            (grid_id,),
        )
        cables = [
            {"cable_id": r[0], "r_imp_real": r[1], "r_imp_imag": r[2],
             "s_imp_real": r[3], "s_imp_imag": r[4], "t_imp_real": r[5], "t_imp_imag": r[6],
             "r_nom_curr": r[7], "s_nom_curr": r[8], "t_nom_curr": r[9]}
            for r in cursor.fetchall()
        ]

        dt_results = list_digital_twin_results(digital_twin_id, cursor, limit=10000)
        total_ts = len([r for r in dt_results if r.get("convergence_status") == "converged"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to gather clone data for digital twin %s: %s", digital_twin_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clone digital twin. See server logs for details.")
    finally:
        conn.close()

    scenario_id = str(_uuid.uuid4())[:12]
    name = ""
    description = ""
    if body and isinstance(body, dict):
        name = body.get("name", "")
        description = body.get("description", "")
    if not name:
        name = f"Scenario from {dt.get('name') or digital_twin_id}"

    sc_data = {
        "scenario_id": scenario_id,
        "source_dt_id": digital_twin_id,
        "grid_id": grid_id,
        "name": name,
        "description": description,
        "grid_snapshot": {"nodes": nodes, "connections": connections, "cables": cables},
        "connection_changes": [],
        "power_limits": {},
        "powerflow_config": dt.get("powerflow_config") or {"phase": "R", "voltage_ref": 230.0},
        "total_timestamps": total_ts,
    }

    conn, cursor = db.get_db_connection()
    try:
        insert_offline_scenario(sc_data, conn, cursor)
    except Exception as e:
        conn.rollback()
        logger.error("Failed to save cloned scenario %s from digital twin %s: %s", scenario_id, digital_twin_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database error while cloning the digital twin.")
    finally:
        conn.close()

    return {
        "scenario_id": scenario_id,
        "message": f"Offline scenario '{scenario_id}' cloned from digital twin '{digital_twin_id}' with {total_ts} timestamps.",
    }


@router.post("/{digital_twin_id}/tick")
async def tick_digital_twin(digital_twin_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
    finally:
        conn.close()

    try:
        metrics = await dt_runner.tick(digital_twin_id)
        return {"message": "Tick completed.", "metrics": metrics}
    except Exception as e:
        logger.error("Tick failed for digital twin %s: %s", digital_twin_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Tick failed. See server logs for details.")


# ── Connector / Mapping ──


@router.post("/{digital_twin_id}/test-source")
async def test_source(digital_twin_id: str):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
    finally:
        conn.close()

    from gridarena.digital_twin.schemas import SourceConfig
    config = SourceConfig(**dt["source_config"])
    success, payload, error, status_code = await connector.fetch_source(config)

    return TestSourceResponse(
        success=success,
        status_code=status_code,
        raw_payload=payload,
        error=error,
    )


@router.post("/{digital_twin_id}/probe")
async def probe_source(digital_twin_id: str, body: dict = None):
    """Call the source URL with custom query params and return the raw response."""
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
    finally:
        conn.close()

    from gridarena.digital_twin.schemas import SourceConfig
    base = SourceConfig(**dt["source_config"])

    extra_params = {}
    if body and isinstance(body, dict):
        extra_params = body.get("query_params", {})

    probe_config = SourceConfig(
        source_type=base.source_type,
        url=base.url,
        method=base.method,
        headers=base.headers,
        query_params={**base.query_params, **extra_params},
        auth_type=base.auth_type,
        secret_ref=base.secret_ref,
        secret_header=base.secret_header,
        timeout_seconds=base.timeout_seconds,
        retry_count=1,
    )

    success, payload, error, status_code = await connector.fetch_source(probe_config)

    return {
        "success": success,
        "status_code": status_code,
        "url": base.url,
        "query_params": probe_config.query_params,
        "raw_payload": payload,
        "error": error,
    }


@router.post("/{digital_twin_id}/publish-sample")
async def publish_sample(digital_twin_id: str):
    """Fetch from source, map, validate, and publish one sample to the broker."""
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
    finally:
        conn.close()

    from gridarena.digital_twin.schemas import FieldMapping, SourceConfig
    config = SourceConfig(**dt["source_config"])
    mapping = FieldMapping(**dt["field_mapping"])
    grid_id = dt["grid_id"]

    success, raw_data, error_msg, _ = await connector.fetch_source(config)
    if not success or raw_data is None:
        raise HTTPException(status_code=502, detail=f"Source fetch failed: {error_msg}")

    batch, errors, warnings = field_mapper.map_payload(raw_data, mapping, grid_id)
    if batch is None:
        raise HTTPException(status_code=422, detail={"mapping_errors": errors})

    batch_dict = batch.model_dump()

    msg_id = None
    try:
        if broker.is_available():
            msg_id = broker.publish_measurement(
                digital_twin_id, batch_dict,
                topic=dt["broker_topic"] or None,
            )
    except Exception:
        pass

    from gridarena.database.digital_twin_crud import update_digital_twin_last_run
    conn, cursor = db.get_db_connection()
    try:
        update_digital_twin_last_run(digital_twin_id, conn, cursor, latest_batch=batch_dict)
    finally:
        conn.close()

    return {
        "message": "Sample published." if msg_id else "Sample mapped and stored successfully.",
        "broker_message_id": msg_id,
        "measurements_count": len(batch.measurements),
        "mapping_warnings": warnings,
        "mapping_errors": errors,
    }


# ── Results / Metrics / Events ──


@router.get("/{digital_twin_id}/latest-state")
async def get_latest_state(digital_twin_id: str):
    _ensure_tables()
    from gridarena.database.digital_twin_crud import get_latest_batch

    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        latest = get_latest_digital_twin_result(digital_twin_id, cursor)
        latest_batch_raw = get_latest_batch(digital_twin_id, cursor)
    finally:
        conn.close()

    batch = None
    if latest_batch_raw:
        try:
            batch = StreamedMeasurementBatch(**latest_batch_raw)
        except Exception:
            pass

    return {
        "digital_twin_id": digital_twin_id,
        "grid_id": dt["grid_id"],
        "status": dt["status"],
        "last_run_at": dt["last_run_at"],
        "latest_measurements": batch.model_dump() if batch else None,
        "latest_result": latest,
    }


@router.get("/{digital_twin_id}/node-history/{node_id}")
async def get_node_history(digital_twin_id: str, node_id: str, limit: int = Query(500, ge=1, le=5000)):
    """Return power and voltage time-series for a specific node across all results."""
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        results = list_digital_twin_results(digital_twin_id, cursor, limit=limit)
    finally:
        conn.close()

    history = []
    for r in reversed(results):
        if r["convergence_status"] != "converged" or not r.get("details"):
            continue
        details = r["details"]
        if isinstance(details, str):
            try:
                details = __import__("json").loads(details)
            except Exception:
                continue
        if not isinstance(details, dict) or node_id not in details:
            continue
        nd = details[node_id]
        history.append({
            "timestamp": r["timestamp"],
            "simulated_voltage": nd.get("simulated_voltage"),
            "true_voltage": nd.get("true_voltage"),
            "power_active": nd.get("power_active"),
            "power_reactive": nd.get("power_reactive"),
        })

    return {"node_id": node_id, "digital_twin_id": digital_twin_id, "points": history}


@router.get("/{digital_twin_id}/results")
async def get_results(digital_twin_id: str, limit: int = Query(50, ge=1, le=1000)):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        return list_digital_twin_results(digital_twin_id, cursor, limit=limit)
    finally:
        conn.close()


@router.get("/{digital_twin_id}/metrics")
async def get_metrics(digital_twin_id: str, limit: int = Query(100, ge=1, le=1000)):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        return get_digital_twin_metrics(digital_twin_id, cursor, limit=limit)
    finally:
        conn.close()


@router.get("/{digital_twin_id}/events")
async def get_events(digital_twin_id: str, limit: int = Query(50, ge=1, le=500)):
    _ensure_tables()
    conn, cursor = db.get_db_connection()
    try:
        dt = get_digital_twin(digital_twin_id, cursor)
        if dt is None:
            raise HTTPException(status_code=404, detail="Digital twin not found.")
        return list_digital_twin_events(digital_twin_id, cursor, limit=limit)
    finally:
        conn.close()

"""Offline scenario runner: run power flow across inherited time-series with a modified grid."""

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional

import numpy as np

import gridarena.database as db
from gridarena.database.create_offline_scenario_database import create_offline_scenario_tables
from gridarena.database.offline_scenario_crud import (
    get_offline_scenario,
    insert_scenario_result,
    list_offline_scenarios,
    update_scenario_simulation_status,
)
from gridarena.database.digital_twin_crud import list_digital_twin_results
from gridarena.powerflow.powerflow_algorithm import full_pf

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """Manages asyncio tasks for running offline scenario simulations."""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}

    def start(self, scenario_id: str):
        if scenario_id in self._tasks and not self._tasks[scenario_id].done():
            return
        task = asyncio.create_task(self._run(scenario_id))
        self._tasks[scenario_id] = task

    def is_running(self, scenario_id: str) -> bool:
        task = self._tasks.get(scenario_id)
        return task is not None and not task.done()

    def shutdown(self):
        for sid in list(self._tasks.keys()):
            task = self._tasks.get(sid)
            if task and not task.done():
                task.cancel()
        self._tasks.clear()

    async def _run(self, scenario_id: str):
        conn, cursor = db.get_db_connection()
        try:
            create_offline_scenario_tables(cursor)
            conn.commit()
            sc = get_offline_scenario(scenario_id, cursor)
        finally:
            conn.close()

        if sc is None:
            logger.error("Scenario %s not found", scenario_id)
            return

        conn, cursor = db.get_db_connection()
        try:
            update_scenario_simulation_status(scenario_id, "running", conn, cursor)
        finally:
            conn.close()

        try:
            await _execute_scenario(scenario_id, sc)
        except asyncio.CancelledError:
            conn, cursor = db.get_db_connection()
            try:
                update_scenario_simulation_status(scenario_id, "failed", conn, cursor, error="Cancelled")
            finally:
                conn.close()
        except Exception as e:
            logger.error("Scenario %s failed: %s", scenario_id, e, exc_info=True)
            conn, cursor = db.get_db_connection()
            try:
                update_scenario_simulation_status(scenario_id, "failed", conn, cursor, error=str(e))
            finally:
                conn.close()


async def _execute_scenario(scenario_id: str, sc: dict):
    grid_snapshot = sc["grid_snapshot"]
    connection_changes = sc.get("connection_changes") or []
    power_limits = sc.get("power_limits") or {}
    pf_config = sc.get("powerflow_config") or {}
    phase = pf_config.get("phase", "R")
    voltage_ref = pf_config.get("voltage_ref", 230.0)
    source_dt_id = sc["source_dt_id"]

    nodes_list = grid_snapshot.get("nodes", [])
    connections_list = grid_snapshot.get("connections", [])
    cables_map = {c["cable_id"]: c for c in grid_snapshot.get("cables", [])}

    modified_connections = _apply_connection_changes(connections_list, connection_changes)

    node_ids = [n["node_id"] for n in nodes_list]
    if "PT" in node_ids:
        node_ids.remove("PT")
        node_ids.insert(0, "PT")
    node_id_to_index = {nid: idx for idx, nid in enumerate(node_ids)}
    n_nodes = len(node_ids)

    pf_connections = []
    pf_conn_data = []
    for c in modified_connections:
        if c.get("disabled"):
            continue
        fi = node_id_to_index.get(c["from_node_id"])
        ti = node_id_to_index.get(c["to_node_id"])
        if fi is None or ti is None:
            continue
        pf_connections.append([fi, ti])
        pf_conn_data.append((c["cable_id"], c.get("length", 1.0)))

    admittances = _compute_admittances(cables_map, pf_conn_data)

    conn, cursor = db.get_db_connection()
    try:
        dt_results = list_digital_twin_results(source_dt_id, cursor, limit=10000)
    finally:
        conn.close()

    timestamps = [r for r in dt_results if r.get("convergence_status") == "converged" and r.get("details")]
    timestamps.reverse()

    completed = 0
    failed = 0

    for i, dt_result in enumerate(timestamps):
        details = dt_result["details"]
        if isinstance(details, str):
            try:
                import json
                details = json.loads(details)
            except Exception:
                failed += 1
                continue
        if not isinstance(details, dict):
            failed += 1
            continue

        ts = dt_result["timestamp"]
        S_array = [0 + 0j] * n_nodes

        for nid, nd in details.items():
            idx = node_id_to_index.get(nid)
            if idx is None:
                continue
            p = nd.get("power_active", 0.0) or 0.0
            q = nd.get("power_reactive", 0.0) or 0.0

            if nid in power_limits:
                limit = float(power_limits[nid])
                if abs(p) > abs(limit):
                    p = math.copysign(limit, p)

            S_array[idx] = complex(p, q)

        reference_voltage = voltage_ref + 0j

        result = {"timestamp": ts}
        t0 = time.time()
        try:
            volt_values = full_pf(
                np.array(S_array),
                pf_connections,
                np.array(admittances),
                reference_voltage,
            )
            node_voltages = {}
            for nid, idx in node_id_to_index.items():
                node_voltages[nid] = {
                    "simulated_voltage": round(abs(volt_values[idx]), 4),
                    "power_active": S_array[idx].real,
                    "power_reactive": S_array[idx].imag,
                }

            result["convergence_status"] = "converged"
            result["node_voltages"] = node_voltages
            completed += 1
        except Exception as e:
            result["convergence_status"] = "failed"
            result["error"] = str(e)
            failed += 1

        result["execution_time_ms"] = round((time.time() - t0) * 1000, 2)

        conn, cursor = db.get_db_connection()
        try:
            insert_scenario_result(scenario_id, result, conn, cursor)
        finally:
            conn.close()

        if (i + 1) % 50 == 0:
            conn, cursor = db.get_db_connection()
            try:
                update_scenario_simulation_status(
                    scenario_id, "running", conn, cursor,
                    completed=completed, failed=failed,
                )
            finally:
                conn.close()
            await asyncio.sleep(0)

    final_status = "completed"
    if failed > 0 and completed > 0:
        final_status = "partially_completed"
    elif failed > 0 and completed == 0:
        final_status = "failed"

    conn, cursor = db.get_db_connection()
    try:
        update_scenario_simulation_status(
            scenario_id, final_status, conn, cursor,
            completed=completed, failed=failed,
        )
    finally:
        conn.close()

    logger.info("Scenario %s finished: %s (%d/%d converged)",
                scenario_id, final_status, completed, completed + failed)


def _apply_connection_changes(base_connections: list, changes: list) -> list:
    conns = {c["connection_id"]: dict(c) for c in base_connections}

    for change in changes:
        action = change.get("action")
        cid = change.get("connection_id")

        if action == "remove" and cid in conns:
            del conns[cid]
        elif action == "disable" and cid in conns:
            conns[cid]["disabled"] = True
        elif action == "enable" and cid in conns:
            conns[cid].pop("disabled", None)
        elif action == "add":
            conns[cid] = {
                "connection_id": cid,
                "from_node_id": change["from_node_id"],
                "to_node_id": change["to_node_id"],
                "cable_id": change["cable_id"],
                "length": change.get("length", 1.0),
            }
        elif action == "update" and cid in conns:
            for k in ("from_node_id", "to_node_id", "cable_id", "length"):
                if k in change:
                    conns[cid][k] = change[k]

    return list(conns.values())


def _compute_admittances(cables_map: dict, conn_data: list) -> list:
    admittances = []
    for cable_id, length in conn_data:
        cable = cables_map.get(cable_id)
        if cable is None:
            admittances.append([complex(0.01, 0.001)])
            continue
        z_real = cable.get("r_imp_real", cable.get("RImpReal", 0.01))
        z_imag = cable.get("r_imp_imag", cable.get("RImpImag", 0.001))
        z = complex(z_real, z_imag) * length
        if z == 0:
            z = complex(0.001, 0.0001)
        admittances.append([1 / z])
    return admittances


scenario_runner = ScenarioRunner()

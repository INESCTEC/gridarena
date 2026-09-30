"""CRUD operations for Offline Scenario tables."""

import json
from typing import List, Optional


def insert_offline_scenario(sc: dict, conn, cursor):
    cursor.execute(
        """
        INSERT INTO "OfflineScenario"
            (scenario_id, source_dt_id, grid_id, name, description,
             grid_snapshot, connection_changes, power_limits, powerflow_config,
             simulation_status, total_timestamps, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (
            sc["scenario_id"],
            sc["source_dt_id"],
            sc["grid_id"],
            sc.get("name", ""),
            sc.get("description", ""),
            json.dumps(sc.get("grid_snapshot", {})),
            json.dumps(sc.get("connection_changes", [])),
            json.dumps(sc.get("power_limits", {})),
            json.dumps(sc.get("powerflow_config", {})),
            "pending",
            sc.get("total_timestamps", 0),
        ),
    )
    conn.commit()


def _parse_jsonb(value):
    if isinstance(value, (dict, list)):
        return value
    if value:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _row_to_scenario(row) -> dict:
    return {
        "scenario_id": row[0],
        "source_dt_id": row[1],
        "grid_id": row[2],
        "name": row[3],
        "description": row[4],
        "grid_snapshot": _parse_jsonb(row[5]),
        "connection_changes": _parse_jsonb(row[6]),
        "power_limits": _parse_jsonb(row[7]),
        "powerflow_config": _parse_jsonb(row[8]),
        "simulation_status": row[9],
        "total_timestamps": row[10],
        "completed_timestamps": row[11],
        "failed_timestamps": row[12],
        "created_at": str(row[13]),
        "updated_at": str(row[14]),
        "completed_at": str(row[15]) if row[15] else None,
        "error": row[16],
    }


_SELECT_COLS = """
    scenario_id, source_dt_id, grid_id, name, description,
    grid_snapshot, connection_changes, power_limits, powerflow_config,
    simulation_status, total_timestamps, completed_timestamps, failed_timestamps,
    created_at, updated_at, completed_at, error
"""


def get_offline_scenario(scenario_id: str, cursor) -> Optional[dict]:
    cursor.execute(
        f'SELECT {_SELECT_COLS} FROM "OfflineScenario" WHERE scenario_id = %s',
        (scenario_id,),
    )
    row = cursor.fetchone()
    return _row_to_scenario(row) if row else None


def list_offline_scenarios(cursor, source_dt_id: str = None) -> List[dict]:
    if source_dt_id:
        cursor.execute(
            f'SELECT {_SELECT_COLS} FROM "OfflineScenario" WHERE source_dt_id = %s ORDER BY created_at DESC',
            (source_dt_id,),
        )
    else:
        cursor.execute(
            f'SELECT {_SELECT_COLS} FROM "OfflineScenario" ORDER BY created_at DESC'
        )
    return [_row_to_scenario(r) for r in cursor.fetchall()]


def delete_offline_scenario(scenario_id: str, conn, cursor):
    cursor.execute('DELETE FROM "OfflineScenario" WHERE scenario_id = %s', (scenario_id,))
    conn.commit()


def update_scenario_changes(scenario_id: str, connection_changes: list, conn, cursor):
    cursor.execute(
        'UPDATE "OfflineScenario" SET connection_changes = %s, updated_at = NOW() WHERE scenario_id = %s',
        (json.dumps(connection_changes), scenario_id),
    )
    conn.commit()


def update_scenario_power_limits(scenario_id: str, power_limits: dict, conn, cursor):
    cursor.execute(
        'UPDATE "OfflineScenario" SET power_limits = %s, updated_at = NOW() WHERE scenario_id = %s',
        (json.dumps(power_limits), scenario_id),
    )
    conn.commit()


def update_scenario_grid_snapshot(scenario_id: str, grid_snapshot: dict, conn, cursor):
    cursor.execute(
        'UPDATE "OfflineScenario" SET grid_snapshot = %s, updated_at = NOW() WHERE scenario_id = %s',
        (json.dumps(grid_snapshot), scenario_id),
    )
    conn.commit()


def update_scenario_simulation_status(scenario_id: str, status: str, conn, cursor,
                                       completed: int = None, failed: int = None, error: str = None):
    parts = ["simulation_status = %s", "updated_at = NOW()"]
    params = [status]
    if completed is not None:
        parts.append("completed_timestamps = %s")
        params.append(completed)
    if failed is not None:
        parts.append("failed_timestamps = %s")
        params.append(failed)
    if error is not None:
        parts.append("error = %s")
        params.append(error)
    if status in ("completed", "partially_completed", "failed"):
        parts.append("completed_at = NOW()")
    params.append(scenario_id)
    cursor.execute(
        f'UPDATE "OfflineScenario" SET {", ".join(parts)} WHERE scenario_id = %s',
        params,
    )
    conn.commit()


# ── Results ──


def insert_scenario_result(scenario_id: str, result: dict, conn, cursor):
    cursor.execute(
        """
        INSERT INTO "OfflineScenarioResult"
            (scenario_id, "timestamp", convergence_status, node_voltages, execution_time_ms, error)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (scenario_id, "timestamp") DO UPDATE SET
            convergence_status = EXCLUDED.convergence_status,
            node_voltages = EXCLUDED.node_voltages,
            execution_time_ms = EXCLUDED.execution_time_ms,
            error = EXCLUDED.error
        """,
        (
            scenario_id,
            result["timestamp"],
            result.get("convergence_status", "unknown"),
            json.dumps(result.get("node_voltages")) if result.get("node_voltages") else None,
            result.get("execution_time_ms"),
            result.get("error"),
        ),
    )
    conn.commit()


def list_scenario_results(scenario_id: str, cursor, limit: int = 5000) -> List[dict]:
    cursor.execute(
        """
        SELECT result_id, scenario_id, "timestamp", convergence_status,
               node_voltages, execution_time_ms, error
        FROM "OfflineScenarioResult"
        WHERE scenario_id = %s
        ORDER BY "timestamp" ASC
        LIMIT %s
        """,
        (scenario_id, limit),
    )
    return [
        {
            "result_id": r[0], "scenario_id": r[1], "timestamp": str(r[2]),
            "convergence_status": r[3],
            "node_voltages": r[4] if isinstance(r[4], dict) else (_parse_jsonb(r[4]) if r[4] else None),
            "execution_time_ms": r[5], "error": r[6],
        }
        for r in cursor.fetchall()
    ]


def get_scenario_voltage_timeseries(scenario_id: str, cursor, node_id: str = None) -> List[dict]:
    results = list_scenario_results(scenario_id, cursor)
    series = []
    for r in results:
        if r["convergence_status"] != "converged" or not r.get("node_voltages"):
            continue
        nv = r["node_voltages"]
        entry = {"timestamp": r["timestamp"]}
        if node_id:
            nd = nv.get(node_id)
            if nd:
                entry.update(nd)
                series.append(entry)
        else:
            entry["nodes"] = nv
            series.append(entry)
    return series


def get_scenario_violations(scenario_id: str, cursor, voltage_ref: float = 230.0,
                            threshold: float = 0.10) -> List[dict]:
    results = list_scenario_results(scenario_id, cursor)
    violations = []
    for r in results:
        if r["convergence_status"] != "converged" or not r.get("node_voltages"):
            continue
        nv = r["node_voltages"]
        for nid, nd in nv.items():
            v = nd.get("simulated_voltage")
            if v is None:
                continue
            deviation = abs(v - voltage_ref) / voltage_ref
            if deviation > threshold:
                violations.append({
                    "timestamp": r["timestamp"],
                    "node_id": nid,
                    "simulated_voltage": v,
                    "deviation_pct": round(deviation * 100, 2),
                    "type": "overvoltage" if v > voltage_ref else "undervoltage",
                })
    return violations

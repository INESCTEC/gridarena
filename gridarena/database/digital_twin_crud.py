"""CRUD operations for Digital Twin tables."""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def insert_digital_twin(dt: dict, conn, cursor):
    cursor.execute(
        """
        INSERT INTO "DigitalTwin"
            (digital_twin_id, grid_id, name, description, status,
             update_interval_seconds, broker_type, broker_topic,
             source_config, field_mapping, powerflow_config,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (
            dt["digital_twin_id"],
            dt["grid_id"],
            dt.get("name", ""),
            dt.get("description", ""),
            dt.get("status", "created"),
            dt.get("update_interval_seconds", 60),
            dt.get("broker_type", "redis"),
            dt.get("broker_topic", ""),
            json.dumps(dt.get("source_config", {})),
            json.dumps({
                "field_mapping": dt.get("field_mapping"),
                "node_assignments": dt.get("node_assignments"),
            }),
            json.dumps(dt.get("powerflow_config", {})),
        ),
    )
    conn.commit()


def get_digital_twin(digital_twin_id: str, cursor) -> Optional[dict]:
    cursor.execute(
        """
        SELECT digital_twin_id, grid_id, name, description, status,
               update_interval_seconds, broker_type, broker_topic,
               source_config, field_mapping, powerflow_config,
               created_at, updated_at, last_run_at, last_error
        FROM "DigitalTwin"
        WHERE digital_twin_id = %s
        """,
        (digital_twin_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_dt_dict(row)


def list_digital_twins(cursor) -> List[dict]:
    cursor.execute(
        """
        SELECT digital_twin_id, grid_id, name, description, status,
               update_interval_seconds, broker_type, broker_topic,
               source_config, field_mapping, powerflow_config,
               created_at, updated_at, last_run_at, last_error
        FROM "DigitalTwin"
        ORDER BY created_at DESC
        """
    )
    return [_row_to_dt_dict(row) for row in cursor.fetchall()]


def update_digital_twin(digital_twin_id: str, updates: dict, conn, cursor):
    set_clauses = []
    params = []
    for key, value in updates.items():
        if key in ("source_config", "field_mapping", "powerflow_config"):
            set_clauses.append(f"{key} = %s")
            params.append(json.dumps(value))
        else:
            set_clauses.append(f"{key} = %s")
            params.append(value)
    set_clauses.append("updated_at = NOW()")
    params.append(digital_twin_id)
    cursor.execute(
        f'UPDATE "DigitalTwin" SET {", ".join(set_clauses)} WHERE digital_twin_id = %s',
        params,
    )
    conn.commit()


def delete_digital_twin(digital_twin_id: str, conn, cursor):
    cursor.execute(
        'DELETE FROM "DigitalTwin" WHERE digital_twin_id = %s',
        (digital_twin_id,),
    )
    conn.commit()


def update_digital_twin_status(digital_twin_id: str, status: str, conn, cursor, error: str = None):
    if error:
        cursor.execute(
            """
            UPDATE "DigitalTwin"
            SET status = %s, last_error = %s, updated_at = NOW()
            WHERE digital_twin_id = %s
            """,
            (status, error, digital_twin_id),
        )
    else:
        cursor.execute(
            """
            UPDATE "DigitalTwin"
            SET status = %s, last_error = NULL, updated_at = NOW()
            WHERE digital_twin_id = %s
            """,
            (status, digital_twin_id),
        )
    conn.commit()


def update_digital_twin_last_run(digital_twin_id: str, conn, cursor, latest_batch: dict = None):
    if latest_batch is not None:
        try:
            cursor.execute(
                'UPDATE "DigitalTwin" SET last_run_at = NOW(), updated_at = NOW(), latest_batch = %s WHERE digital_twin_id = %s',
                (json.dumps(latest_batch), digital_twin_id),
            )
            conn.commit()
            return
        except Exception as e:
            logger.warning("Failed to store latest_batch (column may not exist): %s", e)
            conn.rollback()

    cursor.execute(
        'UPDATE "DigitalTwin" SET last_run_at = NOW(), updated_at = NOW() WHERE digital_twin_id = %s',
        (digital_twin_id,),
    )
    conn.commit()


def get_latest_batch(digital_twin_id: str, cursor) -> Optional[dict]:
    """Read latest_batch from DigitalTwin. Uses a separate query that won't poison the caller's cursor."""
    from gridarena.database import get_db_connection

    conn2, cursor2 = get_db_connection()
    try:
        cursor2.execute(
            'SELECT latest_batch FROM "DigitalTwin" WHERE digital_twin_id = %s',
            (digital_twin_id,),
        )
        row = cursor2.fetchone()
        if row is None or row[0] is None:
            return None
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        logger.warning("get_latest_batch failed for %s: %s", digital_twin_id, e)
        return None
    finally:
        conn2.close()


# ── Events ──


def insert_digital_twin_event(digital_twin_id: str, event_type: str, message: str,
                              conn, cursor, details: dict = None):
    cursor.execute(
        """
        INSERT INTO "DigitalTwinEvent" (digital_twin_id, event_type, message, details)
        VALUES (%s, %s, %s, %s)
        """,
        (digital_twin_id, event_type, message, json.dumps(details) if details else None),
    )
    conn.commit()


def list_digital_twin_events(digital_twin_id: str, cursor, limit: int = 50) -> List[dict]:
    cursor.execute(
        """
        SELECT event_id, digital_twin_id, event_type, message, details, created_at
        FROM "DigitalTwinEvent"
        WHERE digital_twin_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (digital_twin_id, limit),
    )
    return [
        {
            "event_id": r[0],
            "digital_twin_id": r[1],
            "event_type": r[2],
            "message": r[3],
            "details": r[4],
            "created_at": str(r[5]),
        }
        for r in cursor.fetchall()
    ]


# ── Results / Metrics ──


def insert_digital_twin_result(digital_twin_id: str, metrics: dict, conn, cursor):
    cursor.execute(
        """
        INSERT INTO "DigitalTwinResult"
            (digital_twin_id, "timestamp", measurements_count, missing_measurements,
             invalid_measurements, convergence_status, voltage_mae, voltage_rmse,
             max_voltage_error, active_power_error, reactive_power_error,
             execution_time_ms, powerflow_algorithm, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            digital_twin_id,
            metrics["timestamp"],
            metrics.get("measurements_count", 0),
            metrics.get("missing_measurements", 0),
            metrics.get("invalid_measurements", 0),
            metrics.get("convergence_status", "unknown"),
            metrics.get("voltage_mae"),
            metrics.get("voltage_rmse"),
            metrics.get("max_voltage_error"),
            metrics.get("active_power_error"),
            metrics.get("reactive_power_error"),
            metrics.get("execution_time_ms"),
            metrics.get("powerflow_algorithm", "backward_forward_sweep"),
            json.dumps(metrics.get("details")) if metrics.get("details") else None,
        ),
    )
    conn.commit()


def list_digital_twin_results(digital_twin_id: str, cursor, limit: int = 50) -> List[dict]:
    cursor.execute(
        """
        SELECT result_id, digital_twin_id, "timestamp", measurements_count,
               missing_measurements, invalid_measurements, convergence_status,
               voltage_mae, voltage_rmse, max_voltage_error,
               active_power_error, reactive_power_error,
               execution_time_ms, powerflow_algorithm, details, created_at
        FROM "DigitalTwinResult"
        WHERE digital_twin_id = %s
        ORDER BY "timestamp" DESC
        LIMIT %s
        """,
        (digital_twin_id, limit),
    )
    return [_row_to_result_dict(r) for r in cursor.fetchall()]


def get_latest_digital_twin_result(digital_twin_id: str, cursor) -> Optional[dict]:
    cursor.execute(
        """
        SELECT result_id, digital_twin_id, "timestamp", measurements_count,
               missing_measurements, invalid_measurements, convergence_status,
               voltage_mae, voltage_rmse, max_voltage_error,
               active_power_error, reactive_power_error,
               execution_time_ms, powerflow_algorithm, details, created_at
        FROM "DigitalTwinResult"
        WHERE digital_twin_id = %s
        ORDER BY "timestamp" DESC
        LIMIT 1
        """,
        (digital_twin_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_result_dict(row)


def get_digital_twin_metrics(digital_twin_id: str, cursor, limit: int = 100) -> dict:
    results = list_digital_twin_results(digital_twin_id, cursor, limit=limit)
    if not results:
        return {"total_runs": 0, "results": []}

    converged = [r for r in results if r["convergence_status"] == "converged"]
    mae_vals = [r["voltage_mae"] for r in converged if r["voltage_mae"] is not None]
    rmse_vals = [r["voltage_rmse"] for r in converged if r["voltage_rmse"] is not None]

    return {
        "total_runs": len(results),
        "converged_runs": len(converged),
        "avg_voltage_mae": sum(mae_vals) / len(mae_vals) if mae_vals else None,
        "avg_voltage_rmse": sum(rmse_vals) / len(rmse_vals) if rmse_vals else None,
        "latest_result": results[0] if results else None,
        "results": results,
    }


# ── Diagnostics ──


def diagnose_digital_twin(digital_twin_id: str) -> dict:
    """Run a full diagnostic on a digital twin's stored data. Returns a report dict."""
    from gridarena.database import get_db_connection

    report = {"digital_twin_id": digital_twin_id, "checks": {}}

    conn, cursor = get_db_connection()
    try:
        cursor.execute('SELECT 1 FROM "DigitalTwin" WHERE digital_twin_id = %s', (digital_twin_id,))
        report["checks"]["exists"] = cursor.fetchone() is not None

        if not report["checks"]["exists"]:
            return report

        cursor.execute(
            'SELECT field_mapping FROM "DigitalTwin" WHERE digital_twin_id = %s',
            (digital_twin_id,),
        )
        raw = cursor.fetchone()[0]
        report["checks"]["raw_field_mapping_type"] = type(raw).__name__
        report["checks"]["raw_field_mapping_keys"] = list(raw.keys()) if isinstance(raw, dict) else None
        if isinstance(raw, dict):
            report["checks"]["has_node_assignments_key"] = "node_assignments" in raw
            na = raw.get("node_assignments")
            report["checks"]["node_assignments_count"] = len(na) if isinstance(na, list) else None
            report["checks"]["node_assignments_sample"] = na[0] if isinstance(na, list) and len(na) > 0 else None

        has_latest_batch = False
        try:
            cursor.execute(
                'SELECT latest_batch IS NOT NULL FROM "DigitalTwin" WHERE digital_twin_id = %s',
                (digital_twin_id,),
            )
            has_latest_batch = cursor.fetchone()[0]
            report["checks"]["latest_batch_column_exists"] = True
            report["checks"]["latest_batch_has_data"] = has_latest_batch
        except Exception as e:
            conn.rollback()
            report["checks"]["latest_batch_column_exists"] = False
            report["checks"]["latest_batch_error"] = str(e)

        if has_latest_batch:
            try:
                cursor.execute(
                    'SELECT latest_batch FROM "DigitalTwin" WHERE digital_twin_id = %s',
                    (digital_twin_id,),
                )
                batch = cursor.fetchone()[0]
                if isinstance(batch, dict):
                    report["checks"]["latest_batch_keys"] = list(batch.keys())
                    m = batch.get("measurements")
                    report["checks"]["latest_batch_measurements_count"] = len(m) if isinstance(m, list) else None
                    if isinstance(m, list) and len(m) > 0:
                        report["checks"]["latest_batch_sample"] = m[0]
            except Exception as e:
                conn.rollback()
                report["checks"]["latest_batch_read_error"] = str(e)

        cursor.execute(
            'SELECT COUNT(*) FROM "DigitalTwinResult" WHERE digital_twin_id = %s',
            (digital_twin_id,),
        )
        report["checks"]["results_count"] = cursor.fetchone()[0]

        cursor.execute(
            'SELECT COUNT(*) FROM "DigitalTwinEvent" WHERE digital_twin_id = %s',
            (digital_twin_id,),
        )
        report["checks"]["events_count"] = cursor.fetchone()[0]

        dt = get_digital_twin(digital_twin_id, cursor)
        report["checks"]["parsed_node_assignments_count"] = len(dt.get("node_assignments") or [])
        report["checks"]["parsed_field_mapping_keys"] = list((dt.get("field_mapping") or {}).keys())
        report["checks"]["status"] = dt.get("status")
        report["checks"]["grid_id"] = dt.get("grid_id")

        grid_id = dt.get("grid_id")
        if grid_id:
            cursor.execute('SELECT COUNT(*) FROM "Node" WHERE grid_id = %s', (grid_id,))
            report["checks"]["grid_node_count"] = cursor.fetchone()[0]

    except Exception as e:
        report["error"] = str(e)
    finally:
        conn.close()

    return report


# ── Internal helpers ──


def _parse_jsonb(value) -> dict:
    if isinstance(value, dict):
        return value
    if value:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _row_to_dt_dict(row) -> dict:
    raw_mapping = _parse_jsonb(row[9])

    # The field_mapping column stores a wrapper: {"field_mapping": {...}, "node_assignments": [...]}
    # Or for legacy twins it stores the field_mapping directly: {"timestamp": "...", "measurements": "...", ...}
    if "node_assignments" in raw_mapping or "field_mapping" in raw_mapping:
        field_mapping = raw_mapping.get("field_mapping") or {}
        node_assignments = raw_mapping.get("node_assignments")
    else:
        field_mapping = raw_mapping
        node_assignments = None

    return {
        "digital_twin_id": row[0],
        "grid_id": row[1],
        "name": row[2],
        "description": row[3],
        "status": row[4],
        "update_interval_seconds": row[5],
        "broker_type": row[6],
        "broker_topic": row[7],
        "source_config": _parse_jsonb(row[8]),
        "field_mapping": field_mapping if isinstance(field_mapping, dict) else {},
        "node_assignments": node_assignments,
        "powerflow_config": _parse_jsonb(row[10]),
        "created_at": str(row[11]),
        "updated_at": str(row[12]),
        "last_run_at": str(row[13]) if row[13] else None,
        "last_error": row[14],
    }


def _row_to_result_dict(row) -> dict:
    return {
        "result_id": row[0],
        "digital_twin_id": row[1],
        "timestamp": str(row[2]),
        "measurements_count": row[3],
        "missing_measurements": row[4],
        "invalid_measurements": row[5],
        "convergence_status": row[6],
        "voltage_mae": row[7],
        "voltage_rmse": row[8],
        "max_voltage_error": row[9],
        "active_power_error": row[10],
        "reactive_power_error": row[11],
        "execution_time_ms": row[12],
        "powerflow_algorithm": row[13],
        "details": row[14],
        "created_at": str(row[15]),
    }

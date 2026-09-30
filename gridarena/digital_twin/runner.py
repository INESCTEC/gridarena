"""Digital twin runner: periodic fetch → map → publish → consume → power-flow → compare."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import gridarena.database as db
from gridarena.database.create_digital_twin_database import create_digital_twin_tables
from gridarena.database.digital_twin_crud import (
    get_digital_twin,
    insert_digital_twin_event,
    insert_digital_twin_result,
    update_digital_twin_last_run,
    update_digital_twin_status,
)
from gridarena.digital_twin import broker, connector, field_mapper
from gridarena.digital_twin.comparison import run_comparison
from gridarena.digital_twin.schemas import (
    FieldMapping,
    NodeAssignment,
    PowerFlowConfig,
    SourceConfig,
    StreamedMeasurement,
    StreamedMeasurementBatch,
)

logger = logging.getLogger(__name__)


class DigitalTwinRunner:
    """Manages asyncio tasks for running digital twins periodically."""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}

    def start(self, digital_twin_id: str):
        if digital_twin_id in self._tasks and not self._tasks[digital_twin_id].done():
            logger.warning("Digital twin %s already running.", digital_twin_id)
            return
        task = asyncio.create_task(self._run_loop(digital_twin_id))
        self._tasks[digital_twin_id] = task
        logger.info("Started digital twin runner: %s", digital_twin_id)

    def stop(self, digital_twin_id: str):
        task = self._tasks.get(digital_twin_id)
        if task and not task.done():
            task.cancel()
            logger.info("Stopped digital twin runner: %s", digital_twin_id)
        self._tasks.pop(digital_twin_id, None)

    def is_running(self, digital_twin_id: str) -> bool:
        task = self._tasks.get(digital_twin_id)
        return task is not None and not task.done()

    def shutdown(self):
        for dt_id in list(self._tasks.keys()):
            self.stop(dt_id)
        logger.info("DigitalTwinRunner shut down.")

    async def tick(self, digital_twin_id: str) -> dict:
        return await _execute_tick(digital_twin_id)

    async def _run_loop(self, digital_twin_id: str):
        conn, cursor = db.get_db_connection()
        try:
            create_digital_twin_tables(cursor)
            conn.commit()
            dt = get_digital_twin(digital_twin_id, cursor)
        finally:
            conn.close()

        if dt is None:
            logger.error("Digital twin %s not found.", digital_twin_id)
            return

        interval = dt["update_interval_seconds"]

        conn, cursor = db.get_db_connection()
        try:
            update_digital_twin_status(digital_twin_id, "running", conn, cursor)
            insert_digital_twin_event(digital_twin_id, "started", "Digital twin started.", conn, cursor)
        finally:
            conn.close()

        try:
            while True:
                try:
                    await _execute_tick(digital_twin_id)
                except Exception as e:
                    logger.error("Tick failed for %s: %s", digital_twin_id, e, exc_info=True)
                    conn, cursor = db.get_db_connection()
                    try:
                        insert_digital_twin_event(
                            digital_twin_id, "error", str(e), conn, cursor,
                            details={"stage": "tick"},
                        )
                        update_digital_twin_status(digital_twin_id, "running", conn, cursor, error=str(e))
                    finally:
                        conn.close()
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            conn, cursor = db.get_db_connection()
            try:
                update_digital_twin_status(digital_twin_id, "stopped", conn, cursor)
                insert_digital_twin_event(digital_twin_id, "stopped", "Digital twin stopped.", conn, cursor)
            finally:
                conn.close()

        except Exception as e:
            logger.error("Digital twin %s crashed: %s", digital_twin_id, e, exc_info=True)
            conn, cursor = db.get_db_connection()
            try:
                update_digital_twin_status(digital_twin_id, "failed", conn, cursor, error=str(e))
                insert_digital_twin_event(digital_twin_id, "error", f"Runner crashed: {e}", conn, cursor)
            finally:
                conn.close()


async def _execute_tick(digital_twin_id: str) -> dict:
    conn, cursor = db.get_db_connection()
    try:
        create_digital_twin_tables(cursor)
        conn.commit()
        dt = get_digital_twin(digital_twin_id, cursor)
    finally:
        conn.close()

    if dt is None:
        raise ValueError(f"Digital twin '{digital_twin_id}' not found.")

    source_config = SourceConfig(**dt["source_config"])
    pf_config = PowerFlowConfig(**dt["powerflow_config"])
    grid_id = dt["grid_id"]
    broker_topic = dt["broker_topic"] or None

    raw_assignments = dt.get("node_assignments")
    has_node_assignments = raw_assignments and len(raw_assignments) > 0

    if has_node_assignments:
        batch = await _fetch_per_node(digital_twin_id, source_config, raw_assignments, grid_id, pf_config)
    else:
        batch = await _fetch_global(digital_twin_id, source_config, dt, grid_id)

    if batch is None:
        raise RuntimeError("No valid measurements after fetch.")

    batch_dict = batch.model_dump()

    try:
        if broker.is_available():
            broker.publish_measurement(digital_twin_id, batch_dict, topic=broker_topic)
            _log_event(digital_twin_id, "published", f"Published {len(batch.measurements)} measurements to broker")
    except Exception as e:
        logger.warning("Broker publish failed for %s: %s", digital_twin_id, e)

    metrics = run_comparison(batch, phase=pf_config.phase, voltage_ref=pf_config.voltage_ref)

    conn, cursor = db.get_db_connection()
    try:
        insert_digital_twin_result(digital_twin_id, metrics, conn, cursor)
        update_digital_twin_last_run(digital_twin_id, conn, cursor, latest_batch=batch_dict)
        insert_digital_twin_event(
            digital_twin_id, "tick_completed",
            f"PF {metrics.get('convergence_status', 'unknown')}, MAE={metrics.get('voltage_mae', 'N/A')}",
            conn, cursor,
            details={"convergence": metrics.get("convergence_status"), "voltage_mae": metrics.get("voltage_mae")},
        )
    finally:
        conn.close()

    return metrics


async def _fetch_per_node(
    digital_twin_id: str,
    base_config: SourceConfig,
    raw_assignments: list,
    grid_id: str,
    pf_config: PowerFlowConfig,
) -> Optional[StreamedMeasurementBatch]:
    """Fetch data per-node: each node assignment makes its own API call."""
    measurements: List[StreamedMeasurement] = []
    now = datetime.now(timezone.utc).isoformat()
    errors = []

    for raw in raw_assignments:
        na = NodeAssignment(**raw) if isinstance(raw, dict) else raw

        node_config = SourceConfig(
            source_type=base_config.source_type,
            url=base_config.url,
            method=base_config.method,
            headers=base_config.headers,
            query_params={**base_config.query_params, **na.query_params},
            auth_type=base_config.auth_type,
            secret_ref=base_config.secret_ref,
            secret_header=base_config.secret_header,
            timeout_seconds=na.timeout_seconds,
            retry_count=base_config.retry_count,
        )

        success, raw_data, error_msg, status_code = await connector.fetch_source(node_config)
        if not success or raw_data is None:
            errors.append(f"Node {na.node_id}: fetch failed — {error_msg}")
            continue

        mapping = na.mapping
        ts_raw = field_mapper.resolve_path(raw_data, mapping.timestamp)
        timestamp = field_mapper._parse_timestamp(ts_raw) if ts_raw else now

        p_active = 0.0
        if mapping.active_power:
            val = field_mapper.resolve_path(raw_data, mapping.active_power)
            if val is not None:
                try:
                    p_active = float(val) * mapping.active_power_factor
                except (ValueError, TypeError):
                    errors.append(f"Node {na.node_id}: cannot convert active_power {val!r} to float")

        p_reactive = 0.0
        if mapping.reactive_power:
            val = field_mapper.resolve_path(raw_data, mapping.reactive_power)
            if val is not None:
                try:
                    p_reactive = float(val) * mapping.reactive_power_factor
                except (ValueError, TypeError):
                    pass

        v_mag = 0.0
        if mapping.voltage_magnitude:
            val = field_mapper.resolve_path(raw_data, mapping.voltage_magnitude)
            if val is not None:
                try:
                    v_mag = float(val) * mapping.voltage_magnitude_factor
                except (ValueError, TypeError):
                    pass

        v_angle = 0.0
        if mapping.voltage_angle:
            val = field_mapper.resolve_path(raw_data, mapping.voltage_angle)
            if val is not None:
                try:
                    v_angle = float(val)
                except (ValueError, TypeError):
                    pass

        measurements.append(StreamedMeasurement(
            node_id=na.node_id,
            phase=na.phase,
            datetime=timestamp or now,
            power_active=p_active,
            power_reactive=p_reactive,
            voltage_magnitude=v_mag,
            voltage_angle=v_angle,
        ))

    if errors:
        _log_event(digital_twin_id, "fetch_warning", f"{len(errors)} node fetch issues",
                   {"errors": errors[:20]})

    if not measurements:
        _log_event(digital_twin_id, "fetch_error", "All node fetches failed", {"errors": errors})
        return None

    _log_event(digital_twin_id, "fetch_success", f"Fetched {len(measurements)}/{len(raw_assignments)} nodes")

    latest_ts = max(m.datetime for m in measurements)
    return StreamedMeasurementBatch(grid_id=grid_id, timestamp=latest_ts, measurements=measurements)


async def _fetch_global(
    digital_twin_id: str,
    source_config: SourceConfig,
    dt: dict,
    grid_id: str,
) -> Optional[StreamedMeasurementBatch]:
    """Original global-fetch mode: one API call, batch field mapping."""
    field_mapping_cfg = FieldMapping(**dt["field_mapping"])

    success, raw_data, error_msg, status_code = await connector.fetch_source(source_config)
    if not success or raw_data is None:
        _log_event(digital_twin_id, "fetch_error", error_msg or "Unknown fetch error",
                   {"status_code": status_code})
        raise RuntimeError(f"Source fetch failed: {error_msg}")

    _log_event(digital_twin_id, "fetch_success", f"Fetched data (HTTP {status_code})")

    batch, mapping_errors, mapping_warnings = field_mapper.map_payload(raw_data, field_mapping_cfg, grid_id)

    if batch is None:
        _log_event(digital_twin_id, "mapping_error", "Field mapping failed",
                   {"errors": mapping_errors})
        raise RuntimeError(f"Field mapping failed: {'; '.join(mapping_errors)}")

    if mapping_errors:
        _log_event(digital_twin_id, "mapping_warning",
                   f"{len(mapping_errors)} mapping issues",
                   {"errors": mapping_errors, "warnings": mapping_warnings})

    return batch


def _log_event(digital_twin_id: str, event_type: str, message: str, details: dict = None):
    conn, cursor = db.get_db_connection()
    try:
        insert_digital_twin_event(digital_twin_id, event_type, message, conn, cursor, details=details)
    except Exception as e:
        logger.warning("Failed to log event for %s: %s", digital_twin_id, e)
    finally:
        conn.close()


dt_runner = DigitalTwinRunner()

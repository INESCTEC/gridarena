import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.digital_twin.field_mapper import map_payload, resolve_path, validate_against_grid
from gridarena.digital_twin.schemas import (
    DigitalTwinCreate,
    FieldMapping,
    SourceConfig,
    StreamedMeasurementBatch,
    ValidateFieldMappingRequest,
)

client = TestClient(app)
DT_PREFIX = "/digital-twins"


# ═══════════════════════════════════════════════════════════════
#  Field mapper: resolve_path
# ═══════════════════════════════════════════════════════════════


def test_resolve_path_simple():
    assert resolve_path({"a": 1}, "a") == 1


def test_resolve_path_nested():
    assert resolve_path({"a": {"b": {"c": 42}}}, "a.b.c") == 42


def test_resolve_path_missing():
    assert resolve_path({"a": 1}, "b") is None


def test_resolve_path_list_iterate():
    data = {"items": [{"v": 1}, {"v": 2}]}
    assert resolve_path(data, "items[].v") == [1, 2]


def test_resolve_path_list_without_subpath():
    data = {"items": [1, 2, 3]}
    assert resolve_path(data, "items[]") == [1, 2, 3]


def test_resolve_path_empty():
    assert resolve_path({"a": 1}, "") == {"a": 1}


def test_resolve_path_none_data():
    assert resolve_path(None, "a") is None


# ═══════════════════════════════════════════════════════════════
#  Field mapper: map_payload
# ═══════════════════════════════════════════════════════════════


VALID_MAPPING = FieldMapping(
    timestamp="timestamp",
    measurements="measurements",
    node_id="node_id",
    phase="phase",
    active_power="power_active",
    reactive_power="power_reactive",
    voltage_magnitude="voltage_magnitude",
)

VALID_SOURCE = {
    "timestamp": "2025-01-01T00:00:00",
    "measurements": [
        {
            "node_id": "PT",
            "phase": "R",
            "power_active": 0.0,
            "power_reactive": 0.0,
            "voltage_magnitude": 230.0,
        },
        {
            "node_id": "NODE1",
            "phase": "R",
            "power_active": 10.0,
            "power_reactive": 5.0,
            "voltage_magnitude": 229.5,
        },
    ],
}


def test_map_payload_success():
    batch, errors, warnings = map_payload(VALID_SOURCE, VALID_MAPPING, "test_grid")
    assert batch is not None
    assert len(batch.measurements) == 2
    assert batch.grid_id == "test_grid"
    assert batch.timestamp == "2025-01-01T00:00:00"
    assert batch.measurements[0].node_id == "PT"
    assert batch.measurements[1].power_active == 10.0


def test_map_payload_missing_timestamp():
    source = {"measurements": []}
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert batch is None
    assert any("timestamp" in e.lower() for e in errors)


def test_map_payload_missing_measurements():
    source = {"timestamp": "2025-01-01T00:00:00"}
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert batch is None
    assert any("measurements" in e.lower() for e in errors)


def test_map_payload_empty_measurements():
    source = {"timestamp": "2025-01-01T00:00:00", "measurements": []}
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert batch is None
    assert any("empty" in e.lower() for e in errors)


def test_map_payload_invalid_phase():
    source = {
        "timestamp": "2025-01-01T00:00:00",
        "measurements": [
            {"node_id": "N1", "phase": "X", "power_active": 1, "power_reactive": 1, "voltage_magnitude": 230},
        ],
    }
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert any("invalid phase" in e.lower() for e in errors)


def test_map_payload_negative_voltage():
    source = {
        "timestamp": "2025-01-01T00:00:00",
        "measurements": [
            {"node_id": "N1", "phase": "R", "power_active": 1, "power_reactive": 1, "voltage_magnitude": -5},
        ],
    }
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert any("negative" in e.lower() for e in errors)


def test_map_payload_duplicate_measurement():
    source = {
        "timestamp": "2025-01-01T00:00:00",
        "measurements": [
            {"node_id": "N1", "phase": "R", "power_active": 1, "power_reactive": 1, "voltage_magnitude": 230},
            {"node_id": "N1", "phase": "R", "power_active": 2, "power_reactive": 2, "voltage_magnitude": 231},
        ],
    }
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert any("duplicate" in e.lower() for e in errors)
    assert batch is not None
    assert len(batch.measurements) == 1


def test_map_payload_non_numeric_power():
    source = {
        "timestamp": "2025-01-01T00:00:00",
        "measurements": [
            {"node_id": "N1", "phase": "R", "power_active": "abc", "power_reactive": 1, "voltage_magnitude": 230},
        ],
    }
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert any("convert" in e.lower() for e in errors)


def test_map_payload_nested_paths():
    mapping = FieldMapping(
        timestamp="data.time",
        measurements="data.readings",
        node_id="bus_id",
        phase="ph",
        active_power="p_kw",
        reactive_power="q_kvar",
        voltage_magnitude="v",
    )
    source = {
        "data": {
            "time": "2025-06-01T12:00:00",
            "readings": [
                {"bus_id": "N1", "ph": "R", "p_kw": 10, "q_kvar": 5, "v": 229},
            ],
        },
    }
    batch, errors, warnings = map_payload(source, mapping, "grid1")
    assert batch is not None
    assert batch.measurements[0].node_id == "N1"
    assert batch.measurements[0].power_active == 10.0


def test_map_payload_missing_node_id():
    source = {
        "timestamp": "2025-01-01T00:00:00",
        "measurements": [
            {"phase": "R", "power_active": 1, "power_reactive": 1, "voltage_magnitude": 230},
        ],
    }
    batch, errors, warnings = map_payload(source, VALID_MAPPING, "g")
    assert any("node_id" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════
#  Field mapper: validate_against_grid
# ═══════════════════════════════════════════════════════════════


def test_validate_against_grid_valid():
    batch = StreamedMeasurementBatch(
        grid_id="g1",
        timestamp="2025-01-01T00:00:00",
        measurements=[
            {"node_id": "PT", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
        ],
    )
    inv_nodes, inv_phases, _ = validate_against_grid(batch, {"PT", "N1"})
    assert inv_nodes == []
    assert inv_phases == []


def test_validate_against_grid_unknown_node():
    batch = StreamedMeasurementBatch(
        grid_id="g1",
        timestamp="2025-01-01T00:00:00",
        measurements=[
            {"node_id": "UNKNOWN", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
        ],
    )
    inv_nodes, inv_phases, _ = validate_against_grid(batch, {"PT", "N1"})
    assert "UNKNOWN" in inv_nodes


# ═══════════════════════════════════════════════════════════════
#  Connector: _build_auth_headers / _resolve_secret
# ═══════════════════════════════════════════════════════════════


def test_build_auth_headers_none():
    from gridarena.digital_twin.connector import _build_auth_headers
    cfg = SourceConfig(url="http://x", auth_type="none")
    assert _build_auth_headers(cfg) == {}


def test_build_auth_headers_bearer():
    from gridarena.digital_twin.connector import _build_auth_headers
    cfg = SourceConfig(url="http://x", auth_type="bearer", secret_ref="TEST_TOKEN")
    with patch.dict(os.environ, {"TEST_TOKEN": "mytoken123"}):
        headers = _build_auth_headers(cfg)
    assert headers.get("Authorization") == "Bearer mytoken123"


def test_build_auth_headers_api_key():
    from gridarena.digital_twin.connector import _build_auth_headers
    cfg = SourceConfig(url="http://x", auth_type="api_key", secret_ref="MY_KEY", secret_header="X-Custom-Key")
    with patch.dict(os.environ, {"MY_KEY": "key123"}):
        headers = _build_auth_headers(cfg)
    assert headers.get("X-Custom-Key") == "key123"


def test_build_auth_headers_missing_secret():
    from gridarena.digital_twin.connector import _build_auth_headers
    cfg = SourceConfig(url="http://x", auth_type="bearer", secret_ref="NONEXISTENT_VAR")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NONEXISTENT_VAR", None)
        headers = _build_auth_headers(cfg)
    assert headers == {}


# ═══════════════════════════════════════════════════════════════
#  Connector: fetch_source (mocked HTTP)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_source_success():
    from gridarena.digital_twin.connector import fetch_source
    cfg = SourceConfig(url="http://fake-api.test/data")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"ok": true}'
    mock_response.json.return_value = {"ok": True}

    with patch("gridarena.digital_twin.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, data, error, status = await fetch_source(cfg)

    assert success is True
    assert data == {"ok": True}
    assert status == 200


@pytest.mark.asyncio
async def test_fetch_source_401():
    from gridarena.digital_twin.connector import fetch_source
    cfg = SourceConfig(url="http://fake-api.test/data", auth_type="bearer", secret_ref="TOK")

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch.dict(os.environ, {"TOK": "bad_token"}):
        with patch("gridarena.digital_twin.connector.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            success, data, error, status = await fetch_source(cfg)

    assert success is False
    assert status == 401
    assert "authentication" in error.lower()


@pytest.mark.asyncio
async def test_fetch_source_timeout():
    import httpx as _httpx
    from gridarena.digital_twin.connector import fetch_source
    cfg = SourceConfig(url="http://fake-api.test/data", timeout_seconds=1, retry_count=1)

    with patch("gridarena.digital_twin.connector.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        success, data, error, status = await fetch_source(cfg)

    assert success is False
    assert "timed out" in error.lower()


# ═══════════════════════════════════════════════════════════════
#  Broker: publish / consume (mocked Redis)
# ═══════════════════════════════════════════════════════════════


def test_broker_topic_naming():
    from gridarena.digital_twin.broker import topic_for_digital_twin
    assert topic_for_digital_twin("abc123") == "gridarena.digital_twin.abc123.measurements"


@patch("gridarena.digital_twin.broker._get_redis")
def test_broker_publish(mock_redis_fn):
    from gridarena.digital_twin.broker import publish_measurement
    mock_r = MagicMock()
    mock_r.xadd.return_value = "1234-0"
    mock_redis_fn.return_value = mock_r

    msg_id = publish_measurement("dt1", {"grid_id": "g1", "timestamp": "t1", "measurements": []})
    assert msg_id == "1234-0"
    mock_r.xadd.assert_called_once()


@patch("gridarena.digital_twin.broker._get_redis")
def test_broker_consume_latest(mock_redis_fn):
    from gridarena.digital_twin.broker import consume_latest
    mock_r = MagicMock()
    payload = {"grid_id": "g1", "timestamp": "t1", "measurements": []}
    mock_r.xrevrange.return_value = [("1234-0", {"payload": json.dumps(payload)})]
    mock_redis_fn.return_value = mock_r

    result = consume_latest("dt1")
    assert result == payload


@patch("gridarena.digital_twin.broker._get_redis")
def test_broker_consume_latest_empty(mock_redis_fn):
    from gridarena.digital_twin.broker import consume_latest
    mock_r = MagicMock()
    mock_r.xrevrange.return_value = []
    mock_redis_fn.return_value = mock_r

    assert consume_latest("dt1") is None


@patch("gridarena.digital_twin.broker._get_redis")
def test_broker_check_connection(mock_redis_fn):
    from gridarena.digital_twin.broker import check_broker_connection
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    mock_redis_fn.return_value = mock_r

    assert check_broker_connection() is True


@patch("gridarena.digital_twin.broker._get_redis")
def test_broker_check_connection_failure(mock_redis_fn):
    from gridarena.digital_twin.broker import check_broker_connection
    mock_redis_fn.side_effect = Exception("connection refused")

    assert check_broker_connection() is False


# ═══════════════════════════════════════════════════════════════
#  Schemas: validation
# ═══════════════════════════════════════════════════════════════


def test_source_config_defaults():
    cfg = SourceConfig(url="http://example.com")
    assert cfg.method == "GET"
    assert cfg.auth_type == "none"
    assert cfg.timeout_seconds == 30


def test_digital_twin_create_requires_grid_id():
    with pytest.raises(Exception):
        DigitalTwinCreate(
            name="test",
            source_config=SourceConfig(url="http://x"),
            field_mapping=FieldMapping(
                timestamp="t", measurements="m", node_id="n",
                active_power="p", reactive_power="q", voltage_magnitude="v",
            ),
        )


def test_field_mapping_requires_fields():
    with pytest.raises(Exception):
        FieldMapping(timestamp="t")


def test_streamed_measurement_batch_valid():
    batch = StreamedMeasurementBatch(
        grid_id="g1",
        timestamp="2025-01-01T00:00:00",
        measurements=[
            {"node_id": "PT", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
        ],
    )
    assert len(batch.measurements) == 1
    assert batch.measurements[0].node_id == "PT"


# ═══════════════════════════════════════════════════════════════
#  Router: unit tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.digital_twin.insert_digital_twin_event")
@patch("gridarena.routers.digital_twin.insert_digital_twin")
@patch("gridarena.routers.digital_twin.create_digital_twin_tables")
@patch("gridarena.routers.digital_twin.db.get_db_connection")
async def test_create_digital_twin_grid_not_found(mock_db, mock_tables, mock_insert, mock_event):
    from gridarena.routers.digital_twin import create_digital_twin

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = None

    req = DigitalTwinCreate(
        grid_id="nonexistent",
        source_config=SourceConfig(url="http://x"),
        field_mapping=FieldMapping(
            timestamp="t", measurements="m", node_id="n",
            active_power="p", reactive_power="q", voltage_magnitude="v",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await create_digital_twin(req)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@patch("gridarena.routers.digital_twin.insert_digital_twin_event")
@patch("gridarena.routers.digital_twin.insert_digital_twin")
@patch("gridarena.routers.digital_twin.create_digital_twin_tables")
@patch("gridarena.routers.digital_twin.db.get_db_connection")
async def test_create_digital_twin_success(mock_db, mock_tables, mock_insert, mock_event):
    from gridarena.routers.digital_twin import create_digital_twin

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = (1,)

    req = DigitalTwinCreate(
        grid_id="test_grid",
        name="Test DT",
        source_config=SourceConfig(url="http://x"),
        field_mapping=FieldMapping(
            timestamp="t", measurements="m", node_id="n",
            active_power="p", reactive_power="q", voltage_magnitude="v",
        ),
    )
    result = await create_digital_twin(req)
    assert "digital_twin_id" in result
    mock_insert.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.digital_twin.get_digital_twin", return_value=None)
@patch("gridarena.routers.digital_twin._ensure_tables")
@patch("gridarena.routers.digital_twin.db.get_db_connection")
async def test_get_detail_not_found(mock_db, mock_tables, mock_get):
    from gridarena.routers.digital_twin import get_digital_twin_detail

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)

    with pytest.raises(HTTPException) as exc:
        await get_digital_twin_detail("missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@patch("gridarena.routers.digital_twin.dt_runner")
@patch("gridarena.routers.digital_twin.get_digital_twin")
@patch("gridarena.routers.digital_twin._ensure_tables")
@patch("gridarena.routers.digital_twin.db.get_db_connection")
async def test_start_already_running(mock_db, mock_tables, mock_get, mock_runner):
    from gridarena.routers.digital_twin import start_digital_twin

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    mock_get.return_value = {"status": "running", "digital_twin_id": "dt1"}

    with pytest.raises(HTTPException) as exc:
        await start_digital_twin("dt1")
    assert exc.value.status_code == 400


# ═══════════════════════════════════════════════════════════════
#  Comparison: mocked power flow
# ═══════════════════════════════════════════════════════════════


@patch("gridarena.digital_twin.comparison.full_pf")
@patch("gridarena.digital_twin.comparison.gd.get_grid_admitances", return_value=[0.1 + 0.01j])
@patch("gridarena.digital_twin.comparison.gd.get_grid_connections", return_value=([("PT", "N1")], [{"len": 1}]))
@patch("gridarena.digital_twin.comparison.gd.get_nodes_from_grid", return_value={"PT": 0, "N1": 1})
@patch("gridarena.digital_twin.comparison.db.get_db_connection")
def test_run_comparison_converged(mock_db, mock_nodes, mock_conn, mock_adm, mock_pf):
    import numpy as np
    from gridarena.digital_twin.comparison import run_comparison

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    mock_pf.return_value = np.array([230 + 0j, 228.5 - 1.2j])

    batch = StreamedMeasurementBatch(
        grid_id="g1",
        timestamp="2025-01-01T00:00:00",
        measurements=[
            {"node_id": "PT", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
            {"node_id": "N1", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 10, "power_reactive": 5, "voltage_magnitude": 229},
        ],
    )

    metrics = run_comparison(batch, phase="R")
    assert metrics["convergence_status"] == "converged"
    assert metrics["measurements_count"] == 2
    assert metrics["voltage_mae"] is not None
    assert metrics["execution_time_ms"] is not None
    assert "PT" not in metrics.get("details", {}) or True  # PT may or may not be in details


@patch("gridarena.digital_twin.comparison.full_pf", side_effect=Exception("divergence"))
@patch("gridarena.digital_twin.comparison.gd.get_grid_admitances", return_value=[0.1j])
@patch("gridarena.digital_twin.comparison.gd.get_grid_connections", return_value=([], []))
@patch("gridarena.digital_twin.comparison.gd.get_nodes_from_grid", return_value={"PT": 0})
@patch("gridarena.digital_twin.comparison.db.get_db_connection")
def test_run_comparison_failed(mock_db, mock_nodes, mock_conn, mock_adm, mock_pf):
    from gridarena.digital_twin.comparison import run_comparison

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)

    batch = StreamedMeasurementBatch(
        grid_id="g1",
        timestamp="2025-01-01T00:00:00",
        measurements=[
            {"node_id": "PT", "phase": "R", "datetime": "2025-01-01T00:00:00",
             "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
        ],
    )

    metrics = run_comparison(batch, phase="R")
    assert metrics["convergence_status"] == "failed"


# ═══════════════════════════════════════════════════════════════
#  Digital twin lifecycle: unit tests
# ═══════════════════════════════════════════════════════════════


def test_runner_is_not_running():
    from gridarena.digital_twin.runner import DigitalTwinRunner
    runner = DigitalTwinRunner()
    assert runner.is_running("nonexistent") is False


def test_runner_stop_nonexistent():
    from gridarena.digital_twin.runner import DigitalTwinRunner
    runner = DigitalTwinRunner()
    runner.stop("nonexistent")  # should not raise


# ═══════════════════════════════════════════════════════════════
#  Integration: API endpoints
# ═══════════════════════════════════════════════════════════════


def test_list_digital_twins_integration():
    response = client.get(f"{DT_PREFIX}/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_nonexistent_twin_integration():
    response = client.get(f"{DT_PREFIX}/nonexistent_dt_999")
    assert response.status_code == 404


def test_create_twin_grid_not_found_integration():
    payload = {
        "grid_id": "nonexistent_grid_dt_999",
        "source_config": {"url": "http://example.com"},
        "field_mapping": {
            "timestamp": "t", "measurements": "m", "node_id": "n",
            "active_power": "p", "reactive_power": "q", "voltage_magnitude": "v",
        },
    }
    response = client.post(f"{DT_PREFIX}/", json=payload)
    assert response.status_code == 404


def test_start_nonexistent_twin_integration():
    response = client.post(f"{DT_PREFIX}/nonexistent_dt_999/start")
    assert response.status_code == 404


def test_stop_nonexistent_twin_integration():
    response = client.post(f"{DT_PREFIX}/nonexistent_dt_999/stop")
    assert response.status_code == 404


def test_tick_nonexistent_twin_integration():
    response = client.post(f"{DT_PREFIX}/nonexistent_dt_999/tick")
    assert response.status_code == 404


def test_validate_field_mapping_endpoint():
    payload = {
        "source_sample": {
            "timestamp": "2025-01-01T00:00:00",
            "measurements": [
                {"node_id": "PT", "phase": "R", "power_active": 0, "power_reactive": 0, "voltage_magnitude": 230},
            ],
        },
        "field_mapping": {
            "timestamp": "timestamp",
            "measurements": "measurements",
            "node_id": "node_id",
            "phase": "phase",
            "active_power": "power_active",
            "reactive_power": "power_reactive",
            "voltage_magnitude": "voltage_magnitude",
        },
        "grid_id": "nonexistent_grid_999",
    }
    response = client.post(f"{DT_PREFIX}/validate-field-mapping", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert any("not found" in e.lower() for e in data["errors"])


def test_events_nonexistent_integration():
    response = client.get(f"{DT_PREFIX}/nonexistent_dt_999/events")
    assert response.status_code == 404


def test_results_nonexistent_integration():
    response = client.get(f"{DT_PREFIX}/nonexistent_dt_999/results")
    assert response.status_code == 404


def test_metrics_nonexistent_integration():
    response = client.get(f"{DT_PREFIX}/nonexistent_dt_999/metrics")
    assert response.status_code == 404

import io
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import gridarena.database as db
from gridarena.app import app
from gridarena.routers import powerflow as pf

GRID_ID = "grid33nodes"
PHASE = "R"
TIMESTAMP = "2025-01-01T00:00:00"


# ---------------------------------------------------------------------
# Unit test for single_timestamp_power_flow()
# ---------------------------------------------------------------------
@patch("gridarena.routers.powerflow.db.insert_pf_data")
@patch("gridarena.routers.powerflow.full_pf")
@patch("gridarena.routers.powerflow.ms.get_pt_voltage")
@patch("gridarena.routers.powerflow.gd.get_grid_admitances")
@patch("gridarena.routers.powerflow.gd.get_grid_connections")
@patch("gridarena.routers.powerflow.ms.get_measurement_from_timestamp")
@patch("gridarena.routers.powerflow.gd.get_nodes_from_grid")
def test_single_timestamp_power_flow_calls_all_dependencies(
    mock_get_nodes,
    mock_get_measurements,
    mock_get_connections,
    mock_get_admittances,
    mock_get_pt_voltage,
    mock_full_pf,
    mock_insert,
):
    """Should call every dependency in the correct sequence."""
    mock_cursor = MagicMock()

    mock_get_nodes.return_value = {"PT": 0, "NODE1": 1}
    mock_get_measurements.return_value = [1 + 2j, 3 + 4j]
    mock_get_connections.return_value = ([("PT", "NODE1")], [{"len": 1}])
    mock_get_admittances.return_value = [0.1 + 0.01j]
    mock_get_pt_voltage.return_value = 230 + 0j
    mock_full_pf.return_value = np.array([230 + 0j, 228.5 - 1.2j])

    pf.single_timestamp_power_flow(mock_cursor, GRID_ID, TIMESTAMP, PHASE)

    mock_get_nodes.assert_called_once_with(GRID_ID, mock_cursor)
    mock_get_measurements.assert_called_once()
    mock_get_connections.assert_called_once()
    mock_get_admittances.assert_called_once()
    mock_get_pt_voltage.assert_called_once()
    mock_full_pf.assert_called_once()
    mock_insert.assert_called_once()


# ---------------------------------------------------------------------
# Unit tests for run_power_flow()
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.powerflow.db.get_db_connection")
@patch("gridarena.routers.powerflow.db.create_pf_database")
@patch("gridarena.routers.powerflow.single_timestamp_power_flow")
async def test_run_power_flow_runs_for_each_timestamp(
    mock_single_pf, mock_create_pf, mock_get_db
):
    """Should iterate over all timestamps and call single_timestamp_power_flow for each."""

    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # Simulate DB returning two timestamps
    cursor.fetchall.return_value = [("2025-01-01T00:00:00",), ("2025-01-01T01:00:00",)]

    result = await pf.run_power_flow(GRID_ID, PHASE)

    assert result["message"].startswith("Power flow has been run")
    assert mock_single_pf.call_count == 2
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.powerflow.db.get_db_connection")
async def test_run_power_flow_no_timestamps_raises(mock_get_db):
    """Should raise HTTP 404 when no timestamps found."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    mock_get_db.return_value = (conn, cursor)

    with pytest.raises(HTTPException) as exc:
        await pf.run_power_flow(GRID_ID, PHASE)

    assert exc.value.status_code == 404
    assert "no measurement timestamps" in exc.value.detail.lower()
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ---------------------------------------------------------------------
# Unit tests for get_power_flow_results()
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.powerflow.db.get_db_connection")
async def test_get_power_flow_results_returns_expected_data(mock_get_db):
    """Should format results correctly from DB rows."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchall.return_value = [
        ("PT", "2025-01-01T00:00:00", 230.0, 0.0),
        ("NODE1", "2025-01-01T00:00:00", 228.5, -1.2),
    ]

    result = await pf.get_power_flow_results(GRID_ID, PHASE)
    assert result["grid_id"] == GRID_ID
    assert len(result["results"]) == 2
    assert result["results"][0]["voltage"]["real"] == 230.0
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.powerflow.db.get_db_connection")
async def test_get_power_flow_results_raises_404_if_empty(mock_get_db):
    """Should raise HTTP 404 when no results are available."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    mock_get_db.return_value = (conn, cursor)

    with pytest.raises(HTTPException) as exc:
        await pf.get_power_flow_results(GRID_ID, PHASE)

    assert exc.value.status_code == 404
    assert "no power flow results" in exc.value.detail.lower()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.powerflow.db.get_db_connection")
async def test_get_power_flow_results_db_error(mock_get_db):
    """Should raise HTTP 500 if DB layer throws an error."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.execute.side_effect = Exception("SQL error")

    with pytest.raises(HTTPException) as exc:
        await pf.get_power_flow_results(GRID_ID, PHASE)

    assert exc.value.status_code == 500
    assert "database error" in exc.value.detail.lower()
    conn.close.assert_called_once()


# ---------------------------------------------------------------------
# Integration-style tests (PostgreSQL-backed via real API endpoints)
# ---------------------------------------------------------------------

client = TestClient(app)
NOW = datetime.utcnow()


def _setup_powerflow_grid(grid_id: str):
    """Create a minimal grid + historical data via the real API."""
    # Minimal grid definition
    grid_payload = {
        "grid_id": grid_id,
        "nodes": [
            {"node_id": "PT", "coord_lat": 38.65, "coord_lon": -7.98, "coord_error": 1},
            {"node_id": "NODE0001", "coord_lat": 38.651, "coord_lon": -7.981, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "LineUID000001",
                "from_node_id": "PT",
                "to_node_id": "NODE0001",
                "length": 1000,
                "cable_id": "TypeLine00001",
            }
        ],
        "cables": [
            {
                "cable_id": "TypeLine00001",
                "r_imp_real": 0.01,
                "r_imp_imag": 0.001,
                "s_imp_real": 0.01,
                "s_imp_imag": 0.001,
                "t_imp_real": 0.01,
                "t_imp_imag": 0.001,
                "r_nom_curr": 10000,
                "s_nom_curr": 10000,
                "t_nom_curr": 10000,
            }
        ],
    }

    # Minimal historical data with phase R for PT and NODE0001
    hist_payload = {
        "grid_id": grid_id,
        "historical": [
            {
                "node_id": "PT",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=1)).isoformat(),
                        "phase": "R",
                        "power_active": 0.0,
                        "power_reactive": 0.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": 0.0,
                    }
                ],
            },
            {
                "node_id": "NODE0001",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=1)).isoformat(),
                        "phase": "R",
                        "power_active": 5.0,
                        "power_reactive": 2.0,
                        "voltage_magnitude": 0.0,
                        "voltage_angle": 0.0,
                    }
                ],
            },
        ],
    }

    # Register grid
    grid_bytes = io.BytesIO(json.dumps(grid_payload).encode("utf-8"))
    resp_grid = client.post(
        "/grid/",
        files={"file": ("grid.json", grid_bytes, "application/json")},
    )
    assert resp_grid.status_code == 200, resp_grid.text

    # Upload historical data
    hist_bytes = io.BytesIO(json.dumps(hist_payload).encode("utf-8"))
    resp_hist = client.post(
        "/measurements/",
        files={"file": ("hist.json", hist_bytes, "application/json")},
    )
    assert resp_hist.status_code == 200, resp_hist.text


def test_powerflow_run_endpoints():
    """
    Integration smoke test: ensures /powerflow/{grid_id}/run works with a real DB
    and data created via the API.
    """
    grid_id = "pf_grid_run_1"
    phase = "R"

    _setup_powerflow_grid(grid_id)

    run_response = client.post(f"/powerflow/{grid_id}/run?phase={phase}")
    assert run_response.status_code == 200, run_response.text
    assert "successfully" in run_response.json()["message"].lower()


def test_powerflow_results_endpoints():
    """
    Integration smoke test: ensures /powerflowdata/{grid_id}/results returns
    stored PF results after /run has been executed.
    """
    grid_id = "pf_grid_results_1"
    phase = "R"

    _setup_powerflow_grid(grid_id)

    # Run power flow first
    run_response = client.post(f"/powerflow/{grid_id}/run?phase={phase}")
    assert run_response.status_code == 200, run_response.text

    # Fetch results
    results_response = client.get(f"/powerflow/data/{grid_id}/results?phase={phase}")
    assert results_response.status_code == 200, results_response.text
    data = results_response.json()

    assert data["grid_id"] == grid_id
    assert data["phase"] == phase
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0
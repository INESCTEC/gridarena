import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.digital_twin.scenario_runner import _apply_connection_changes, _compute_admittances

client = TestClient(app)
SC_PREFIX = "/offline-scenarios"


# ═══════════════════════════════════════════════════════════════
#  Unit: _apply_connection_changes
# ═══════════════════════════════════════════════════════════════


BASE_CONNECTIONS = [
    {"connection_id": "C01", "from_node_id": "PT", "to_node_id": "N1", "cable_id": "CBL1", "length": 35},
    {"connection_id": "C02", "from_node_id": "N1", "to_node_id": "N2", "cable_id": "CBL1", "length": 42},
    {"connection_id": "C03", "from_node_id": "N2", "to_node_id": "N3", "cable_id": "CBL2", "length": 38},
]


def test_apply_no_changes():
    result = _apply_connection_changes(BASE_CONNECTIONS, [])
    assert len(result) == 3


def test_apply_remove():
    result = _apply_connection_changes(BASE_CONNECTIONS, [{"action": "remove", "connection_id": "C02"}])
    ids = [c["connection_id"] for c in result]
    assert "C02" not in ids
    assert len(result) == 2


def test_apply_disable():
    result = _apply_connection_changes(BASE_CONNECTIONS, [{"action": "disable", "connection_id": "C03"}])
    c03 = next(c for c in result if c["connection_id"] == "C03")
    assert c03.get("disabled") is True


def test_apply_enable():
    changes = [
        {"action": "disable", "connection_id": "C01"},
        {"action": "enable", "connection_id": "C01"},
    ]
    result = _apply_connection_changes(BASE_CONNECTIONS, changes)
    c01 = next(c for c in result if c["connection_id"] == "C01")
    assert c01.get("disabled") is not True


def test_apply_add():
    change = {
        "action": "add", "connection_id": "C_NEW",
        "from_node_id": "N1", "to_node_id": "N3", "cable_id": "CBL2", "length": 20,
    }
    result = _apply_connection_changes(BASE_CONNECTIONS, [change])
    ids = [c["connection_id"] for c in result]
    assert "C_NEW" in ids
    assert len(result) == 4
    new_conn = next(c for c in result if c["connection_id"] == "C_NEW")
    assert new_conn["from_node_id"] == "N1"
    assert new_conn["length"] == 20


def test_apply_update():
    change = {"action": "update", "connection_id": "C02", "length": 100}
    result = _apply_connection_changes(BASE_CONNECTIONS, [change])
    c02 = next(c for c in result if c["connection_id"] == "C02")
    assert c02["length"] == 100
    assert c02["from_node_id"] == "N1"


def test_apply_unknown_action():
    result = _apply_connection_changes(BASE_CONNECTIONS, [{"action": "unknown", "connection_id": "C01"}])
    assert len(result) == 3


def test_apply_remove_nonexistent():
    result = _apply_connection_changes(BASE_CONNECTIONS, [{"action": "remove", "connection_id": "NOPE"}])
    assert len(result) == 3


# ═══════════════════════════════════════════════════════════════
#  Unit: _compute_admittances
# ═══════════════════════════════════════════════════════════════


def test_compute_admittances_basic():
    cables = {"CBL1": {"r_imp_real": 0.32, "r_imp_imag": 0.078}}
    conn_data = [("CBL1", 100.0)]
    adm = _compute_admittances(cables, conn_data)
    assert len(adm) == 1
    assert adm[0][0] != 0


def test_compute_admittances_missing_cable():
    adm = _compute_admittances({}, [("MISSING", 50.0)])
    assert len(adm) == 1


def test_compute_admittances_zero_length():
    cables = {"CBL1": {"r_imp_real": 0.32, "r_imp_imag": 0.078}}
    adm = _compute_admittances(cables, [("CBL1", 0)])
    assert len(adm) == 1


# ═══════════════════════════════════════════════════════════════
#  Router: validation
# ═══════════════════════════════════════════════════════════════


def test_list_scenarios_integration():
    response = client.get(f"{SC_PREFIX}/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_nonexistent_scenario():
    response = client.get(f"{SC_PREFIX}/nonexistent_999")
    assert response.status_code == 404


def test_delete_nonexistent_scenario():
    response = client.delete(f"{SC_PREFIX}/nonexistent_999")
    assert response.status_code == 404


def test_run_pf_nonexistent_scenario():
    response = client.post(f"{SC_PREFIX}/nonexistent_999/run-powerflow-timeseries")
    assert response.status_code == 404


def test_results_nonexistent_scenario():
    response = client.get(f"{SC_PREFIX}/nonexistent_999/results")
    assert response.status_code == 404


def test_violations_nonexistent_scenario():
    response = client.get(f"{SC_PREFIX}/nonexistent_999/violations")
    assert response.status_code == 404


def test_voltage_ts_nonexistent_scenario():
    response = client.get(f"{SC_PREFIX}/nonexistent_999/voltage-timeseries")
    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Router: connection changes validation
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.offline_scenario.get_offline_scenario")
@patch("gridarena.routers.offline_scenario.create_offline_scenario_tables")
@patch("gridarena.routers.offline_scenario.db.get_db_connection")
async def test_connection_change_invalid_node(mock_db, mock_tables, mock_get):
    from gridarena.routers.offline_scenario import set_connection_changes
    from gridarena.schemas.offline_scenario import ConnectionChange

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    mock_get.return_value = {
        "simulation_status": "pending",
        "grid_snapshot": {
            "nodes": [{"node_id": "PT"}, {"node_id": "N1"}],
            "cables": [{"cable_id": "CBL1"}],
            "connections": [{"connection_id": "C01"}],
        },
    }

    changes = [ConnectionChange(action="add", connection_id="NEW", from_node_id="GHOST", to_node_id="N1", cable_id="CBL1")]
    with pytest.raises(HTTPException) as exc:
        await set_connection_changes("sc1", changes)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
@patch("gridarena.routers.offline_scenario.get_offline_scenario")
@patch("gridarena.routers.offline_scenario.create_offline_scenario_tables")
@patch("gridarena.routers.offline_scenario.db.get_db_connection")
async def test_connection_change_unknown_action(mock_db, mock_tables, mock_get):
    from gridarena.routers.offline_scenario import set_connection_changes
    from gridarena.schemas.offline_scenario import ConnectionChange

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    mock_get.return_value = {
        "simulation_status": "pending",
        "grid_snapshot": {"nodes": [], "cables": [], "connections": []},
    }

    changes = [ConnectionChange(action="explode", connection_id="C01")]
    with pytest.raises(HTTPException) as exc:
        await set_connection_changes("sc1", changes)
    assert exc.value.status_code == 422


# ═══════════════════════════════════════════════════════════════
#  Router: power limits validation
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.offline_scenario.get_offline_scenario")
@patch("gridarena.routers.offline_scenario.create_offline_scenario_tables")
@patch("gridarena.routers.offline_scenario.db.get_db_connection")
async def test_power_limit_invalid_node(mock_db, mock_tables, mock_get):
    from gridarena.routers.offline_scenario import set_power_limits
    from gridarena.schemas.offline_scenario import PowerLimitsUpdate

    conn = MagicMock()
    cursor = MagicMock()
    mock_db.return_value = (conn, cursor)
    mock_get.return_value = {
        "simulation_status": "pending",
        "grid_snapshot": {"nodes": [{"node_id": "N1"}]},
    }

    body = PowerLimitsUpdate(power_limits={"GHOST": 10.0})
    with pytest.raises(HTTPException) as exc:
        await set_power_limits("sc1", body)
    assert exc.value.status_code == 422


# ═══════════════════════════════════════════════════════════════
#  CRUD: violations
# ═══════════════════════════════════════════════════════════════


def test_violations_detection():
    from gridarena.database.offline_scenario_crud import get_scenario_violations

    cursor = MagicMock()
    cursor.execute = MagicMock()
    cursor.fetchall.return_value = [
        (1, "sc1", "2025-01-01T00:00:00", "converged",
         {"N1": {"simulated_voltage": 260.0}, "N2": {"simulated_voltage": 225.0}},
         10.0, None),
    ]

    violations = get_scenario_violations("sc1", cursor, voltage_ref=230.0, threshold=0.10)
    assert len(violations) == 1
    assert violations[0]["node_id"] == "N1"
    assert violations[0]["type"] == "overvoltage"


def test_no_violations():
    from gridarena.database.offline_scenario_crud import get_scenario_violations

    cursor = MagicMock()
    cursor.execute = MagicMock()
    cursor.fetchall.return_value = [
        (1, "sc1", "2025-01-01T00:00:00", "converged",
         {"N1": {"simulated_voltage": 229.0}, "N2": {"simulated_voltage": 231.0}},
         10.0, None),
    ]

    violations = get_scenario_violations("sc1", cursor, voltage_ref=230.0, threshold=0.10)
    assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════
#  Scenario runner: source DT not modified
# ═══════════════════════════════════════════════════════════════


def test_apply_changes_does_not_mutate_original():
    original = [
        {"connection_id": "C01", "from_node_id": "PT", "to_node_id": "N1", "cable_id": "CBL1", "length": 35},
    ]
    import copy
    original_copy = copy.deepcopy(original)

    _apply_connection_changes(original, [{"action": "remove", "connection_id": "C01"}])
    assert original == original_copy

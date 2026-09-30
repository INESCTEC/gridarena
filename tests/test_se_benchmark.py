import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
import gridarena.routers.state_estimation_benchmark as se_router

USER_ID = "user_123"
GRID_ID = "grid_001"
ESTIMATION_ID = "est_task_01"


# ===============================================================
#  GET /training-state-data
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_grid_masks")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_all_node_masks")
async def test_get_training_state_data_success(mock_node_masks, mock_grid_masks, mock_get_db):
    """Should return structured masked training data."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    row = (
        GRID_ID, "masked_gid_1", "NODE1", "masked_nid_1",
        "2025-01-01T00:00:00", "R", 10.0, 5.0, 230.0, 0.0,
    )
    # fetchall for GridUsage query, fetchmany for batched measurement read
    cursor.fetchall.return_value = [(GRID_ID,)]
    cursor.fetchmany.side_effect = [[row], []]

    result = await se_router.get_training_state_data()

    assert "grids" in result
    assert "masked_gid_1" in result["grids"]
    assert "masked_nid_1" in result["grids"]["masked_gid_1"]
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_grid_masks")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_all_node_masks")
async def test_training_state_data_deterministic(mock_node_masks, mock_grid_masks, mock_get_db):
    """Same difficulty should produce identical noise across calls."""
    row = (GRID_ID, "masked_gid_1", "NODE1", "masked_nid_1",
           "2025-01-01T00:00:00", "R", 10.0, 5.0, 230.0, 0.1)

    def setup():
        conn = MagicMock()
        cursor = MagicMock()
        mock_get_db.return_value = (conn, cursor)
        cursor.fetchall.return_value = [row]
        cursor.fetchmany.side_effect = [[row], []]

    setup()
    r1 = await se_router.get_training_state_data(noise_difficulty="easy")
    setup()
    r2 = await se_router.get_training_state_data(noise_difficulty="easy")

    m1 = r1["grids"]["masked_gid_1"]["masked_nid_1"][0]
    m2 = r2["grids"]["masked_gid_1"]["masked_nid_1"][0]
    assert m1["power_active"] == m2["power_active"]
    assert m1["voltage_magnitude"] == m2["voltage_magnitude"]


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_grid_masks")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_all_node_masks")
async def test_get_training_state_data_db_error(mock_node_masks, mock_grid_masks, mock_get_db):
    """Should raise HTTP 500 if DB fails."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL fail")

    with pytest.raises(HTTPException) as exc:
        await se_router.get_training_state_data()
    assert exc.value.status_code == 500
    assert "SQL fail" in exc.value.detail
    conn.close.assert_called_once()


# ===============================================================
#  GET /state-data
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_grid_masks")
@patch("gridarena.routers.state_estimation_benchmark.se.ensure_all_node_masks")
@patch("gridarena.routers.state_estimation_benchmark.se.get_random_grid")
@patch("gridarena.routers.state_estimation_benchmark.se.get_masked_grid")
@patch("gridarena.routers.state_estimation_benchmark.se.random_timestamp_for_grid")
@patch("gridarena.routers.state_estimation_benchmark.se.create_estimation_task")
@patch("gridarena.routers.state_estimation_benchmark.se.get_actual_state")
async def test_get_state_estimation_input_success(
    mock_get_actual,
    mock_create_task,
    mock_rand_time,
    mock_get_masked,
    mock_get_rand,
    mock_node_masks,
    mock_grid_masks,
    mock_get_db,
):
    """Should retrieve state estimation task input."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_rand.return_value = GRID_ID
    mock_get_masked.return_value = "masked_grid_1"
    mock_rand_time.return_value = "2025-01-01T00:00:00"
    mock_create_task.return_value = ESTIMATION_ID
    mock_get_actual.return_value = ({"known_nodes": {}, "unknown_nodes": []}, {"data": []})

    result = await se_router.get_state_estimation_input(USER_ID)

    assert result["Masked GridID"] == "masked_grid_1"
    assert result["Estimation Task ID"] == ESTIMATION_ID
    assert "Current State" in result
    assert "Measurement Data" in result
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
async def test_get_state_estimation_input_db_error(mock_get_db):
    """Should raise HTTP 500 if DB throws."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("DB failure")

    with pytest.raises(HTTPException) as exc:
        await se_router.get_state_estimation_input(USER_ID)
    assert exc.value.status_code == 500
    assert "DB failure" in exc.value.detail
    conn.close.assert_called_once()


# ===============================================================
#  POST /submit-estimates
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_grid_id_from_mask")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_node_id_from_mask")
@patch("gridarena.routers.state_estimation_benchmark.se.insert_state_estimation")
async def test_submit_state_estimates_success(
    mock_insert,
    mock_resolve_node,
    mock_resolve_grid,
    mock_get_db,
):
    """Should insert estimates successfully."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # grid eligibility check returns a row, estimation_id check returns a row
    cursor.fetchone.side_effect = [(1,), (1,)]

    submission = MagicMock()
    submission.grid_id = "masked_grid_1"
    submission.user_id = USER_ID
    submission.estimation_id = ESTIMATION_ID
    submission.estimates = [MagicMock(masked_node_id="masked_node_1")]

    mock_resolve_grid.return_value = GRID_ID
    mock_resolve_node.return_value = ("NODE1", "R")

    result = await se_router.submit_state_estimates(submission)

    mock_resolve_grid.assert_called_once()
    mock_resolve_node.assert_called_once()
    mock_insert.assert_called_once()
    conn.commit.assert_called_once()
    conn.close.assert_called_once()
    assert result["status"] == "submitted"
    assert result["accepted"] == 1


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_grid_id_from_mask")
async def test_submit_state_estimates_db_error(
    mock_resolve_grid,
    mock_get_db,
):
    """Should raise HTTP 500 on DB error."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_resolve_grid.side_effect = Exception("SQL failure")

    submission = MagicMock()
    submission.grid_id = "masked_grid_1"
    submission.user_id = USER_ID
    submission.estimation_id = ESTIMATION_ID
    submission.estimates = []

    with pytest.raises(HTTPException) as exc:
        await se_router.submit_state_estimates(submission)
    assert exc.value.status_code == 500
    assert "SQL failure" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_grid_id_from_mask")
async def test_submit_state_estimates_invalid_grid(
    mock_resolve_grid,
    mock_get_db,
):
    """Should raise HTTP 422 for unknown masked grid ID."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_resolve_grid.side_effect = ValueError("not found")

    submission = MagicMock()
    submission.grid_id = "bad_mask"
    submission.user_id = USER_ID
    submission.estimation_id = ESTIMATION_ID
    submission.estimates = []

    with pytest.raises(HTTPException) as exc:
        await se_router.submit_state_estimates(submission)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_grid_id_from_mask")
async def test_submit_state_estimates_invalid_task(
    mock_resolve_grid,
    mock_get_db,
):
    """Should raise HTTP 422 for nonexistent estimation task."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_resolve_grid.return_value = GRID_ID
    # grid eligibility check returns row, estimation_id check returns None
    cursor.fetchone.side_effect = [(1,), None]

    submission = MagicMock()
    submission.grid_id = "masked_grid_1"
    submission.user_id = USER_ID
    submission.estimation_id = "nonexistent_task"
    submission.estimates = []

    with pytest.raises(HTTPException) as exc:
        await se_router.submit_state_estimates(submission)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_grid_id_from_mask")
@patch("gridarena.routers.state_estimation_benchmark.se.resolve_node_id_from_mask")
async def test_submit_state_estimates_invalid_node(
    mock_resolve_node,
    mock_resolve_grid,
    mock_get_db,
):
    """Should raise HTTP 422 for unknown masked node ID."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_resolve_grid.return_value = GRID_ID
    cursor.fetchone.side_effect = [(1,), (1,)]
    mock_resolve_node.side_effect = ValueError("not found")

    submission = MagicMock()
    submission.grid_id = "masked_grid_1"
    submission.user_id = USER_ID
    submission.estimation_id = ESTIMATION_ID
    submission.estimates = [MagicMock(masked_node_id="bad_node")]

    with pytest.raises(HTTPException) as exc:
        await se_router.submit_state_estimates(submission)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


# ===============================================================
#  GET /state-score
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.get_predicted_voltages")
@patch("gridarena.routers.state_estimation_benchmark.se.get_real_voltages")
@patch("gridarena.routers.state_estimation_benchmark.se.get_state_estimation_score")
async def test_get_state_estimation_score_success(
    mock_score,
    mock_real,
    mock_pred,
    mock_get_db,
):
    """Should compute state estimation score correctly."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_pred.return_value = ([1.0], [0.0])
    mock_real.return_value = ([1.0], [0.0])
    mock_score.return_value = 0.000123

    result = await se_router.get_state_estimation_score(USER_ID, ESTIMATION_ID)
    assert result["score"] == round(0.000123, 6)
    assert result["user_id"] == USER_ID
    assert result["estimation_id"] == ESTIMATION_ID
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.state_estimation_benchmark.db.get_db_connection")
@patch("gridarena.routers.state_estimation_benchmark.se.get_predicted_voltages")
async def test_get_state_estimation_score_db_error(mock_get_pred, mock_get_db):
    """Should raise HTTP 500 if DB fails and call rollback."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_pred.side_effect = Exception("SQL problem")

    with pytest.raises(HTTPException) as exc:
        await se_router.get_state_estimation_score(USER_ID, ESTIMATION_ID)
    assert exc.value.status_code == 500
    assert "SQL problem" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# Integration-style tests (real FastAPI + backing DB via app)
# ----------------------------------------------------------------------------------------

client = TestClient(app)
BENCH_PREFIX = "/state_estimation_benchmark"


def _setup_state_grid(grid_id: str):
    """Create a minimal grid + historical data via public API endpoints."""
    grid_payload = {
        "grid_id": grid_id,
        "nodes": [
            {"node_id": "PT", "coord_lat": 38.65, "coord_lon": -7.98, "coord_error": 1},
            {"node_id": "NODE1", "coord_lat": 38.651, "coord_lon": -7.981, "coord_error": 1},
            {"node_id": "NODE2", "coord_lat": 38.652, "coord_lon": -7.982, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "L1",
                "from_node_id": "PT",
                "to_node_id": "NODE1",
                "length": 1000,
                "cable_id": "TypeLine00001",
            },
            {
                "connection_id": "L2",
                "from_node_id": "NODE1",
                "to_node_id": "NODE2",
                "length": 800,
                "cable_id": "TypeLine00001",
            },
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

    now = datetime.utcnow().isoformat()

    hist_payload = {
        "grid_id": grid_id,
        "historical": [
            {
                "node_id": "PT",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "R",
                        "power_active": 0.0,
                        "power_reactive": 0.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": 0.0,
                    }
                ],
            },
            {
                "node_id": "NODE1",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "R",
                        "power_active": 10.0,
                        "power_reactive": 5.0,
                        "voltage_magnitude": 229.5,
                        "voltage_angle": -1.0,
                    }
                ],
            },
            {
                "node_id": "NODE2",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "R",
                        "power_active": 8.0,
                        "power_reactive": 3.5,
                        "voltage_magnitude": 229.0,
                        "voltage_angle": -2.0,
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


# -----------------------------------------------------------
# GET /training-state-data
# -----------------------------------------------------------
def test_get_training_state_data_integration():
    """Should return structured masked training data."""
    grid_id = "se_grid_train_pg1"
    _setup_state_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/training-state-data")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "grids" in data
    assert isinstance(data["grids"], dict)


# -----------------------------------------------------------
# GET /state-data
# -----------------------------------------------------------
def test_get_state_estimation_input_integration():
    """Should generate a new estimation task and state input."""
    grid_id = "se_grid_state_pg1"
    _setup_state_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/state-data?user_id={USER_ID}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "Masked GridID" in data
    assert "Estimation Task ID" in data
    assert "Current State" in data
    assert "Measurement Data" in data


# -----------------------------------------------------------
# POST /submit-estimates
# -----------------------------------------------------------
def test_submit_state_estimates_integration():
    """Should submit estimated node states."""
    grid_id = "se_grid_submit_pg1"
    _setup_state_grid(grid_id)

    # First, obtain an estimation task and masked IDs
    state_resp = client.get(f"{BENCH_PREFIX}/state-data?user_id={USER_ID}")
    assert state_resp.status_code == 200, state_resp.text
    state = state_resp.json()

    masked_grid = state["Masked GridID"]
    est_id = state["Estimation Task ID"]
    current_state = state.get("Current State", {})
    known_nodes = current_state.get("known_nodes", {})
    unknown_nodes = current_state.get("unknown_nodes", [])

    # Prefer estimating unknown nodes; if none, fall back to known nodes;
    # if still none, fall back to measurement data keys.
    nodes_to_estimate = unknown_nodes or list(known_nodes.keys())
    if not nodes_to_estimate:
        meas_data = state.get("Measurement Data", {})
        if isinstance(meas_data, dict):
            nodes_to_estimate = list(meas_data.keys())

    assert nodes_to_estimate, "No nodes available to estimate in current state or measurement data."

    # Derive a timestamp from known nodes or measurement data if available
    timestamp = None
    if known_nodes:
        first_entry = next(iter(known_nodes.values()))
        if isinstance(first_entry, dict):
            timestamp = first_entry.get("datetime") or first_entry.get("timestamp")

    if not timestamp:
        meas_data = state.get("Measurement Data", {})
        if isinstance(meas_data, dict) and meas_data:
            first_series = next(iter(meas_data.values()))
            if first_series:
                timestamp = first_series[0].get("datetime") or first_series[0].get("timestamp")

    if not timestamp:
        timestamp = datetime.utcnow().isoformat()

    payload = {
        "user_id": USER_ID,
        "estimation_id": est_id,
        "timestamp": timestamp,
        "grid_id": masked_grid,
        "estimates": [
            {
                "masked_node_id": node_id,
                "voltage_magnitude": 230.0,
                "voltage_angle": 0.0,
            }
            for node_id in nodes_to_estimate
        ],
    }

    response = client.post(
        f"{BENCH_PREFIX}/submit-estimates",
        json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted"


# -----------------------------------------------------------
# GET /state-score
# -----------------------------------------------------------
def test_get_state_estimation_score_integration():
    """Should compute a finite score successfully from predicted/real voltages."""
    grid_id = "se_grid_score_pg1"
    _setup_state_grid(grid_id)

    # Obtain estimation task and masked info
    state_resp = client.get(f"{BENCH_PREFIX}/state-data?user_id={USER_ID}")
    assert state_resp.status_code == 200, state_resp.text
    state = state_resp.json()

    masked_grid = state["Masked GridID"]
    est_id = state["Estimation Task ID"]
    current_state = state.get("Current State", {})
    known_nodes = current_state.get("known_nodes", {})
    unknown_nodes = current_state.get("unknown_nodes", [])

    # For scoring we should only estimate unknown nodes, to match the benchmark contract.
    nodes_to_estimate = list(unknown_nodes)
    if not nodes_to_estimate:
        pytest.skip("No unknown nodes available to estimate for scoring in this task.")

    # Try to infer the estimation timestamp
    timestamp = None
    if known_nodes:
        first_entry = next(iter(known_nodes.values()))
        if isinstance(first_entry, dict):
            timestamp = first_entry.get("datetime") or first_entry.get("timestamp")

    if not timestamp:
        meas_data = state.get("Measurement Data", {})
        if isinstance(meas_data, dict) and meas_data:
            first_series = next(iter(meas_data.values()))
            if first_series:
                timestamp = first_series[0].get("datetime") or first_series[0].get("timestamp")

    if not timestamp:
        timestamp = datetime.utcnow().isoformat()

    estimates_payload = {
        "user_id": USER_ID,
        "estimation_id": est_id,
        "timestamp": timestamp,
        "grid_id": masked_grid,
        "estimates": [
            {
                "masked_node_id": node_id,
                "voltage_magnitude": 230.0,
                "voltage_angle": 0.0,
            }
            for node_id in nodes_to_estimate
        ],
    }

    submit_resp = client.post(f"{BENCH_PREFIX}/submit-estimates", json=estimates_payload)
    assert submit_resp.status_code == 200, submit_resp.text

    score_resp = client.get(
        f"{BENCH_PREFIX}/state-score?user_id={USER_ID}&estimation_id={est_id}"
    )
    assert score_resp.status_code == 200, score_resp.text

    data = score_resp.json()
    assert "score" in data
    # Check it's a finite, non-negative number
    assert not (data["score"] != data["score"]), f"Score is NaN: {data}"
    assert data["score"] >= 0.0

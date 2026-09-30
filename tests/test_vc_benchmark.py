import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import gridarena.routers.voltage_control_benchmark as vc_router
from gridarena.app import app
import gridarena.database as db

GRID_ID = "grid_001"
USER_ID = "user_001"
VOLTAGE_LIMIT = 230

client = TestClient(app)
BENCH_PREFIX = "/voltage_control_benchmark"


# -------------------------------------------------
# Training scenarios (Overvoltages / Undervoltages)
# -------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
@patch("gridarena.routers.voltage_control_benchmark.vc.get_all_measurements_over")
@patch("gridarena.routers.voltage_control_benchmark.vc.get_all_measurements_under")
async def test_get_training_scenarios_success(
    mock_under, mock_over, mock_get_db
):
    """Should fetch measurements and organize data correctly."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_over.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10, 5, 240, 0.1),
    ]
    cursor.fetchall.return_value = [
        ("NODE1", "R", 230, 9.8, 4.9, "2025-01-01T00:00:00")
    ]

    result = await vc_router.get_training_voltage_control_data(
        VOLTAGE_LIMIT, Scenario="Overvoltages"
    )
    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "measurements" in result["grids"][GRID_ID]["2025-01-01T00:00:00"]
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
@patch("gridarena.routers.voltage_control_benchmark.vc.get_all_measurements_over")
async def test_get_training_scenarios_db_error(mock_get_meas, mock_get_db):
    """Should raise HTTP 500 on DB error and call rollback."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)
    mock_get_meas.side_effect = Exception("SQL fail")

    with pytest.raises(HTTPException) as exc:
        await vc_router.get_training_voltage_control_data(
            VOLTAGE_LIMIT, Scenario="Overvoltages"
        )
    assert exc.value.status_code == 500
    assert "SQL fail" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# -------------------------------------------------
# Voltage control data (anonymised)
# -------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
@patch("gridarena.routers.voltage_control_benchmark.vc.get_all_measurements_over")
@patch("gridarena.routers.voltage_control_benchmark.vc.build_load_voltage_timestamp_keys")
async def test_get_voltage_control_data_success(
    mock_build, mock_get_meas, mock_get_db
):
    """Should anonymise and organize voltage data properly."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    measurements = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10, 5, 240, 0.1)
    ]
    mock_get_meas.return_value = measurements
    mock_build.return_value = {(GRID_ID, "2025-01-01T00:00:00"): "anon_key_1"}

    result = await vc_router.get_voltage_control_data(VOLTAGE_LIMIT)
    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "anon_key_1" in result["grids"][GRID_ID]
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_get_voltage_control_data_db_error(mock_get_db):
    """Should raise HTTP 500 if DB query fails."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL fail")

    with pytest.raises(HTTPException) as exc:
        await vc_router.get_voltage_control_data(VOLTAGE_LIMIT)
    assert exc.value.status_code == 500
    assert "SQL fail" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# -------------------------------------------------
# Submit results
# -------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_submit_voltage_control_guesses_success(mock_get_db):
    """Should insert voltage control guesses correctly."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # grid exists check returns row, anon key validation returns valid key
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [("anon1",)]

    node_solution = MagicMock()
    node_solution.node_id = "NODE1"
    node_solution.phase = "R"
    node_solution.corrected_voltage = 230
    node_solution.adjusted_power_active = 10
    node_solution.adjusted_power_reactive = 5

    vc_guess = MagicMock()
    vc_guess.guess_id = USER_ID
    vc_guess.grid_id = GRID_ID
    vc_guess.guesses = {"anon1": [node_solution]}

    result = await vc_router.submit_voltage_control_guesses(vc_guess)
    assert result["status"] == "submitted"
    assert result["accepted"] == 1
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_submit_voltage_control_guesses_db_error(mock_get_db):
    """Should raise HTTP 500 if DB fails."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL failure")

    vc_guess = MagicMock()
    vc_guess.guess_id = USER_ID
    vc_guess.grid_id = GRID_ID
    vc_guess.guesses = {}

    with pytest.raises(HTTPException) as exc:
        await vc_router.submit_voltage_control_guesses(vc_guess)
    assert exc.value.status_code == 500
    assert "SQL failure" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_submit_voltage_control_guesses_invalid_grid(mock_get_db):
    """Should raise HTTP 422 for nonexistent grid."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchone.return_value = None

    vc_guess = MagicMock()
    vc_guess.guess_id = USER_ID
    vc_guess.grid_id = "nonexistent_grid"
    vc_guess.guesses = {"anon1": []}

    with pytest.raises(HTTPException) as exc:
        await vc_router.submit_voltage_control_guesses(vc_guess)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_submit_voltage_control_guesses_invalid_keys(mock_get_db):
    """Should raise HTTP 422 for unknown anonymised keys."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # grid exists, but anon key validation returns empty
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = []

    vc_guess = MagicMock()
    vc_guess.guess_id = USER_ID
    vc_guess.grid_id = GRID_ID
    vc_guess.guesses = {"bad_key": []}

    with pytest.raises(HTTPException) as exc:
        await vc_router.submit_voltage_control_guesses(vc_guess)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


# -------------------------------------------------
# Score
# -------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_get_score_computes_accuracy(mock_get_db):
    """Should compute voltage correction scores correctly."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # First fetchall: user guesses; second fetchall: measurements
    cursor.fetchall.side_effect = [
        [
            (
                "anon1",
                '{"NODE1": {"phase": "R", "corrected_voltage": 230}}',
                '{"NODE1": {"adjusted_power_active": 10, "adjusted_power_reactive": 5}}',
                "2025-01-01T00:00:00",
            )
        ],
        [("NODE1", "R", 240, 10, 5)],
    ]

    result = await vc_router.get_score(USER_ID, grid_id=GRID_ID)
    assert result["grid_id"] == GRID_ID
    assert "overall_score" in result
    assert isinstance(result["overall_score"], float)
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.voltage_control_benchmark.db.get_db_connection")
async def test_get_score_db_error(mock_get_db):
    """Should raise HTTP 500 on DB error and call rollback."""
    conn, cursor = MagicMock(), MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL failure")

    with pytest.raises(HTTPException) as exc:
        await vc_router.get_score(USER_ID, grid_id=GRID_ID)
    assert exc.value.status_code == 500
    assert "SQL failure" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# Integration-style tests using the real app + DB
# ----------------------------------------------------------------------------------------


def _setup_voltage_grid(grid_id: str, overvoltage: bool = True) -> str:
    """
    Register a grid and upload historical data via the public API.
    Returns the timestamp used for the measurements.
    """
    grid_payload = {
        "grid_id": grid_id,
        "nodes": [
            {"node_id": "PT", "coord_lat": 38.65, "coord_lon": -7.98, "coord_error": 1},
            {
                "node_id": "NODE1",
                "coord_lat": 38.651,
                "coord_lon": -7.981,
                "coord_error": 1,
            },
        ],
        "connections": [
            {
                "connection_id": "L1",
                "from_node_id": "PT",
                "to_node_id": "NODE1",
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

    now = datetime.utcnow().isoformat()

    voltage_mag = 240.0 if overvoltage else 210.0

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
                        "voltage_magnitude": voltage_mag,
                        "voltage_angle": 0.0,
                    }
                ],
            },
        ],
    }

    grid_bytes = io.BytesIO(json.dumps(grid_payload).encode("utf-8"))
    resp_grid = client.post(
        "/grid/",
        files={"file": ("grid.json", grid_bytes, "application/json")},
    )
    assert resp_grid.status_code == 200, resp_grid.text

    hist_bytes = io.BytesIO(json.dumps(hist_payload).encode("utf-8"))
    resp_hist = client.post(
        "/measurements/",
        files={"file": ("hist.json", hist_bytes, "application/json")},
    )
    assert resp_hist.status_code == 200, resp_hist.text

    return now


def test_get_training_voltage_control_data_integration():
    """Should return valid training data (Overvoltages)."""
    grid_id = "vc_grid_train_pg1"
    _setup_voltage_grid(grid_id, overvoltage=True)

    response = client.get(
        f"{BENCH_PREFIX}/training-scenarios?voltage_limit={VOLTAGE_LIMIT}"
        f"&Scenario=Overvoltages"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert grid_id in data["grids"]
    # Ensure at least one snapshot has measurements
    assert any(
        "measurements" in snap for snap in data["grids"][grid_id].values()
    )


def test_get_voltage_control_data_integration():
    """Should return anonymised voltage control data."""
    grid_id = "vc_grid_vcdata_pg1"
    _setup_voltage_grid(grid_id, overvoltage=True)

    response = client.get(
        f"{BENCH_PREFIX}/voltage-control-data?voltage_limit={VOLTAGE_LIMIT}"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "grids" in data
    assert grid_id in data["grids"]
    assert len(data["grids"][grid_id]) > 0


def test_submit_voltage_control_guesses_integration():
    """Should insert guesses successfully into DB through the API."""
    grid_id = "vc_grid_submit_pg1"
    timestamp = _setup_voltage_grid(grid_id, overvoltage=True)

    # Ensure the anonymised key exists in VoltageTimestampMapping (FK target)
    anon_key = "anon_submit1"
    conn, cursor = db.get_db_connection()
    try:
        db.create_voltage_timestamp_map_table(cursor)
        cursor.execute(
            """
            INSERT INTO "VoltageTimestampMapping" (anonymised_key, grid_id, datetime)
            VALUES (%s, %s, %s)
            """,
            (anon_key, grid_id, timestamp),
        )
        conn.commit()
    finally:
        conn.close()

    body = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": {
            anon_key: [
                {
                    "node_id": "NODE1",
                    "phase": "R",
                    "corrected_voltage": 230.0,
                    "adjusted_power_active": 10.0,
                    "adjusted_power_reactive": 5.0,
                }
            ]
        },
    }

    response = client.post(f"{BENCH_PREFIX}/submit-results", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "submitted"


def test_get_voltage_control_score_integration():
    """Should compute a score based on stored guesses and measurements."""
    grid_id = "vc_grid_score_pg1"
    timestamp = _setup_voltage_grid(grid_id, overvoltage=True)

    # Prepare mapping + guesses directly in the DB using helper creators
    conn, cursor = db.get_db_connection()
    try:
        db.create_voltage_timestamp_map_table(cursor)
        db.create_vc_guesses_database(cursor)

        # Map anonymised key to (grid, timestamp)
        cursor.execute(
            """
            INSERT INTO "VoltageTimestampMapping" (anonymised_key, grid_id, datetime)
            VALUES (%s, %s, %s)
            """,
            ("anon1", grid_id, timestamp),
        )
        conn.commit()
    finally:
        conn.close()

    # Submit guesses via the API so they are stored in VCUserGuesses
    body = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": {
            "anon1": [
                {
                    "node_id": "NODE1",
                    "phase": "R",
                    "corrected_voltage": 231.0,
                    "adjusted_power_active": 10.0,
                    "adjusted_power_reactive": 5.0,
                }
            ]
        },
    }

    submit_resp = client.post(f"{BENCH_PREFIX}/submit-results", json=body)
    assert submit_resp.status_code == 200, submit_resp.text

    # Now compute score
    response = client.get(
        f"{BENCH_PREFIX}/score?guess_id={USER_ID}&grid_id={grid_id}"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "overall_score" in data
    assert isinstance(data["overall_score"], float)
    assert data["total_nodes"] >= 1
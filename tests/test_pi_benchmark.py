import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import phase_identification_benchmark as pi_router
import gridarena.database as db


GRID_ID = "test_grid_001"
USER_ID = "user_123"


# ----------------------------------------------------------------------------------------
# DB cleanup for this module only
# ----------------------------------------------------------------------------------------
#
# IMPORTANT: this must never touch grids/data this test file didn't create. An earlier
# version of this fixture ran `TRUNCATE "Node"/"Cable"/"Connection"/... CASCADE`
# unconditionally against whatever database is configured, which destroyed real grid
# topology in the shared dev database when the suite was run (~78k Node rows, ~73k
# Cable/Connection rows across ~5900 grids). grids(grid_id) has ON DELETE CASCADE down
# to Node/Cable/Connection/HistoricalNodes->Measurements/AnonymisedMapping/UserGuesses,
# so deleting only this file's own grid_id rows from `grids` is enough to fully clean up
# after these tests while leaving every other grid untouched.

# Only the "integration-style" tests below actually write to the real DB (via TestClient);
# the mocked unit tests never touch it. Keep this list in sync with the grid_id values
# used by _setup_phase_grid(...) calls in this file.
TEST_GRID_IDS_FOR_PHASE = [
    GRID_ID,
    "phase_grid_train_pg1",
    "phase_grid_phase_pg1",
    "phase_grid_submit_pg1",
    "phase_grid_score_pg1",
]


def _cleanup_phase_test_grids():
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            "DELETE FROM grids WHERE grid_id = ANY(%s)", (TEST_GRID_IDS_FOR_PHASE,)
        )
        conn.commit()
    except Exception:
        # e.g. table doesn't exist yet -> ignore and continue
        conn.rollback()
    finally:
        conn.close()


@pytest.fixture(autouse=True, scope="module")
def clean_db_for_phase_benchmark():
    """
    Deletes only this module's own test grids (by grid_id) before and after its tests,
    relying on ON DELETE CASCADE to clean up their Node/Cable/Connection/Measurements/
    AnonymisedMapping/UserGuesses rows. Never touches any other grid's data.
    """
    _cleanup_phase_test_grids()
    yield
    _cleanup_phase_test_grids()


# ----------------------------------------------------------------------------------------
# get_training_phase_data
# ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
@patch("gridarena.routers.phase_identification_benchmark.pi.get_all_measurements")
async def test_get_training_phase_data_success(mock_get_measurements, mock_get_db):
    """Should organize measurements by grid and node correctly."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_measurements.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1),
        (GRID_ID, "NODE1", "R", "2025-01-01T01:00:00", 12.0, 6.0, 231.0, 0.2),
        (GRID_ID, "NODE2", "S", "2025-01-01T00:00:00", 9.0, 4.5, 229.5, 0.05),
    ]

    result = await pi_router.get_training_phase_identification_data()
    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "NODE1" in result["grids"][GRID_ID]
    assert len(result["grids"][GRID_ID]["NODE1"]) == 2
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
@patch("gridarena.routers.phase_identification_benchmark.pi.get_all_measurements")
async def test_get_training_phase_data_db_error(mock_get_measurements, mock_get_db):
    """Should raise HTTP 500 on DB error."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    mock_get_measurements.side_effect = Exception("DB fail")

    with pytest.raises(HTTPException) as exc:
        await pi_router.get_training_phase_identification_data()
    assert exc.value.status_code == 500
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# Deterministic noise (seeded RNG)
# ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
@patch("gridarena.routers.phase_identification_benchmark.pi.get_all_measurements")
async def test_training_data_deterministic(mock_get_measurements, mock_get_db):
    """Same difficulty should produce identical noise across calls."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_measurements.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1),
    ]

    r1 = await pi_router.get_training_phase_identification_data(difficulty="easy")
    mock_get_db.return_value = (MagicMock(), MagicMock())
    mock_get_measurements.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1),
    ]
    r2 = await pi_router.get_training_phase_identification_data(difficulty="easy")

    m1 = r1["grids"][GRID_ID]["NODE1"][0]
    m2 = r2["grids"][GRID_ID]["NODE1"][0]
    assert m1["power_active"] == m2["power_active"]
    assert m1["voltage_magnitude"] == m2["voltage_magnitude"]


# ----------------------------------------------------------------------------------------
# get_phase_data (anonymised)
# ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
@patch("gridarena.routers.phase_identification_benchmark.pi.get_all_measurements")
@patch("gridarena.routers.phase_identification_benchmark.pi.build_load_anon_keys")
async def test_get_phase_data_success(
    mock_build_keys, mock_get_meas, mock_get_db
):
    """Should return anonymised data grouped by anon_key."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_meas.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1)
    ]
    mock_build_keys.return_value = {(GRID_ID, "NODE1", "R"): "anon123"}

    result = await pi_router.get_phase_identification_data()
    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "anon123" in result["grids"][GRID_ID]
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
@patch("gridarena.routers.phase_identification_benchmark.pi.get_all_measurements")
async def test_get_phase_data_sql_error(mock_get_meas, mock_get_db):
    """Should raise HTTP 500 if DB throws."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    mock_get_meas.side_effect = Exception("SQL error")

    with pytest.raises(HTTPException) as exc:
        await pi_router.get_phase_identification_data()
    assert exc.value.status_code == 500
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# submit_phase_guesses
# ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_submit_phase_guesses_success(mock_get_db):
    """Should insert guesses and return confirmation."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # First execute returns valid anon keys, subsequent ones are inserts
    cursor.fetchall.return_value = [("anon1",), ("anon2",)]

    phase_guess = MagicMock()
    phase_guess.guess_id = USER_ID
    phase_guess.grid_id = GRID_ID
    phase_guess.guesses = {"anon1": "R", "anon2": "S"}

    result = await pi_router.submit_phase_guesses(phase_guess)
    assert result["status"] == "submitted"
    assert result["accepted"] == 2
    # 1 validation query + 2 inserts
    assert cursor.execute.call_count == 3
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_submit_phase_guesses_db_error(mock_get_db):
    """Should raise HTTP 500 if DB fails."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL failure")

    phase_guess = MagicMock()
    phase_guess.guess_id = USER_ID
    phase_guess.grid_id = GRID_ID
    phase_guess.guesses = {"anon1": "R"}

    with pytest.raises(HTTPException) as exc:
        await pi_router.submit_phase_guesses(phase_guess)
    assert exc.value.status_code == 500
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_submit_phase_guesses_invalid_keys(mock_get_db):
    """Should raise HTTP 422 for unknown anonymised keys."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchall.return_value = [("anon1",)]

    phase_guess = MagicMock()
    phase_guess.guess_id = USER_ID
    phase_guess.grid_id = GRID_ID
    phase_guess.guesses = {"anon1": "R", "bad_key": "S"}

    with pytest.raises(HTTPException) as exc:
        await pi_router.submit_phase_guesses(phase_guess)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_submit_phase_guesses_no_mapping(mock_get_db):
    """Should raise HTTP 422 when no mapping exists for the grid."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchall.return_value = []

    phase_guess = MagicMock()
    phase_guess.guess_id = USER_ID
    phase_guess.grid_id = "nonexistent_grid"
    phase_guess.guesses = {"anon1": "R"}

    with pytest.raises(HTTPException) as exc:
        await pi_router.submit_phase_guesses(phase_guess)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# get_score
# ----------------------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_get_score_computes_accuracy(mock_get_db):
    """Should compute accuracy from DB correctly."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchone.side_effect = [(3,), (5,)]  # 3 correct, 5 total

    result = await pi_router.get_score(USER_ID, GRID_ID)
    assert result["accuracy"] == 0.6
    assert result["grid_id"] == GRID_ID
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_get_score_handles_zero_total(mock_get_db):
    """Should handle division by zero safely."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchone.side_effect = [(0,), (0,)]  # 0 correct, 0 total

    result = await pi_router.get_score(USER_ID, GRID_ID)
    assert result["accuracy"] == 0.0
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.phase_identification_benchmark.db.get_db_connection")
async def test_get_score_db_error(mock_get_db):
    """Should raise HTTP 500 on DB failure."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL error")

    with pytest.raises(HTTPException) as exc:
        await pi_router.get_score(USER_ID, GRID_ID)
    assert exc.value.status_code == 500
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# Integration-style tests (real FastAPI + PostgreSQL via app)
# ----------------------------------------------------------------------------------------

client = TestClient(app)
BENCH_PREFIX = "/phase_identification_benchmark"
USER_ID = "user_123"


def _setup_phase_grid(grid_id: str):
    """Create a minimal grid + historical data via public API endpoints."""

    # Minimal grid definition
    grid_payload = {
        "grid_id": grid_id,
        "nodes": [
            {"node_id": "PT", "coord_lat": 38.65, "coord_lon": -7.98, "coord_error": 1},
            {"node_id": "NODE1", "coord_lat": 38.651, "coord_lon": -7.981, "coord_error": 1},
            {"node_id": "NODE2", "coord_lat": 38.652, "coord_lon": -7.982, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "LineUID000001",
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

    # Minimal historical data
    hist_payload = {
        "grid_id": grid_id,
        "historical": [
            {
                "node_id": "NODE1",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "R",
                        "power_active": 10.0,
                        "power_reactive": 5.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": 0.0,
                    }
                ],
            },
            {
                "node_id": "NODE2",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "S",
                        "power_active": 9.0,
                        "power_reactive": 4.0,
                        "voltage_magnitude": 229.5,
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


def test_get_training_phase_identification_data_integration():
    """Should return structured measurement data grouped by grid and node."""
    grid_id = "phase_grid_train_pg1"
    _setup_phase_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/training-phase-data")
    assert response.status_code == 200, response.text
    data = response.json()

    assert "grids" in data
    assert grid_id in data["grids"]
    assert "NODE1" in data["grids"][grid_id]
    assert len(data["grids"][grid_id]["NODE1"]) > 0


def test_get_phase_identification_data_integration():
    """Should return anonymised measurement data."""
    grid_id = "phase_grid_phase_pg1"
    _setup_phase_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/phase-data")
    assert response.status_code == 200, response.text
    data = response.json()

    assert "grids" in data
    assert grid_id in data["grids"]
    grid_map = data["grids"][grid_id]
    assert isinstance(grid_map, dict)
    assert len(grid_map.keys()) > 0
    assert any(isinstance(k, str) for k in grid_map.keys())


def test_submit_phase_guesses_integration():
    """Should allow posting phase guesses for anonymised nodes."""
    grid_id = "phase_grid_submit_pg1"
    _setup_phase_grid(grid_id)

    phase_resp = client.get(f"{BENCH_PREFIX}/phase-data")
    assert phase_resp.status_code == 200, phase_resp.text
    phase_data = phase_resp.json()

    anon_map = phase_data["grids"][grid_id]
    anon_keys = list(anon_map.keys())
    assert len(anon_keys) > 0

    guesses = {k: "R" for k in anon_keys}

    payload = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": guesses,
    }

    response = client.post(f"{BENCH_PREFIX}/submit-results", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "submitted"


def test_get_score_integration():
    """Should calculate user accuracy correctly using stored guesses and mapping."""
    grid_id = "phase_grid_score_pg1"
    _setup_phase_grid(grid_id)

    # Create anonymised mapping by calling phase-data
    phase_resp = client.get(f"{BENCH_PREFIX}/phase-data")
    assert phase_resp.status_code == 200, phase_resp.text
    phase_data = phase_resp.json()

    anon_map = phase_data["grids"][grid_id]
    anon_keys = list(anon_map.keys())
    assert len(anon_keys) > 0

    # Submit guesses for these keys
    guesses = {k: "R" for k in anon_keys}

    payload = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": guesses,
    }

    submit_resp = client.post(f"{BENCH_PREFIX}/submit-results", json=payload)
    assert submit_resp.status_code == 200, submit_resp.text

    # Get score
    score_resp = client.get(f"{BENCH_PREFIX}/score?guess_id={USER_ID}&grid_id={grid_id}")
    assert score_resp.status_code == 200, score_resp.text
    data = score_resp.json()

    assert data["grid_id"] == grid_id
    assert "accuracy" in data
    assert 0.0 <= data["accuracy"] <= 1.0
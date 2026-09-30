import io
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import measurements as meas_router
from gridarena.routers.measurements import register_measurements_data
import gridarena.database as db


@pytest.mark.asyncio
@patch("gridarena.database.insert_measurements_data")
@patch("gridarena.database.create_measurements_tables")
@patch("gridarena.database.get_db_connection")
async def test_register_grid_unit(mock_get_conn, mock_create_db, mock_insert_db):
    # Setup mocks
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    # Simulate a valid JSON grid file
    fake_historical = {"grid_id": "grid123", "historical": []}
    file_bytes = io.BytesIO(json.dumps(fake_historical).encode("utf-8"))
    upload = UploadFile(filename="historical.json", file=file_bytes)

    # Call function directly (no FastAPI client)
    result = await register_measurements_data(upload)

    # Assert success message
    assert result == {"message": "Measurement data for grid 'grid123' inserted successfully."}

    # Assert DB functions called properly
    mock_create_db.assert_called_once_with(mock_cursor)
    mock_insert_db.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_register_historical_invalid_json():
    """Should raise 400 for invalid JSON."""
    bad_json = io.BytesIO(b"{invalid json")
    upload = UploadFile(filename="bad.json", file=bad_json)

    with pytest.raises(HTTPException) as exc:
        await meas_router.register_measurements_data(upload)

    assert exc.value.status_code == 400
    assert "Invalid JSON format" in exc.value.detail


@pytest.mark.asyncio
async def test_register_historical_schema_error():
    """Should raise 422 if schema validation fails."""

    bad_data = {"grid_id": "grid_bad"}
    file_bytes = io.BytesIO(json.dumps(bad_data).encode("utf-8"))
    upload = UploadFile(filename="hist.json", file=file_bytes)

    with pytest.raises(HTTPException) as exc:
        await meas_router.register_measurements_data(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
@patch("gridarena.database.insert_measurements_data", side_effect=Exception("SQL insert error"))
@patch("gridarena.database.create_measurements_tables")
@patch("gridarena.database.get_db_connection")
async def test_register_historical_db_error(mock_get_conn, mock_create_tables, mock_insert):
    """Should raise 500 if database error occurs."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    data = {"grid_id": "grid_fail", "historical": []}
    file_bytes = io.BytesIO(json.dumps(data).encode("utf-8"))
    upload = UploadFile(filename="hist.json", file=file_bytes)

    with pytest.raises(HTTPException) as exc:
        await meas_router.register_measurements_data(upload)

    assert exc.value.status_code == 500
    assert "Database error" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------
# delete_measurements() — various branches
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_historical_success(mock_get_conn):
    """Should delete rows and return proper message."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 3
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    result = await meas_router.delete_measurements("grid_ok", start=None, end=None)
    assert result == {"message": "3 measurement(s) deleted for grid 'grid_ok'."}
    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_delete_historical_invalid_datetime():
    """Should raise 400 if datetime cannot be parsed."""
    with pytest.raises(HTTPException) as exc:
        await meas_router.delete_measurements("grid_bad", start="bad_date")
    assert exc.value.status_code == 400
    assert "Invalid datetime format" in exc.value.detail


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_historical_with_filters(mock_get_conn):
    """Should build query correctly with node_id, phase, and date filters."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    start = datetime(2025, 1, 1).isoformat()
    end = datetime(2025, 1, 2).isoformat()
    result = await meas_router.delete_measurements(
        "grid_filters", node_id="NODE1", phase="R", start=start, end=end
    )

    assert "deleted" in result["message"]
    query = mock_cursor.execute.call_args[0][0]
    assert "node_id" in query and "phase" in query and "datetime" in query
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_historical_db_error(mock_get_conn):
    """Should raise 500 if database error occurs."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("delete failed")
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await meas_router.delete_measurements("grid_fail", start=None, end=None)
    assert exc.value.status_code == 500
    assert "Database error" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------
# get_measurements_data() — filters, validation, errors
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_historical_success(mock_get_conn):
    """Should return correctly structured data."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    mock_cursor.fetchall.return_value = [
        ("PT", "2025-01-01T00:00:00", "R", 10.0, 2.0, 230.0, 0.0),
        ("NODE1", "2025-01-01T01:00:00", "S", 11.0, 3.0, 229.8, 0.1),
    ]

    result = await meas_router.get_measurements_data("grid_ok", start=None, end=None)

    assert result["grid_id"] == "grid_ok"
    assert len(result["records"]) == 2
    assert all("node_id" in rec for rec in result["records"])
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_historical_invalid_datetime():
    """Should raise 400 for badly formatted datetime."""
    with pytest.raises(HTTPException) as exc:
        await meas_router.get_measurements_data("grid", start="invalid-date")
    assert exc.value.status_code == 400
    assert "Invalid datetime" in exc.value.detail


@pytest.mark.asyncio
async def test_get_historical_phase_with_per_phase_false():
    """Should raise 400 if phase is given but per_phase=False."""
    with pytest.raises(HTTPException) as exc:
        await meas_router.get_measurements_data(
            "grid", per_phase=False, phase="R", start=None, end=None
        )
    assert exc.value.status_code == 400
    assert "requires per_phase=true" in exc.value.detail


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_historical_no_results(mock_get_conn):
    """Should raise 404 if no data found."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await meas_router.get_measurements_data("empty_grid", start=None, end=None)
    assert exc.value.status_code == 404
    assert "no measurements found" in exc.value.detail.lower()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_historical_db_error(mock_get_conn):
    """Should raise 500 if DB query fails."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("bad select")
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await meas_router.get_measurements_data("grid_fail", start=None, end=None)
    assert exc.value.status_code == 500
    assert "database error" in exc.value.detail.lower()
    mock_conn.close.assert_called_once()


################################################# INTEGRATION TESTS #####################################################

client = TestClient(app)
HIST_PREFIX = "/measurements"

# ----------------------------
# Example data for testing
# ----------------------------
GRID_ID = "test_grid_001"
NOW = datetime.utcnow()

EXAMPLE_HISTORICAL = {
    "grid_id": GRID_ID,
    "historical": [
        {
            "node_id": "PT",
            "measurements": [
                {
                    "datetime": (NOW - timedelta(hours=1)).isoformat(),
                    "phase": "R",
                    "power_active": 12.3,
                    "power_reactive": 4.5,
                    "voltage_magnitude": 230.1,
                    "voltage_angle": -5.6,
                },
                {
                    "datetime": NOW.isoformat(),
                    "phase": "S",
                    "power_active": 15.1,
                    "power_reactive": 3.3,
                    "voltage_magnitude": 231.4,
                    "voltage_angle": -3.1,
                },
            ],
        },
        {
            "node_id": "NODE0001",
            "measurements": [
                {
                    "datetime": (NOW - timedelta(hours=2)).isoformat(),
                    "phase": "R",
                    "power_active": 10.8,
                    "power_reactive": 2.9,
                    "voltage_magnitude": 229.9,
                    "voltage_angle": -4.4,
                }
            ],
        },
    ],
}


# ----------------------------
# DB helpers for integration tests
# ----------------------------

def ensure_grids_table():
    """Ensure the base `grids` table exists (idempotent)."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS grids (
                grid_id TEXT PRIMARY KEY
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def ensure_measurements_tables():
    """Ensure all measurement-related tables exist (idempotent)."""
    # First ensure the referenced `grids` table exists
    ensure_grids_table()

    conn, cursor = db.get_db_connection()
    try:
        db.create_measurements_tables(cursor)
        conn.commit()
    finally:
        conn.close()


def ensure_grid_exists(grid_id: str):
    """Ensure a given grid_id exists in the grids table (idempotent)."""
    # Ensure the table exists first
    ensure_grids_table()

    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            "INSERT INTO grids (grid_id) VALUES (%s) "
            "ON CONFLICT (grid_id) DO NOTHING",
            (grid_id,),
        )
        conn.commit()
    finally:
        conn.close()


def reset_grid_data(grid_id: str):
    """
    Ensure the grid exists, historical tables exist,
    and clear existing historical data for that grid.
    """
    # 1) Make sure the grid row exists
    ensure_grid_exists(grid_id)
    # 2) Make sure historical tables exist (FKs now safe)
    ensure_measurements_tables()

    conn, cursor = db.get_db_connection()
    try:
        cursor.execute('DELETE FROM "Measurements" WHERE grid_id = %s', (grid_id,))
        cursor.execute('DELETE FROM "HistoricalNodes" WHERE grid_id = %s', (grid_id,))
        conn.commit()
    finally:
        conn.close()


def prepare_example_grid():
    """Prepare GRID_ID with EXAMPLE_HISTORICAL data, in a clean state."""
    reset_grid_data(GRID_ID)
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_HISTORICAL).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
    )
    assert response.status_code == 200, response.text


# ----------------------------
# Upload tests
# ----------------------------


def test_upload_valid_historical_data():
    """Should successfully upload a valid historical JSON file."""
    reset_grid_data(GRID_ID)

    file_bytes = io.BytesIO(json.dumps(EXAMPLE_HISTORICAL).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "inserted successfully" in data["message"]
    assert GRID_ID in data["message"]


def test_upload_invalid_json():
    """Should fail with invalid JSON format."""
    ensure_measurements_tables()
    bad_json = io.BytesIO(b"{ invalid json }")
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("bad.json", bad_json, "application/json")}
    )

    assert response.status_code == 400
    assert "Invalid JSON format" in response.json()["detail"]


def test_upload_schema_validation_error():
    """Should fail if JSON misses required fields."""
    ensure_measurements_tables()
    incomplete_data = {"grid_id": GRID_ID}  # Missing 'historical'
    file_bytes = io.BytesIO(json.dumps(incomplete_data).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("hist_bad.json", file_bytes, "application/json")}
    )

    assert response.status_code == 422
    assert "historical" in str(response.json()["detail"])


# ----------------------------
# Retrieval tests
# ----------------------------


def test_get_all_historical_data():
    """Should retrieve historical data for a given grid."""
    prepare_example_grid()

    response = client.get(f"{HIST_PREFIX}data/{GRID_ID}")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["grid_id"] == GRID_ID
    assert data["count"] >= 2
    assert all("voltage_magnitude" in rec for rec in data["records"])


def test_get_data_with_node_filter():
    """Should retrieve historical data filtered by node_id."""
    prepare_example_grid()

    response = client.get(f"{HIST_PREFIX}data/{GRID_ID}?node_id=PT")
    assert response.status_code == 200, response.text
    data = response.json()
    assert all(rec["node_id"] == "PT" for rec in data["records"])


def test_get_data_with_phase_filter():
    """Should retrieve only a single phase when specified."""
    prepare_example_grid()

    response = client.get(f"{HIST_PREFIX}data/{GRID_ID}?phase=R&per_phase=true")
    assert response.status_code == 200, response.text
    data = response.json()
    assert all(rec["phase"] == "R" for rec in data["records"])


def test_get_data_time_window():
    """Should retrieve data in a datetime window."""
    prepare_example_grid()

    start = (NOW - timedelta(hours=2)).isoformat()
    end = (NOW - timedelta(minutes=30)).isoformat()
    response = client.get(f"{HIST_PREFIX}data/{GRID_ID}?start={start}&end={end}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert all(start <= rec["datetime"] < end for rec in data["records"])


def test_get_data_nonexistent_grid():
    """Should return 404 for unknown grid_id."""
    ensure_measurements_tables()

    response = client.get(f"{HIST_PREFIX}data/nonexistent_grid_999")
    assert response.status_code == 404
    assert "No measurements found" in response.json()["detail"]


# ----------------------------
# Delete tests
# ----------------------------


def test_delete_measurements_by_node():
    """Should delete measurements for a specific node."""
    prepare_example_grid()

    response = client.delete(f"{HIST_PREFIX}/{GRID_ID}?node_id=NODE0001")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "deleted" in data["message"].lower()


def test_delete_nonexistent_grid():
    """Should not fail badly when deleting unknown grid_id."""
    ensure_measurements_tables()

    response = client.delete(f"{HIST_PREFIX}/no_such_grid_001")
    assert response.status_code == 200 or response.status_code == 500


def test_upload_and_retrieve_multiple_grids():
    """Should allow uploading historical data for multiple grids and retrieving them independently."""

    # --- Define Grid A ---
    grid_a = {
        "grid_id": "hist_grid_A",
        "historical": [
            {
                "node_id": "PT_A",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=1)).isoformat(),
                        "phase": "R",
                        "power_active": 10.0,
                        "power_reactive": 5.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": -5.0,
                    }
                ],
            }
        ],
    }

    # --- Define Grid B ---
    grid_b = {
        "grid_id": "hist_grid_B",
        "historical": [
            {
                "node_id": "PT_B",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=2)).isoformat(),
                        "phase": "S",
                        "power_active": 15.0,
                        "power_reactive": 3.0,
                        "voltage_magnitude": 231.5,
                        "voltage_angle": -3.2,
                    }
                ],
            }
        ],
    }

    for grid in [grid_a, grid_b]:
        reset_grid_data(grid["grid_id"])
        file_bytes = io.BytesIO(json.dumps(grid).encode("utf-8"))
        response = client.post(
            f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
        )
        assert response.status_code == 200, response.text
        assert grid["grid_id"] in response.json()["message"]

    res_a = client.get(f"{HIST_PREFIX}data/{grid_a['grid_id']}")
    assert res_a.status_code == 200, res_a.text
    data_a = res_a.json()
    assert data_a["grid_id"] == grid_a["grid_id"]
    assert all(rec["node_id"].startswith("PT_A") for rec in data_a["records"])

    res_b = client.get(f"{HIST_PREFIX}data/{grid_b['grid_id']}")
    assert res_b.status_code == 200, res_b.text
    data_b = res_b.json()
    assert data_b["grid_id"] == grid_b["grid_id"]
    assert all(rec["node_id"].startswith("PT_B") for rec in data_b["records"])

    # --- Ensure no cross-contamination ---
    nodes_a = {rec["node_id"] for rec in data_a["records"]}
    nodes_b = {rec["node_id"] for rec in data_b["records"]}
    assert nodes_a.isdisjoint(nodes_b), "Historical records between grids are mixed up!"


def test_delete_multiple_grids_independently():
    """Should delete historical data from one grid without affecting the other."""
    # Prepare both grids with data
    now_local = NOW

    grid_a = {
        "grid_id": "hist_grid_A",
        "historical": [
            {
                "node_id": "PT_A",
                "measurements": [
                    {
                        "datetime": (now_local - timedelta(hours=1)).isoformat(),
                        "phase": "R",
                        "power_active": 10.0,
                        "power_reactive": 5.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": -5.0,
                    }
                ],
            }
        ],
    }
    grid_b = {
        "grid_id": "hist_grid_B",
        "historical": [
            {
                "node_id": "PT_B",
                "measurements": [
                    {
                        "datetime": (now_local - timedelta(hours=2)).isoformat(),
                        "phase": "S",
                        "power_active": 15.0,
                        "power_reactive": 3.0,
                        "voltage_magnitude": 231.5,
                        "voltage_angle": -3.2,
                    }
                ],
            }
        ],
    }

    for grid in [grid_a, grid_b]:
        reset_grid_data(grid["grid_id"])
        file_bytes = io.BytesIO(json.dumps(grid).encode("utf-8"))
        resp = client.post(
            f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
        )
        assert resp.status_code == 200, resp.text

    grid_to_delete = "hist_grid_A"
    grid_to_keep = "hist_grid_B"

    response_del = client.delete(f"{HIST_PREFIX}/{grid_to_delete}")
    assert response_del.status_code == 200, response_del.text
    assert "deleted" in response_del.json()["message"].lower()

    response_a = client.get(f"{HIST_PREFIX}data/{grid_to_delete}")
    assert response_a.status_code == 404

    response_b = client.get(f"{HIST_PREFIX}data/{grid_to_keep}")
    assert response_b.status_code == 200
    data_b = response_b.json()
    assert data_b["grid_id"] == grid_to_keep
    assert len(data_b["records"]) > 0


def test_filtering_per_grid_independently():
    """Should apply node_id, phase, and datetime filters per grid without leaking results."""

    # --- Create two grids with distinct characteristics ---
    grid_a = {
        "grid_id": "filter_grid_A",
        "historical": [
            {
                "node_id": "NODE_A1",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=3)).isoformat(),
                        "phase": "R",
                        "power_active": 10.0,
                        "power_reactive": 5.0,
                        "voltage_magnitude": 230.0,
                        "voltage_angle": -5.0,
                    },
                    {
                        "datetime": (NOW - timedelta(hours=2)).isoformat(),
                        "phase": "S",
                        "power_active": 11.0,
                        "power_reactive": 4.8,
                        "voltage_magnitude": 229.9,
                        "voltage_angle": -4.2,
                    },
                ],
            }
        ],
    }

    grid_b = {
        "grid_id": "filter_grid_B",
        "historical": [
            {
                "node_id": "NODE_B1",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=1)).isoformat(),
                        "phase": "T",
                        "power_active": 14.0,
                        "power_reactive": 3.5,
                        "voltage_magnitude": 231.5,
                        "voltage_angle": -2.5,
                    }
                ],
            }
        ],
    }

    for grid in [grid_a, grid_b]:
        reset_grid_data(grid["grid_id"])
        file_bytes = io.BytesIO(json.dumps(grid).encode("utf-8"))
        response = client.post(
            f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
        )
        assert response.status_code == 200, response.text
        assert grid["grid_id"] in response.json()["message"]

    res_a_node = client.get(f"{HIST_PREFIX}data/{grid_a['grid_id']}?node_id=NODE_A1")
    res_b_node = client.get(f"{HIST_PREFIX}data/{grid_b['grid_id']}?node_id=NODE_B1")

    assert res_a_node.status_code == 200
    assert res_b_node.status_code == 200
    data_a = res_a_node.json()
    data_b = res_b_node.json()

    assert all(rec["node_id"] == "NODE_A1" for rec in data_a["records"])
    assert all(rec["node_id"] == "NODE_B1" for rec in data_b["records"])

    res_a_phase_r = client.get(f"{HIST_PREFIX}data/{grid_a['grid_id']}?phase=R&per_phase=true")
    res_b_phase_t = client.get(f"{HIST_PREFIX}data/{grid_b['grid_id']}?phase=T&per_phase=true")

    assert res_a_phase_r.status_code == 200
    assert res_b_phase_t.status_code == 200
    data_a_phase = res_a_phase_r.json()
    data_b_phase = res_b_phase_t.json()

    assert all(rec["phase"] == "R" for rec in data_a_phase["records"])
    assert all(rec["phase"] == "T" for rec in data_b_phase["records"])

    start_a = (NOW - timedelta(hours=3, minutes=30)).isoformat()
    end_a = (NOW - timedelta(hours=1, minutes=30)).isoformat()
    res_a_time = client.get(f"{HIST_PREFIX}data/{grid_a['grid_id']}?start={start_a}&end={end_a}")
    assert res_a_time.status_code == 200, res_a_time.text
    data_a_time = res_a_time.json()

    assert all(start_a <= rec["datetime"] <= end_a for rec in data_a_time["records"])
    assert all(rec["node_id"].startswith("NODE_A") for rec in data_a_time["records"])

    # --- Ensure no cross-contamination ---
    nodes_a = {rec["node_id"] for rec in data_a_time["records"]}
    res_b_all = client.get(f"{HIST_PREFIX}data/{grid_b['grid_id']}").json()
    nodes_b = {rec["node_id"] for rec in res_b_all["records"]}

    assert nodes_a.isdisjoint(nodes_b), "Filtered data from Grid A leaked into Grid B!"


def test_combined_filters_within_single_grid():
    """Should correctly apply combined node_id, phase, and time filters for one grid only."""

    grid_id = "filter_combo_grid"
    node_id = "NODE_X1"

    # --- Create a grid with multiple measurements ---
    grid_data = {
        "grid_id": grid_id,
        "historical": [
            {
                "node_id": node_id,
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=4)).isoformat(),
                        "phase": "R",
                        "power_active": 9.5,
                        "power_reactive": 3.1,
                        "voltage_magnitude": 229.5,
                        "voltage_angle": -5.0,
                    },
                    {
                        "datetime": (NOW - timedelta(hours=3)).isoformat(),
                        "phase": "S",
                        "power_active": 10.2,
                        "power_reactive": 3.0,
                        "voltage_magnitude": 230.5,
                        "voltage_angle": -4.5,
                    },
                    {
                        "datetime": (NOW - timedelta(hours=2)).isoformat(),
                        "phase": "R",
                        "power_active": 11.0,
                        "power_reactive": 2.8,
                        "voltage_magnitude": 231.0,
                        "voltage_angle": -3.5,
                    },
                ],
            },
            {
                "node_id": "NODE_X2",
                "measurements": [
                    {
                        "datetime": (NOW - timedelta(hours=2)).isoformat(),
                        "phase": "R",
                        "power_active": 7.5,
                        "power_reactive": 2.0,
                        "voltage_magnitude": 228.9,
                        "voltage_angle": -4.0,
                    }
                ],
            },
        ],
    }

    reset_grid_data(grid_id)
    file_bytes = io.BytesIO(json.dumps(grid_data).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
    )
    assert response.status_code == 200, response.text
    assert grid_id in response.json()["message"]

    start_time = (NOW - timedelta(hours=3, minutes=30)).isoformat()
    end_time = (NOW - timedelta(hours=1, minutes=30)).isoformat()

    response = client.get(
        f"{HIST_PREFIX}data/{grid_id}?node_id={node_id}&phase=R&start={start_time}&end={end_time}&per_phase=true"
    )

    assert response.status_code == 200, response.text
    data = response.json()

    # --- Assertions ---
    assert data["grid_id"] == grid_id
    assert all(
        rec["node_id"] == node_id for rec in data["records"]
    ), "Mixed node IDs in filtered results"
    assert all(rec["phase"] == "R" for rec in data["records"]), "Wrong phase in filtered results"
    assert all(
        start_time <= rec["datetime"] <= end_time for rec in data["records"]
    ), "Record outside time window"

    # --- Confirm filtering precision ---
    filtered_datetimes = [rec["datetime"] for rec in data["records"]]
    assert (
        len(filtered_datetimes) >= 1
    ), f"Expected at least 1 record, got {len(filtered_datetimes)}"

    assert all(
        start_time <= dt <= end_time for dt in filtered_datetimes
    ), "Out-of-range datetime found"
    assert any(
        abs(json.loads(json.dumps(rec))["power_active"] - 11.0) < 0.001 for rec in data["records"]
    )


def test_combined_filters_no_match_returns_empty():
    """Should return 404 if combined filters have no match."""
    grid_id = "filter_combo_grid"

    ensure_measurements_tables()

    start = (NOW - timedelta(days=10)).isoformat()
    end = (NOW - timedelta(days=9)).isoformat()
    response = client.get(f"{HIST_PREFIX}data/{grid_id}?start={start}&end={end}&phase=T")

    assert response.status_code == 404, response.text
    data = response.json()
    assert "No measurements found" in data["detail"]


def test_combined_filters_across_multiple_grids_isolated():
    """Ensure filtering applies per grid even when timestamps and phases overlap."""

    grid_a = "grid_alpha"
    grid_b = "grid_beta"

    # Common overlapping timestamps
    t1 = (NOW - timedelta(hours=4)).isoformat()
    t2 = (NOW - timedelta(hours=3)).isoformat()

    # Grid A data
    hist_a = {
        "grid_id": grid_a,
        "historical": [
            {
                "node_id": "PT",
                "measurements": [
                    {
                        "datetime": t1,
                        "phase": "R",
                        "power_active": 12.0,
                        "power_reactive": 3.0,
                        "voltage_magnitude": 230.5,
                        "voltage_angle": -4.2,
                    },
                    {
                        "datetime": t2,
                        "phase": "S",
                        "power_active": 11.5,
                        "power_reactive": 2.9,
                        "voltage_magnitude": 231.1,
                        "voltage_angle": -3.8,
                    },
                ],
            }
        ],
    }

    # Grid B data (same timestamps and node name, but different grid)
    hist_b = {
        "grid_id": grid_b,
        "historical": [
            {
                "node_id": "PT",
                "measurements": [
                    {
                        "datetime": t1,
                        "phase": "R",
                        "power_active": 8.0,
                        "power_reactive": 2.0,
                        "voltage_magnitude": 228.0,
                        "voltage_angle": -5.0,
                    }
                ],
            }
        ],
    }

    for hist in (hist_a, hist_b):
        reset_grid_data(hist["grid_id"])
        file_bytes = io.BytesIO(json.dumps(hist).encode("utf-8"))
        resp = client.post(
            f"{HIST_PREFIX}/", files={"file": ("hist.json", file_bytes, "application/json")}
        )
        assert resp.status_code == 200, resp.text

    # Apply overlapping filters — same time/phase, but different grids
    response_a = client.get(f"{HIST_PREFIX}data/{grid_a}?phase=R&start={t1}&end={t2}")
    response_b = client.get(f"{HIST_PREFIX}data/{grid_b}?phase=R&start={t1}&end={t2}")

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text

    data_a = response_a.json()
    data_b = response_b.json()

    # Grid A should only return its own data
    assert data_a["grid_id"] == grid_a
    assert all(rec["phase"] == "R" for rec in data_a["records"])
    assert all(rec["voltage_magnitude"] > 230 for rec in data_a["records"])
    assert all(rec["node_id"] == "PT" for rec in data_a["records"])

    # Grid B should only return its own data
    assert data_b["grid_id"] == grid_b
    assert all(rec["phase"] == "R" for rec in data_b["records"])
    assert all(rec["voltage_magnitude"] < 230 for rec in data_b["records"])
    assert all(rec["node_id"] == "PT" for rec in data_b["records"])

    # Ensure isolation — no shared measurement datetimes/values
    timestamps_a = {rec["datetime"] for rec in data_a["records"]}
    timestamps_b = {rec["datetime"] for rec in data_b["records"]}
    assert timestamps_a == timestamps_b, "Expected same timestamps"
    assert data_a != data_b, "Grid data should differ even if timestamps overlap"

    print("Multi-grid isolation test passed — filters apply per grid cleanly.")
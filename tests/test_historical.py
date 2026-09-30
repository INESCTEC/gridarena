import io
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import historical as hist_router
from gridarena.routers.historical import upload_historical_database
import gridarena.database as db


def _make_upload(payload: dict, filename: str = "database.json") -> UploadFile:
    file_bytes = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return UploadFile(filename=filename, file=file_bytes)


@pytest.mark.asyncio
@patch("gridarena.database.insert_historical_data")
@patch("gridarena.database.create_historical_data_tables")
@patch("gridarena.database.get_db_connection")
async def test_upload_database_unit(mock_get_conn, mock_create_db, mock_insert_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    fake_db = {
        "database_id": "db123",
        "timestamps": ["2025-01-01T00:00:00"],
        "historicals": [
            {"series_id": "s1", "grid_level": "LV", "values": [
                {"datetime": "2025-01-01T00:00:00", "power_active": 10.0}
            ]}
        ],
    }
    upload = _make_upload(fake_db)

    result = await upload_historical_database(upload)

    assert "db123" in result["message"]
    assert "inserted successfully" in result["message"]
    mock_create_db.assert_called_once_with(mock_cursor)
    mock_insert_db.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_upload_historical_invalid_json():
    """Should raise 400 for invalid JSON."""
    bad_json = io.BytesIO(b"{invalid json")
    upload = UploadFile(filename="bad.json", file=bad_json)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 400
    assert "Invalid JSON format" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_historical_schema_error_missing_field():
    """Should raise 422 if schema validation fails (missing timestamps)."""
    bad_data = {"database_id": "db_bad", "historicals": []}
    upload = _make_upload(bad_data)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_historical_schema_error_no_power_or_voltage():
    """Should raise 422 if a value has neither power nor voltage set."""
    bad_data = {
        "database_id": "db_bad",
        "timestamps": ["2025-01-01T00:00:00"],
        "historicals": [
            {"series_id": "s1", "grid_level": "MV", "values": [{"datetime": "2025-01-01T00:00:00"}]}
        ],
    }
    upload = _make_upload(bad_data)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_historical_schema_error_datetime_not_in_timestamps():
    """Should raise 422 if a value's datetime isn't in the declared timestamps."""
    bad_data = {
        "database_id": "db_bad",
        "timestamps": ["2025-01-01T00:00:00"],
        "historicals": [
            {"series_id": "s1", "grid_level": "MV", "values": [
                {"datetime": "2025-01-01T01:00:00", "power_active": 1.0}
            ]}
        ],
    }
    upload = _make_upload(bad_data)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_historical_schema_error_duplicate_series_id():
    """Should raise 422 if two historicals in the same upload share a series_id."""
    bad_data = {
        "database_id": "db_bad",
        "timestamps": ["2025-01-01T00:00:00"],
        "historicals": [
            {"series_id": "dup", "grid_level": "MV", "values": [
                {"datetime": "2025-01-01T00:00:00", "power_active": 1.0}
            ]},
            {"series_id": "dup", "grid_level": "LV", "values": [
                {"datetime": "2025-01-01T00:00:00", "power_active": 2.0}
            ]},
        ],
    }
    upload = _make_upload(bad_data)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
@patch("gridarena.database.insert_historical_data", side_effect=Exception("SQL insert error"))
@patch("gridarena.database.create_historical_data_tables")
@patch("gridarena.database.get_db_connection")
async def test_upload_historical_db_error(mock_get_conn, mock_create_tables, mock_insert):
    """Should raise 500 if database error occurs."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    data = {
        "database_id": "db_fail",
        "timestamps": ["2025-01-01T00:00:00"],
        "historicals": [
            {"series_id": "s1", "grid_level": "LV", "values": [
                {"datetime": "2025-01-01T00:00:00", "power_active": 1.0}
            ]}
        ],
    }
    upload = _make_upload(data)

    with pytest.raises(HTTPException) as exc:
        await hist_router.upload_historical_database(upload)

    assert exc.value.status_code == 500
    assert "Database error" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------
# delete_historical_database() / delete_historical_series_records()
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_database_success(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    result = await hist_router.delete_historical_database("db_ok")
    assert result == {"message": "1 database(s) deleted for 'db_ok'."}
    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_series_records_success(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 3
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    result = await hist_router.delete_historical_series_records("db_ok", "s1", start=None, end=None)
    assert result == {"message": "3 record(s) deleted for series 's1' in database 'db_ok'."}
    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_delete_series_records_invalid_datetime():
    with pytest.raises(HTTPException) as exc:
        await hist_router.delete_historical_series_records("db_bad", "s1", start="bad_date")
    assert exc.value.status_code == 400
    assert "Invalid datetime format" in exc.value.detail


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_series_records_with_filters(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    start = datetime(2025, 1, 1).isoformat()
    end = datetime(2025, 1, 2).isoformat()
    result = await hist_router.delete_historical_series_records(
        "db_filters", "s1", phase="R", start=start, end=end
    )

    assert "deleted" in result["message"]
    query = mock_cursor.execute.call_args[0][0]
    assert "phase" in query and "datetime" in query
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_delete_series_records_db_error(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("delete failed")
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await hist_router.delete_historical_series_records("db_fail", "s1", start=None, end=None)
    assert exc.value.status_code == 500
    assert "Database error" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


################################################# INTEGRATION TESTS #####################################################

client = TestClient(app)
HIST_PREFIX = "/historical"

DATABASE_ID = "test_db_001"
NOW = datetime.utcnow().replace(microsecond=0)
TIMESTAMPS = [
    (NOW - timedelta(hours=2)).isoformat(),
    (NOW - timedelta(hours=1)).isoformat(),
    NOW.isoformat(),
]

EXAMPLE_DATABASE = {
    "database_id": DATABASE_ID,
    "name": "Example database",
    "timestamps": TIMESTAMPS,
    "historicals": [
        {
            "series_id": "power_series",
            "grid_level": "LV",
            "values": [
                {"datetime": TIMESTAMPS[0], "phase": "R", "power_active": 12.3, "power_reactive": 4.5},
                {"datetime": TIMESTAMPS[1], "phase": "S", "power_active": 15.1, "power_reactive": 3.3},
                {"datetime": TIMESTAMPS[2], "phase": "R", "power_active": 10.8, "power_reactive": 2.9},
            ],
        },
        {
            "series_id": "voltage_series",
            "grid_level": "MV",
            "values": [
                {"datetime": TIMESTAMPS[0], "voltage_magnitude": 20000.0, "voltage_angle": 0.0},
                {"datetime": TIMESTAMPS[1], "voltage_magnitude": 19980.0, "voltage_angle": -0.1},
            ],
        },
    ],
}


def ensure_historical_tables():
    """Ensure all historical-database tables exist (idempotent)."""
    conn, cursor = db.get_db_connection()
    try:
        db.create_historical_data_tables(cursor)
        conn.commit()
    finally:
        conn.close()


def reset_database_data(database_id: str):
    """Ensure historical tables exist and remove a database entirely (cascades)."""
    ensure_historical_tables()
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute('DELETE FROM "HistoricalDatabase" WHERE database_id = %s', (database_id,))
        conn.commit()
    finally:
        conn.close()


def prepare_example_database():
    """Prepare DATABASE_ID with EXAMPLE_DATABASE data, in a clean state."""
    reset_database_data(DATABASE_ID)
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_DATABASE).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("db.json", file_bytes, "application/json")}
    )
    assert response.status_code == 200, response.text


# ----------------------------
# Upload tests
# ----------------------------


def test_upload_valid_database_with_multiple_series():
    """Should successfully upload a database containing several series sharing one timeline."""
    reset_database_data(DATABASE_ID)

    file_bytes = io.BytesIO(json.dumps(EXAMPLE_DATABASE).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("db.json", file_bytes, "application/json")}
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "inserted successfully" in data["message"]
    assert DATABASE_ID in data["message"]
    assert "2 series" in data["message"]


def test_upload_feeder_level_series():
    """grid_level should also accept 'Feeder', not just 'MV'/'LV'."""
    database_id = "feeder_level_db"
    reset_database_data(database_id)

    data = {
        "database_id": database_id,
        "timestamps": [NOW.isoformat()],
        "historicals": [
            {"series_id": "feeder_series", "grid_level": "Feeder", "values": [
                {"datetime": NOW.isoformat(), "power_active": 42.0}
            ]}
        ],
    }
    file_bytes = io.BytesIO(json.dumps(data).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("db.json", file_bytes, "application/json")}
    )
    assert response.status_code == 200, response.text

    get_resp = client.get(f"{HIST_PREFIX}/data/{database_id}/feeder_series")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["grid_level"] == "Feeder"


def test_upload_invalid_json():
    ensure_historical_tables()
    bad_json = io.BytesIO(b"{ invalid json }")
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("bad.json", bad_json, "application/json")}
    )
    assert response.status_code == 400
    assert "Invalid JSON format" in response.json()["detail"]


def test_upload_schema_validation_error_missing_timestamps():
    ensure_historical_tables()
    incomplete_data = {"database_id": DATABASE_ID, "historicals": []}
    file_bytes = io.BytesIO(json.dumps(incomplete_data).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("db_bad.json", file_bytes, "application/json")}
    )
    assert response.status_code == 422


def test_upload_datetime_not_in_timestamps_rejected():
    ensure_historical_tables()
    bad_data = {
        "database_id": "bad_timeline_db",
        "timestamps": [NOW.isoformat()],
        "historicals": [
            {"series_id": "s1", "grid_level": "LV", "values": [
                {"datetime": (NOW - timedelta(days=1)).isoformat(), "power_active": 1.0}
            ]}
        ],
    }
    file_bytes = io.BytesIO(json.dumps(bad_data).encode("utf-8"))
    response = client.post(
        f"{HIST_PREFIX}/", files={"file": ("db_bad.json", file_bytes, "application/json")}
    )
    assert response.status_code == 422


# ----------------------------
# Retrieval tests
# ----------------------------


def test_get_series_data():
    prepare_example_database()

    response = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/power_series")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["database_id"] == DATABASE_ID
    assert data["series_id"] == "power_series"
    assert data["grid_level"] == "LV"
    assert data["count"] == 3


def test_get_series_data_power_only_has_null_voltage():
    prepare_example_database()

    response = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/power_series")
    assert response.status_code == 200, response.text
    data = response.json()
    assert all(rec["voltage_magnitude"] is None for rec in data["records"])
    assert all(rec["power_active"] is not None for rec in data["records"])


def test_get_series_data_voltage_only_has_null_power():
    prepare_example_database()

    response = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/voltage_series")
    assert response.status_code == 200, response.text
    data = response.json()
    assert all(rec["power_active"] is None for rec in data["records"])
    assert all(rec["voltage_magnitude"] is not None for rec in data["records"])


def test_get_series_with_phase_filter():
    prepare_example_database()

    response = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/power_series?phase=R")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["records"]) == 2
    assert all(rec["phase"] == "R" for rec in data["records"])


def test_get_data_nonexistent_series():
    ensure_historical_tables()
    response = client.get(f"{HIST_PREFIX}/data/nonexistent_db_999/nonexistent_series")
    assert response.status_code == 404


def test_get_data_nonexistent_series_in_existing_database():
    prepare_example_database()
    response = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/no_such_series")
    assert response.status_code == 404


# ----------------------------
# Delete tests
# ----------------------------


def test_delete_one_series_keeps_sibling_and_database():
    """Deleting one series' records should not affect its siblings or the database itself."""
    prepare_example_database()

    response = client.delete(f"{HIST_PREFIX}/{DATABASE_ID}/power_series")
    assert response.status_code == 200, response.text
    assert "deleted" in response.json()["message"].lower()

    # Sibling series untouched
    res_sibling = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/voltage_series")
    assert res_sibling.status_code == 200
    assert res_sibling.json()["count"] == 2

    # Database page still resolves (registration survives even with 0 records for power_series)
    res_db = client.get(f"{HIST_PREFIX}/ui/{DATABASE_ID}")
    assert res_db.status_code == 200


def test_delete_whole_database_cascades():
    """Deleting a database should remove its series/records entirely."""
    prepare_example_database()

    response = client.delete(f"{HIST_PREFIX}/{DATABASE_ID}")
    assert response.status_code == 200, response.text
    assert "1 database" in response.json()["message"]

    res_series = client.get(f"{HIST_PREFIX}/data/{DATABASE_ID}/power_series")
    assert res_series.status_code == 404

    res_ui = client.get(f"{HIST_PREFIX}/ui/{DATABASE_ID}")
    assert res_ui.status_code == 404


def test_delete_nonexistent_database():
    ensure_historical_tables()
    response = client.delete(f"{HIST_PREFIX}/no_such_database_001")
    assert response.status_code == 200
    assert "0 database" in response.json()["message"]


# ----------------------------
# UI smoke tests
# ----------------------------


def test_ui_list_page_loads():
    response = client.get(f"{HIST_PREFIX}/ui")
    assert response.status_code == 200


def test_ui_database_page_loads_and_lists_series():
    prepare_example_database()
    response = client.get(f"{HIST_PREFIX}/ui/{DATABASE_ID}")
    assert response.status_code == 200


def test_ui_database_page_404_for_missing_database():
    ensure_historical_tables()
    response = client.get(f"{HIST_PREFIX}/ui/no_such_database_for_ui")
    assert response.status_code == 404


def test_ui_series_page_loads_for_existing_series():
    prepare_example_database()
    response = client.get(f"{HIST_PREFIX}/ui/{DATABASE_ID}/power_series")
    assert response.status_code == 200


def test_ui_series_page_404_for_missing_series():
    prepare_example_database()
    response = client.get(f"{HIST_PREFIX}/ui/{DATABASE_ID}/no_such_series_for_ui")
    assert response.status_code == 404

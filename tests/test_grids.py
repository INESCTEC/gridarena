import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import grid as grid_router
from gridarena.routers.grid import register_grid


@pytest.mark.asyncio
@patch("gridarena.database.insert_grid_data")
@patch("gridarena.database.create_grid_database")
@patch("gridarena.database.get_db_connection")
async def test_register_grid_unit(mock_get_conn, mock_create_db, mock_insert_db):
    # Setup mocks
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    # Simulate a valid JSON grid file
    fake_grid = {"grid_id": "grid123", "nodes": [], "connections": [], "cables": []}
    file_bytes = io.BytesIO(json.dumps(fake_grid).encode("utf-8"))
    upload = UploadFile(filename="grid.json", file=file_bytes)

    # Call function directly (no FastAPI client)
    result = await register_grid(upload)

    # Assert success message
    assert result == {"message": "Grid 'grid123' registered successfully."}

    # Assert DB functions called properly
    mock_create_db.assert_called_once_with("grid123", mock_conn, mock_cursor)
    mock_insert_db.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_register_grid_invalid_json():
    bad_json = io.BytesIO(b"{invalid_json")
    upload = UploadFile(filename="bad.json", file=bad_json)

    with pytest.raises(HTTPException) as excinfo:
        await register_grid(upload)

    assert excinfo.value.status_code == 400
    assert "Invalid JSON format" in excinfo.value.detail


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_register_grid_schema_validation_error(mock_get_conn):
    """Should raise 422 when schema validation fails."""

    bad_data = {"nodes": []}
    file_data = io.BytesIO(json.dumps(bad_data).encode("utf-8"))
    upload = UploadFile(filename="grid.json", file=file_data)

    with pytest.raises(HTTPException) as exc:
        await grid_router.register_grid(upload)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
@patch("gridarena.database.insert_grid_data", side_effect=Exception("SQL error"))
@patch("gridarena.database.create_grid_database")
@patch("gridarena.database.get_db_connection")
async def test_register_grid_db_failure(mock_get_conn, mock_create_db, mock_insert):
    """Should raise 500 if database fails."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    valid_data = {"grid_id": "grid_fail", "nodes": [], "connections": [], "cables": []}
    file_data = io.BytesIO(json.dumps(valid_data).encode("utf-8"))
    upload = UploadFile(filename="grid.json", file=file_data)

    with pytest.raises(HTTPException) as exc:
        await grid_router.register_grid(upload)

    assert exc.value.status_code == 500
    assert "Database error" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------
# delete_grid() — success and failure cases
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.database.delete_grid")
@patch("gridarena.database.get_db_connection")
async def test_delete_grid_success(mock_get_conn, mock_delete):
    """Should delete grid and close connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    result = await grid_router.delete_grid("grid_del")

    assert result == {
        "message": "Grid 'grid_del' and all associated data were deleted successfully."
    }
    mock_delete.assert_called_once_with("grid_del", mock_conn, mock_cursor)
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.delete_grid", side_effect=Exception("constraint fail"))
@patch("gridarena.database.get_db_connection")
async def test_delete_grid_db_error(mock_get_conn, mock_delete):
    """Should raise 500 if database error occurs."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await grid_router.delete_grid("grid_bad")

    assert exc.value.status_code == 500
    assert "constraint fail" in exc.value.detail
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.delete_grid", side_effect=Exception("not found"))
@patch("gridarena.database.get_db_connection")
async def test_delete_grid_generic_exception(mock_get_conn, mock_delete):
    """Should raise 500 for generic exceptions."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await grid_router.delete_grid("grid_missing")

    assert exc.value.status_code == 500
    assert "not found" in exc.value.detail.lower()
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------
# get_grid() — success, empty, and database errors
# ---------------------------------------------------------------------
@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_grid_success(mock_get_conn):
    """Should return structured data correctly."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    mock_cursor.fetchall.return_value = [
        ("PT", "grid_id_value", 38.6, -7.9, 1, "grid_ok"),
    ]
    mock_cursor.description = [
        SimpleNamespace(name="NodeId"),
        SimpleNamespace(name="grid_id"),
        SimpleNamespace(name="CoordLat"),
        SimpleNamespace(name="CoordLon"),
        SimpleNamespace(name="CoordError"),
        SimpleNamespace(name="grid_id"),
    ]

    result = await grid_router.get_grid("grid_ok", table="Node")

    assert result["table"] == "Node"
    assert result["grid_id"] == "grid_ok"
    assert isinstance(result["records"], list)
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_grid_no_results_raises_404(mock_get_conn):
    """Should raise 404 if no records found."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [SimpleNamespace(name="NodeId")]
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await grid_router.get_grid("grid_empty", table="Node")

    assert exc.value.status_code == 404
    assert "no data found" in exc.value.detail.lower()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.database.get_db_connection")
async def test_get_grid_db_error(mock_get_conn):
    """Should raise 500 if database error occurs."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("bad query")
    mock_get_conn.return_value = (mock_conn, mock_cursor)

    with pytest.raises(HTTPException) as exc:
        await grid_router.get_grid("grid_fail", table="grids")

    assert exc.value.status_code == 500
    assert "database error" in exc.value.detail.lower()
    mock_conn.close.assert_called_once()


################################################# INTEGRATION TESTS #####################################################


GRID_PREFIX = "/grid"
client = TestClient(app)

EXAMPLE_GRID = {
    "grid_id": "test_grid_001",
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


def test_register_valid_grid():
    """Should successfully register a valid grid JSON file."""
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_GRID).encode("utf-8"))
    response = client.post(
        f"{GRID_PREFIX}/",
        files={"file": ("grid.json", file_bytes, "application/json")},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "registered successfully" in data["message"]
    assert EXAMPLE_GRID["grid_id"] in data["message"]


def test_register_invalid_json():
    """Should fail if invalid JSON is uploaded."""
    bad_json = io.BytesIO(b"{ invalid json }")
    response = client.post(
        f"{GRID_PREFIX}/",
        files={"file": ("bad.json", bad_json, "application/json")},
    )
    assert response.status_code == 400
    assert "Invalid JSON format" in response.json()["detail"]


def test_get_grid_data():
    """Should retrieve grid metadata after registration."""
    grid_id = EXAMPLE_GRID["grid_id"]
    response = client.get(f"{GRID_PREFIX}/data/{grid_id}?table=grids")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["grid_id"] == grid_id
    assert data["table"] == "grids"
    assert isinstance(data["records"], list)


def test_get_grid_nodes():
    """Should retrieve node data for the grid."""
    grid_id = EXAMPLE_GRID["grid_id"]
    response = client.get(f"{GRID_PREFIX}/data/{grid_id}?table=Node")

    assert response.status_code == 200, response.text
    data = response.json()
    assert "records" in data
    assert any(node["NodeId"] == "PT" for node in data["records"])


def test_get_grid_connections():
    """Should retrieve connections data for the grid."""
    grid_id = EXAMPLE_GRID["grid_id"]
    response = client.get(f"{GRID_PREFIX}/data/{grid_id}?table=Connection")

    assert response.status_code == 200, response.text
    data = response.json()
    assert "records" in data
    assert any(connection["ConnectionId"] == "LineUID000001" for connection in data["records"])


def test_get_grid_cables():
    """Should retrieve cable data for the grid."""
    grid_id = EXAMPLE_GRID["grid_id"]
    response = client.get(f"{GRID_PREFIX}/data/{grid_id}?table=Cable")

    assert response.status_code == 200, response.text
    data = response.json()
    assert "records" in data
    assert any(cable["CableId"] == "TypeLine00001" for cable in data["records"])


def test_delete_grid():
    """Should delete the grid successfully."""
    grid_id = EXAMPLE_GRID["grid_id"]
    response = client.delete(f"{GRID_PREFIX}/{grid_id}")

    assert response.status_code == 200, response.text
    assert f"Grid '{grid_id}'" in response.json()["message"]


def test_delete_nonexistent_grid():
    """Should raise a 404 when trying to delete a non-existent grid."""
    response = client.delete(f"{GRID_PREFIX}/nonexistent_grid_9999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_register_two_grids_and_retrieve_data():
    """Should allow registering multiple grids and retrieving their respective data separately."""

    grid_a = {
        "grid_id": "grid_A",
        "nodes": [
            {"node_id": "A_PT", "coord_lat": 40.0, "coord_lon": -8.0, "coord_error": 1},
            {"node_id": "A_NODE1", "coord_lat": 40.001, "coord_lon": -8.001, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "A_CONN_1",
                "from_node_id": "A_PT",
                "to_node_id": "A_NODE1",
                "length": 100,
                "cable_id": "A_CABLE_1",
            }
        ],
        "cables": [
            {
                "cable_id": "A_CABLE_1",
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

    grid_b = {
        "grid_id": "grid_B",
        "nodes": [
            {"node_id": "B_PT", "coord_lat": 41.0, "coord_lon": -7.0, "coord_error": 1},
            {"node_id": "B_NODE1", "coord_lat": 41.001, "coord_lon": -7.001, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "B_CONN_1",
                "from_node_id": "B_PT",
                "to_node_id": "B_NODE1",
                "length": 200,
                "cable_id": "B_CABLE_1",
            }
        ],
        "cables": [
            {
                "cable_id": "B_CABLE_1",
                "r_imp_real": 0.02,
                "r_imp_imag": 0.002,
                "s_imp_real": 0.02,
                "s_imp_imag": 0.002,
                "t_imp_real": 0.02,
                "t_imp_imag": 0.002,
                "r_nom_curr": 9000,
                "s_nom_curr": 9000,
                "t_nom_curr": 9000,
            }
        ],
    }

    for grid in [grid_a, grid_b]:
        file_bytes = io.BytesIO(json.dumps(grid).encode("utf-8"))
        response = client.post(
            f"{GRID_PREFIX}/",
            files={"file": ("grid.json", file_bytes, "application/json")},
        )
        assert response.status_code == 200, response.text
        assert f"Grid '{grid['grid_id']}'" in response.json()["message"]

    res_nodes_a = client.get(f"{GRID_PREFIX}/data/{grid_a['grid_id']}?table=Node").json()
    res_conn_a = client.get(f"{GRID_PREFIX}/data/{grid_a['grid_id']}?table=Connection").json()
    res_cables_a = client.get(f"{GRID_PREFIX}/data/{grid_a['grid_id']}?table=Cable").json()

    res_nodes_b = client.get(f"{GRID_PREFIX}/data/{grid_b['grid_id']}?table=Node").json()
    res_conn_b = client.get(f"{GRID_PREFIX}/data/{grid_b['grid_id']}?table=Connection").json()
    res_cables_b = client.get(f"{GRID_PREFIX}/data/{grid_b['grid_id']}?table=Cable").json()

    # Assertions for Grid A
    assert any(n["NodeId"] == "A_PT" for n in res_nodes_a["records"])
    assert any(c["ConnectionId"] == "A_CONN_1" for c in res_conn_a["records"])
    assert any(cab["CableId"] == "A_CABLE_1" for cab in res_cables_a["records"])

    # Assertions for Grid B
    assert any(n["NodeId"] == "B_PT" for n in res_nodes_b["records"])
    assert any(c["ConnectionId"] == "B_CONN_1" for c in res_conn_b["records"])
    assert any(cab["CableId"] == "B_CABLE_1" for cab in res_cables_b["records"])

    # Ensure no cross-contamination
    node_ids_a = [n["NodeId"] for n in res_nodes_a["records"]]
    node_ids_b = [n["NodeId"] for n in res_nodes_b["records"]]
    assert not any(
        node_id in node_ids_b for node_id in node_ids_a
    ), "Grid A nodes appeared in Grid B response"

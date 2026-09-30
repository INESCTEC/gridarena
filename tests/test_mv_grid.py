import io
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gridarena.app import app
from gridarena.routers import mv_grid as mv_router

client = TestClient(app)
MV_PREFIX = "/mv_grid"


# ── Minimal valid MV grid payload ──

EXAMPLE_MV_GRID = {
    "mv_grid_id": "MV_TEST_01",
    "name": "Test MV Grid",
    "nominal_voltage_kv": 20.0,
    "region": "Test Region",
    "nodes": [
        {"node_id": "MV_SUB", "coord_lat": 41.15, "coord_lon": -8.61, "node_type": "substation"},
        {"node_id": "MV_N1", "coord_lat": 41.151, "coord_lon": -8.609},
        {"node_id": "MV_CP1", "coord_lat": 41.152, "coord_lon": -8.608, "node_type": "connection_point"},
    ],
    "cables": [
        {"cable_id": "MVC_01", "imp_real": 0.1, "imp_imag": 0.05, "nom_curr": 300.0},
    ],
    "connections": [
        {"connection_id": "MVCONN_01", "from_node_id": "MV_SUB", "to_node_id": "MV_N1", "cable_id": "MVC_01", "length": 500},
        {"connection_id": "MVCONN_02", "from_node_id": "MV_N1", "to_node_id": "MV_CP1", "cable_id": "MVC_01", "length": 300},
    ],
    "connection_points": [
        {"connection_point_id": "CP1", "node_id": "MV_CP1", "name": "Connection Point 1"},
    ],
    "transformers": [
        {
            "transformer_id": "TR1",
            "connection_point_id": "CP1",
            "rated_power_kva": 400.0,
            "primary_voltage_kv": 20.0,
            "secondary_voltage_v": 230.0,
            "imp_real": 0.004,
            "imp_imag": 0.04,
        }
    ],
}


# ═══════════════════════════════════════════════════════════════
#  Unit: _validate_mv_grid
# ═══════════════════════════════════════════════════════════════


def test_validate_mv_grid_valid():
    """Should return no errors for a valid MV grid."""
    from gridarena.schemas import MVGrid

    mv_grid = MVGrid(**EXAMPLE_MV_GRID)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert errors == []


def test_validate_mv_grid_bad_connection_node():
    """Should catch connection referencing non-existent node."""
    from gridarena.schemas import MVGrid

    payload = {**EXAMPLE_MV_GRID}
    payload["connections"] = [
        {"connection_id": "BAD", "from_node_id": "MISSING", "to_node_id": "MV_N1", "cable_id": "MVC_01", "length": 100},
    ]
    mv_grid = MVGrid(**payload)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert any("MISSING" in e for e in errors)


def test_validate_mv_grid_bad_cable_ref():
    """Should catch connection referencing non-existent cable."""
    from gridarena.schemas import MVGrid

    payload = {**EXAMPLE_MV_GRID}
    payload["connections"] = [
        {"connection_id": "BAD", "from_node_id": "MV_SUB", "to_node_id": "MV_N1", "cable_id": "NO_CABLE", "length": 100},
    ]
    mv_grid = MVGrid(**payload)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert any("NO_CABLE" in e for e in errors)


def test_validate_mv_grid_bad_cp_node():
    """Should catch connection point referencing non-existent node."""
    from gridarena.schemas import MVGrid

    payload = {**EXAMPLE_MV_GRID}
    payload["connection_points"] = [
        {"connection_point_id": "CP_BAD", "node_id": "GHOST_NODE"},
    ]
    payload["transformers"] = []
    mv_grid = MVGrid(**payload)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert any("GHOST_NODE" in e for e in errors)


def test_validate_mv_grid_duplicate_cp():
    """Should catch duplicate connection_point_id."""
    from gridarena.schemas import MVGrid

    payload = {**EXAMPLE_MV_GRID}
    payload["connection_points"] = [
        {"connection_point_id": "CP1", "node_id": "MV_CP1"},
        {"connection_point_id": "CP1", "node_id": "MV_CP1"},
    ]
    mv_grid = MVGrid(**payload)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert any("Duplicate" in e for e in errors)


def test_validate_mv_grid_transformer_voltage_mismatch():
    """Should catch transformer primary_voltage_kv not matching grid nominal."""
    from gridarena.schemas import MVGrid

    payload = {**EXAMPLE_MV_GRID}
    payload["transformers"] = [
        {
            "transformer_id": "TR_BAD",
            "connection_point_id": "CP1",
            "rated_power_kva": 400.0,
            "primary_voltage_kv": 10.0,
            "secondary_voltage_v": 230.0,
        }
    ]
    mv_grid = MVGrid(**payload)
    errors = mv_router._validate_mv_grid(mv_grid)
    assert any("primary_voltage_kv" in e for e in errors)


# ═══════════════════════════════════════════════════════════════
#  Unit: _compute_graph_layout
# ═══════════════════════════════════════════════════════════════


def test_compute_graph_layout_returns_nodes_and_edges():
    """Should return graph structure with correct count."""
    grid_data = {
        "nodes": [
            {"node_id": "A", "coord_lat": 1.0, "coord_lon": 2.0, "node_type": "substation"},
            {"node_id": "B", "coord_lat": 1.1, "coord_lon": 2.1},
        ],
        "connections": [
            {"connection_id": "C1", "from_node_id": "A", "to_node_id": "B"},
        ],
        "connection_points": [],
        "transformers": [],
    }
    result = mv_router._compute_graph_layout(grid_data)
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    assert all("x" in n and "y" in n for n in result["nodes"])


# ═══════════════════════════════════════════════════════════════
#  Unit: validate_mv_grid endpoint
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_endpoint_valid():
    """Should return valid=True for a well-formed grid."""
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_MV_GRID).encode("utf-8"))
    upload = UploadFile(filename="mv.json", file=file_bytes)
    result = await mv_router.validate_mv_grid(upload)
    assert result["valid"] is True
    assert "graph" in result


@pytest.mark.asyncio
async def test_validate_endpoint_invalid_json():
    """Should raise 400 for invalid JSON."""
    file_bytes = io.BytesIO(b"{ bad json }")
    upload = UploadFile(filename="bad.json", file=file_bytes)
    with pytest.raises(HTTPException) as exc:
        await mv_router.validate_mv_grid(upload)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_endpoint_schema_error():
    """Should raise 422 for schema validation failure."""
    file_bytes = io.BytesIO(json.dumps({"mv_grid_id": "X"}).encode("utf-8"))
    upload = UploadFile(filename="bad.json", file=file_bytes)
    with pytest.raises(HTTPException) as exc:
        await mv_router.validate_mv_grid(upload)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_validate_endpoint_validation_errors():
    """Should return valid=False when internal references are broken."""
    payload = {**EXAMPLE_MV_GRID}
    payload["connections"] = [
        {"connection_id": "BAD", "from_node_id": "MISSING", "to_node_id": "MV_N1", "cable_id": "MVC_01", "length": 100},
    ]
    file_bytes = io.BytesIO(json.dumps(payload).encode("utf-8"))
    upload = UploadFile(filename="mv.json", file=file_bytes)
    result = await mv_router.validate_mv_grid(upload)
    assert result["valid"] is False
    assert len(result["errors"]) > 0


# ═══════════════════════════════════════════════════════════════
#  Unit: register_mv_grid
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.insert_mv_grid_data")
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_register_mv_grid_success(mock_get_db, mock_create, mock_insert):
    """Should register a valid MV grid successfully."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    file_bytes = io.BytesIO(json.dumps(EXAMPLE_MV_GRID).encode("utf-8"))
    upload = UploadFile(filename="mv.json", file=file_bytes)
    result = await mv_router.register_mv_grid(upload)

    assert "registered successfully" in result["message"]
    mock_create.assert_called_once()
    mock_insert.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.insert_mv_grid_data", side_effect=Exception("SQL error"))
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_register_mv_grid_db_error(mock_get_db, mock_create, mock_insert):
    """Should raise 500 on DB error."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    file_bytes = io.BytesIO(json.dumps(EXAMPLE_MV_GRID).encode("utf-8"))
    upload = UploadFile(filename="mv.json", file=file_bytes)

    with pytest.raises(HTTPException) as exc:
        await mv_router.register_mv_grid(upload)
    assert exc.value.status_code == 500
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: delete_mv_grid
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.delete_mv_grid")
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_delete_mv_grid_success(mock_get_db, mock_create, mock_delete):
    """Should delete grid and return confirmation."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    result = await mv_router.delete_mv_grid("MV_DEL")
    assert "deleted" in result["message"].lower()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.delete_mv_grid", side_effect=Exception("FK violation"))
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_delete_mv_grid_db_error(mock_get_db, mock_create, mock_delete):
    """Should raise 500 if delete fails."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    with pytest.raises(HTTPException) as exc:
        await mv_router.delete_mv_grid("MV_BAD")
    assert exc.value.status_code == 500
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: list_mv_grids
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.get_mv_grid_list", return_value=[{"mv_grid_id": "G1"}])
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_list_mv_grids_success(mock_get_db, mock_create, mock_list):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    result = await mv_router.list_mv_grids()
    assert len(result) == 1
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: get_mv_grid
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.get_mv_grid_detail", return_value={"mv_grid_id": "G1", "nodes": []})
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_get_mv_grid_success(mock_get_db, mock_create, mock_detail):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    result = await mv_router.get_mv_grid("G1")
    assert result["mv_grid_id"] == "G1"
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.get_mv_grid_detail", side_effect=Exception("not found"))
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_get_mv_grid_not_found(mock_get_db, mock_create, mock_detail):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    with pytest.raises(HTTPException) as exc:
        await mv_router.get_mv_grid("MISSING")
    assert exc.value.status_code == 500
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: connect / disconnect LV grid
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.connect_lv_to_mv")
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_connect_lv_grid_success(mock_get_db, mock_create, mock_connect):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    from gridarena.schemas import ConnectLVRequest
    req = ConnectLVRequest(lv_grid_id="LV_01")

    result = await mv_router.connect_lv_grid("MV_01", "CP1", req)
    assert "connected" in result["message"].lower()
    mock_connect.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.connect_lv_to_mv", side_effect=Exception("already connected"))
@patch("gridarena.routers.mv_grid.db.create_mv_database")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_connect_lv_grid_error(mock_get_db, mock_create, mock_connect):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    from gridarena.schemas import ConnectLVRequest
    req = ConnectLVRequest(lv_grid_id="LV_01")

    with pytest.raises(HTTPException) as exc:
        await mv_router.connect_lv_grid("MV_01", "CP1", req)
    assert exc.value.status_code == 400
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.disconnect_lv_from_mv")
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_disconnect_lv_grid_success(mock_get_db, mock_disconnect):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    result = await mv_router.disconnect_lv_grid("MV_01", "CP1", "LV_01")
    assert "disconnected" in result["message"].lower()
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: get_lv_aggregated_pv
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.get_aggregated_pv", return_value=[{"ts": "t1", "avg_p": 10, "avg_v": 230}])
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_get_lv_aggregated_pv_success(mock_get_db, mock_pv):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    cursor.fetchone.side_effect = [(1,), (5,)]

    result = await mv_router.get_lv_aggregated_pv("MV_01", "LV_01")
    assert result["lv_grid_id"] == "LV_01"
    assert result["count"] == 1
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.mv_grid.db.get_db_connection")
async def test_get_lv_aggregated_pv_not_connected(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = None

    with pytest.raises(HTTPException) as exc:
        await mv_router.get_lv_aggregated_pv("MV_01", "LV_MISSING")
    assert exc.value.status_code == 404
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Integration tests
# ═══════════════════════════════════════════════════════════════


def test_register_valid_mv_grid():
    """Should register a valid MV grid through the API."""
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_MV_GRID).encode("utf-8"))
    response = client.post(
        f"{MV_PREFIX}/",
        files={"file": ("mv.json", file_bytes, "application/json")},
    )
    assert response.status_code == 200, response.text
    assert "registered successfully" in response.json()["message"]


def test_register_invalid_json():
    """Should fail with 400 for invalid JSON."""
    bad = io.BytesIO(b"{ broken }")
    response = client.post(
        f"{MV_PREFIX}/",
        files={"file": ("bad.json", bad, "application/json")},
    )
    assert response.status_code == 400


def test_validate_mv_grid_endpoint():
    """Should validate an MV grid via API without saving."""
    file_bytes = io.BytesIO(json.dumps(EXAMPLE_MV_GRID).encode("utf-8"))
    response = client.post(
        f"{MV_PREFIX}/validate",
        files={"file": ("mv.json", file_bytes, "application/json")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["valid"] is True
    assert "graph" in data
    assert len(data["graph"]["nodes"]) == 3
    assert len(data["graph"]["edges"]) == 2


def test_list_mv_grids_integration():
    """Should list MV grids including the one we just registered."""
    response = client.get(f"{MV_PREFIX}/list")
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data, list)
    assert any(g.get("mv_grid_id") == EXAMPLE_MV_GRID["mv_grid_id"] for g in data)


def test_get_mv_grid_detail_integration():
    """Should retrieve the full MV grid detail."""
    grid_id = EXAMPLE_MV_GRID["mv_grid_id"]
    response = client.get(f"{MV_PREFIX}/data/{grid_id}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mv_grid_id"] == grid_id
    assert "nodes" in data


def test_delete_mv_grid_integration():
    """Should delete the MV grid."""
    grid_id = EXAMPLE_MV_GRID["mv_grid_id"]
    response = client.delete(f"{MV_PREFIX}/{grid_id}")
    assert response.status_code == 200, response.text
    assert "deleted" in response.json()["message"].lower()

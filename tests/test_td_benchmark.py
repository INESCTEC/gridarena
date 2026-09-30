import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
import gridarena.routers.topology_discovery_benchmark as topo_router

GRID_ID = "grid_test_001"
USER_ID = "user_123"


# ===============================================================
#  GET /training-topology-data
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.pi.get_all_measurements")
@patch("gridarena.routers.topology_discovery_benchmark.td.get_all_grids_topology")
async def test_get_training_topology_data_success(mock_get_topo, mock_get_meas, mock_get_db):
    """Should return grid measurement + topology data successfully."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_meas.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1),
        (GRID_ID, "NODE2", "S", "2025-01-01T00:00:00", 12.0, 6.0, 231.0, 0.2),
    ]
    mock_get_topo.return_value = (
        {"grid_test_001": {"NODE1": 0, "NODE2": 1}},
        {"grid_test_001": [(0, 1)]},
        {"grid_test_001": {"(0,1)": {"Length": 100}}},
    )

    result = await topo_router.get_topology_identification_data()

    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "node to corresponding index" in result
    assert "topology (index)" in result
    assert "conn_data" in result

    mock_get_meas.assert_called_once()
    mock_get_topo.assert_called_once()
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.pi.get_all_measurements")
@patch("gridarena.routers.topology_discovery_benchmark.td.get_all_grids_topology")
async def test_training_topology_data_deterministic(mock_get_topo, mock_get_meas, mock_get_db):
    """Same difficulty should produce identical noise across calls."""
    def setup_mocks():
        conn = MagicMock()
        cursor = MagicMock()
        mock_get_db.return_value = (conn, cursor)
        mock_get_meas.return_value = [
            (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1),
        ]
        mock_get_topo.return_value = (
            {GRID_ID: {"NODE1": 0}},
            {GRID_ID: [(0, 1)]},
            {GRID_ID: [("CBL1", 100.0)]},
        )

    setup_mocks()
    r1 = await topo_router.get_topology_identification_data(difficulty="easy")
    setup_mocks()
    r2 = await topo_router.get_topology_identification_data(difficulty="easy")

    m1 = r1["grids"][GRID_ID]["NODE1"][0]
    m2 = r2["grids"][GRID_ID]["NODE1"][0]
    assert m1["power_active"] == m2["power_active"]
    assert m1["voltage_magnitude"] == m2["voltage_magnitude"]


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.pi.get_all_measurements")
@patch("gridarena.routers.topology_discovery_benchmark.td.get_all_grids_topology")
async def test_get_training_topology_data_db_error(mock_get_topo, mock_get_meas, mock_get_db):
    """Should raise HTTP 500 on DB error."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    mock_get_meas.side_effect = Exception("DB fail")

    with pytest.raises(HTTPException) as exc:
        await topo_router.get_topology_identification_data()
    assert exc.value.status_code == 500
    assert "DB fail" in exc.value.detail
    conn.close.assert_called_once()


# ===============================================================
#  GET /topology-data
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.pi.get_all_measurements")
async def test_get_topology_data_success(mock_get_meas, mock_get_db):
    """Should return hidden topology data."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    mock_get_meas.return_value = [
        (GRID_ID, "NODE1", "R", "2025-01-01T00:00:00", 10.0, 5.0, 230.0, 0.1)
    ]

    result = await topo_router.get_topology_discovery_data()

    assert "grids" in result
    assert GRID_ID in result["grids"]
    assert "NODE1" in result["grids"][GRID_ID]

    conn.commit.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.pi.get_all_measurements")
async def test_get_topology_data_sql_error(mock_get_meas, mock_get_db):
    """Should raise HTTP 500 if DB throws."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    mock_get_meas.side_effect = Exception("SQL error")

    with pytest.raises(HTTPException) as exc:
        await topo_router.get_topology_discovery_data()
    assert exc.value.status_code == 500
    assert "SQL error" in exc.value.detail
    conn.close.assert_called_once()


# ===============================================================
#  POST /submit-results
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
async def test_submit_topology_guesses_success(mock_get_db):
    """Should insert topology guess successfully."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # resolve_real_grid_id returns None (passthrough), grid exists check returns a row
    cursor.fetchone.side_effect = [None, (1,)]

    topo_guess = MagicMock()
    topo_guess.guess_id = USER_ID
    topo_guess.grid_id = GRID_ID
    topo_guess.guesses = [[0, 1], [1, 2], [2, 3]]

    result = await topo_router.submit_topology_guesses(topo_guess)

    # resolve query + grid exists check + insert = 3
    assert cursor.execute.call_count == 3
    conn.commit.assert_called_once()
    conn.close.assert_called_once()
    assert result["status"] == "submitted"
    assert result["accepted_edges"] == 3


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
async def test_submit_topology_guesses_db_error(mock_get_db):
    """Should raise HTTP 500 if DB fails."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL failure")

    topo_guess = MagicMock()
    topo_guess.guess_id = USER_ID
    topo_guess.grid_id = GRID_ID
    topo_guess.guesses = [[0, 1]]

    with pytest.raises(HTTPException) as exc:
        await topo_router.submit_topology_guesses(topo_guess)
    assert exc.value.status_code == 500
    assert "SQL failure" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
async def test_submit_topology_guesses_invalid_grid(mock_get_db):
    """Should raise HTTP 422 for nonexistent grid."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # resolve_real_grid_id returns None (passthrough), grid exists check returns None
    cursor.fetchone.side_effect = [None, None]

    topo_guess = MagicMock()
    topo_guess.guess_id = USER_ID
    topo_guess.grid_id = "nonexistent_grid"
    topo_guess.guesses = [[0, 1]]

    with pytest.raises(HTTPException) as exc:
        await topo_router.submit_topology_guesses(topo_guess)
    assert exc.value.status_code == 422
    conn.close.assert_called_once()


# ===============================================================
#  GET /score
# ===============================================================
@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
@patch("gridarena.routers.topology_discovery_benchmark.gd.get_nodes_from_grid")
@patch("gridarena.routers.topology_discovery_benchmark.gd.get_grid_connections")
async def test_get_score_computes_accuracy(mock_get_conn, mock_get_nodes, mock_get_db):
    """Should compute accuracy correctly."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)

    # First query: guessed_topology
    cursor.fetchone.side_effect = [
        (json.dumps([[0, 1], [1, 2]]),),
    ]
    mock_get_nodes.return_value = {"NODE1": 0, "NODE2": 1, "NODE3": 2}
    mock_get_conn.return_value = ([(0, 1), (1, 2)], {"(0,1)": {}, "(1,2)": {}})

    result = await topo_router.get_score(USER_ID, GRID_ID)

    assert result["correct"] == 2
    assert result["accuracy"] == 1.0
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.topology_discovery_benchmark.db.get_db_connection")
async def test_get_score_db_error(mock_get_db):
    """Should raise HTTP 500 on DB failure and call rollback."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("SQL error")

    with pytest.raises(HTTPException) as exc:
        await topo_router.get_score(USER_ID, GRID_ID)
    assert exc.value.status_code == 500
    assert "SQL error" in exc.value.detail
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


# ----------------------------------------------------------------------------------------
# Integration-style tests (real FastAPI + backing DB via app)
# ----------------------------------------------------------------------------------------

client = TestClient(app)
BENCH_PREFIX = "/topology_discovery_benchmark"
USER_ID = "user_topo_123"


def _setup_topology_grid(grid_id: str):
    """Create a minimal grid + historical data via public API endpoints."""

    # Grid definition with simple radial topology
    grid_payload = {
        "grid_id": grid_id,
        "nodes": [
            {"node_id": "PT", "coord_lat": 38.65, "coord_lon": -7.98, "coord_error": 1},
            {"node_id": "NODE1", "coord_lat": 38.651, "coord_lon": -7.981, "coord_error": 1},
            {"node_id": "NODE2", "coord_lat": 38.652, "coord_lon": -7.982, "coord_error": 1},
            {"node_id": "NODE3", "coord_lat": 38.653, "coord_lon": -7.983, "coord_error": 1},
        ],
        "connections": [
            {
                "connection_id": "Line001",
                "from_node_id": "PT",
                "to_node_id": "NODE1",
                "length": 1000,
                "cable_id": "TypeLine00001",
            },
            {
                "connection_id": "Line002",
                "from_node_id": "NODE1",
                "to_node_id": "NODE2",
                "length": 800,
                "cable_id": "TypeLine00001",
            },
            {
                "connection_id": "Line003",
                "from_node_id": "NODE2",
                "to_node_id": "NODE3",
                "length": 600,
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
                        "phase": "R",
                        "power_active": 11.0,
                        "power_reactive": 4.5,
                        "voltage_magnitude": 229.5,
                        "voltage_angle": -1.0,
                    }
                ],
            },
            {
                "node_id": "NODE3",
                "measurements": [
                    {
                        "datetime": now,
                        "phase": "R",
                        "power_active": 9.5,
                        "power_reactive": 4.0,
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
# Integration: GET /training-topology-data
# -----------------------------------------------------------
def test_get_training_topology_data_integration():
    """Should return combined measurement and topology data."""
    grid_id = "topo_grid_train_pg1"
    _setup_topology_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/training-topology-data")
    assert response.status_code == 200, response.text

    data = response.json()
    assert "grids" in data
    assert grid_id in data["grids"]
    assert isinstance(data["grids"][grid_id], dict)


# -----------------------------------------------------------
# Integration: GET /topology-data
# -----------------------------------------------------------
def test_get_topology_data_integration():
    """Should return hidden topology data."""
    grid_id = "topo_grid_data_pg1"
    _setup_topology_grid(grid_id)

    response = client.get(f"{BENCH_PREFIX}/topology-data")
    assert response.status_code == 200, response.text

    data = response.json()
    assert "grids" in data
    assert grid_id in data["grids"]
    assert len(data["grids"][grid_id]) > 0


# -----------------------------------------------------------
# Integration: POST /submit-results
# -----------------------------------------------------------
def test_submit_topology_guesses_integration():
    """Should submit guessed connections successfully."""
    grid_id = "topo_grid_submit_pg1"
    _setup_topology_grid(grid_id)

    # Use a simple guess; structure is validated and stored
    payload = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": [[0, 1], [1, 2]],
    }

    response = client.post(f"{BENCH_PREFIX}/submit-results", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted"


# -----------------------------------------------------------
# Integration: GET /score
# -----------------------------------------------------------
def test_get_score_integration():
    """Should compute topology accuracy correctly."""
    grid_id = "topo_grid_score_pg1"
    _setup_topology_grid(grid_id)

    # Get true topology in index space from training endpoint
    training_resp = client.get(f"{BENCH_PREFIX}/training-topology-data")
    assert training_resp.status_code == 200, training_resp.text
    training_data = training_resp.json()

    topo_by_grid = training_data["topology (index)"]
    assert grid_id in topo_by_grid
    true_edges = topo_by_grid[grid_id]
    assert isinstance(true_edges, list)
    assert len(true_edges) > 0

    # Submit a perfect guess equal to true topology
    payload = {
        "guess_id": USER_ID,
        "grid_id": grid_id,
        "guesses": true_edges,
    }
    submit_resp = client.post(f"{BENCH_PREFIX}/submit-results", json=payload)
    assert submit_resp.status_code == 200, submit_resp.text

    # Now score should be 1.0 accuracy
    response = client.get(f"{BENCH_PREFIX}/score?guess_id={USER_ID}&grid_id={grid_id}")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["grid_id"] == grid_id
    assert data["total_true_edges"] == len(true_edges)
    assert data["correct"] == len(true_edges)
    assert data["accuracy"] == 1.0

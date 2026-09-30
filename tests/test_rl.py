import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import rl as rl_router
from gridarena.rl.schemas import RunStatus, TrainRequest, EvaluateRequest

client = TestClient(app)
RL_PREFIX = "/rl"


# ═══════════════════════════════════════════════════════════════
#  Unit: start_training
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
@patch("gridarena.routers.rl.build_grid_config_from_db")
@patch("gridarena.routers.rl.db.get_db_connection")
async def test_start_training_success(mock_get_db, mock_build, mock_registry):
    """Should start a training run and return run_id."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = (1,)

    mock_config = MagicMock()
    mock_config.to_dict.return_value = {"n_nodes": 5}
    mock_build.return_value = mock_config
    mock_registry.start_training.return_value = "abc12345"

    request = TrainRequest(grid_id="test_grid", timesteps=1000)
    result = await rl_router.start_training(request)

    assert result.run_id == "abc12345"
    assert result.status == "queued"
    mock_build.assert_called_once()
    mock_registry.start_training.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.rl.db.get_db_connection")
async def test_start_training_grid_not_found(mock_get_db):
    """Should raise 404 if grid doesn't exist."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = None

    request = TrainRequest(grid_id="missing_grid", timesteps=1000)
    with pytest.raises(HTTPException) as exc:
        await rl_router.start_training(request)
    assert exc.value.status_code == 404
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: list_runs
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_list_runs(mock_registry):
    """Should return list of runs as dicts."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="completed", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.list_runs.return_value = [run]

    result = await rl_router.list_runs()
    assert len(result) == 1
    assert result[0]["run_id"] == "r1"
    assert result[0]["status"] == "completed"


# ═══════════════════════════════════════════════════════════════
#  Unit: get_run
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_get_run_success(mock_registry):
    """Should return run details."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="completed", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.get_run.return_value = run

    result = await rl_router.get_run("r1")
    assert result["run_id"] == "r1"


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_get_run_not_found(mock_registry):
    """Should raise 404 for unknown run_id."""
    mock_registry.get_run.return_value = None

    with pytest.raises(HTTPException) as exc:
        await rl_router.get_run("missing")
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Unit: download_model
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_download_model_not_completed(mock_registry):
    """Should raise 404 if run is not completed."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="running", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.get_run.return_value = run

    with pytest.raises(HTTPException) as exc:
        await rl_router.download_model("r1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_download_model_not_found(mock_registry):
    """Should raise 404 for unknown run."""
    mock_registry.get_run.return_value = None

    with pytest.raises(HTTPException) as exc:
        await rl_router.download_model("missing")
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Unit: evaluate_run
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_evaluate_run_not_completed(mock_registry):
    """Should raise 400 if run not completed."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="queued", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.get_run.return_value = run

    with pytest.raises(HTTPException) as exc:
        await rl_router.evaluate_run("r1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_evaluate_run_success(mock_registry):
    """Should evaluate model and return result."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="completed", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.get_run.return_value = run
    mock_registry.get_run_dir.return_value = Path("/fake/run/dir")

    with patch("gridarena.rl.evaluation.evaluate_model", return_value={"voltages": [230.0]}):
        result = await rl_router.evaluate_run("r1")
    assert "voltages" in result


@pytest.mark.asyncio
@patch("gridarena.routers.rl.registry")
async def test_evaluate_run_failure(mock_registry):
    """Should raise 500 if evaluation fails."""
    run = RunStatus(
        run_id="r1", grid_id="g1", agent_type="single",
        status="completed", created_at="2025-01-01T00:00:00", timesteps=5000,
    )
    mock_registry.get_run.return_value = run
    mock_registry.get_run_dir.return_value = Path("/fake/run/dir")

    with patch("gridarena.rl.evaluation.evaluate_model", side_effect=Exception("eval crash")):
        with pytest.raises(HTTPException) as exc:
            await rl_router.evaluate_run("r1")
        assert exc.value.status_code == 500


# ═══════════════════════════════════════════════════════════════
#  Unit: _fetch_grid_ids
# ═══════════════════════════════════════════════════════════════


@patch("gridarena.routers.rl.db.get_db_connection")
def test_fetch_grid_ids_success(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchall.return_value = [("g1",), ("g2",)]

    result = rl_router._fetch_grid_ids()
    assert result == ["g1", "g2"]
    conn.close.assert_called_once()


@patch("gridarena.routers.rl.db.get_db_connection")
def test_fetch_grid_ids_db_error(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("fail")

    result = rl_router._fetch_grid_ids()
    assert result == []
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Integration: API endpoints
# ═══════════════════════════════════════════════════════════════


def test_list_runs_integration():
    """Should return a list (possibly empty) of RL runs."""
    response = client.get(f"{RL_PREFIX}/runs")
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_get_run_not_found_integration():
    """Should return 404 for non-existent run."""
    response = client.get(f"{RL_PREFIX}/runs/nonexistent_run_999")
    assert response.status_code == 404


def test_download_model_not_found_integration():
    """Should return 404 for non-existent run model."""
    response = client.get(f"{RL_PREFIX}/runs/nonexistent_run_999/model")
    assert response.status_code == 404


def test_start_training_missing_grid_integration():
    """Should return 404 when grid doesn't exist."""
    payload = {
        "grid_id": "nonexistent_grid_rl_999",
        "agent_type": "single",
        "timesteps": 1000,
    }
    response = client.post(f"{RL_PREFIX}/train", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_start_training_invalid_timesteps():
    """Should return 422 for timesteps below minimum."""
    payload = {
        "grid_id": "some_grid",
        "timesteps": 10,
    }
    response = client.post(f"{RL_PREFIX}/train", json=payload)
    assert response.status_code == 422

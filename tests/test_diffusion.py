import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gridarena.app import app
from gridarena.routers import diffusion as diff_router
from gridarena.diffusion.schemas import (
    DiffusionRunStatus,
    DiffusionTrainRequest,
    GenerateSnapshotRequest,
)

client = TestClient(app)
DIFF_PREFIX = "/diffusion"


# ═══════════════════════════════════════════════════════════════
#  Unit: start_diffusion_training
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
@patch("gridarena.routers.diffusion.db.get_db_connection")
async def test_start_training_success(mock_get_db, mock_registry):
    """Should start a diffusion training run."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = (1,)

    mock_registry.start_training.return_value = "diff_001"

    request = DiffusionTrainRequest(grid_ids=["g1"], num_epochs=10)
    result = await diff_router.start_diffusion_training(request)

    assert result.run_id == "diff_001"
    assert result.status == "queued"
    mock_registry.start_training.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.db.get_db_connection")
async def test_start_training_grid_not_found(mock_get_db):
    """Should raise 404 if any grid doesn't exist."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.return_value = None

    request = DiffusionTrainRequest(grid_ids=["missing_grid"], num_epochs=10)
    with pytest.raises(HTTPException) as exc:
        await diff_router.start_diffusion_training(request)
    assert exc.value.status_code == 404
    conn.close.assert_called_once()


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.db.get_db_connection")
async def test_start_training_multiple_grids_one_missing(mock_get_db):
    """Should raise 404 if second grid doesn't exist."""
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchone.side_effect = [(1,), None]

    request = DiffusionTrainRequest(grid_ids=["g1", "missing"], num_epochs=10)
    with pytest.raises(HTTPException) as exc:
        await diff_router.start_diffusion_training(request)
    assert exc.value.status_code == 404
    assert "missing" in exc.value.detail
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Unit: list_diffusion_runs
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_list_runs(mock_registry):
    """Should return list of runs."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="completed",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.list_runs.return_value = [run]

    result = await diff_router.list_diffusion_runs()
    assert len(result) == 1
    assert result[0]["run_id"] == "d1"


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_list_runs_empty(mock_registry):
    """Should return empty list when no runs exist."""
    mock_registry.list_runs.return_value = []

    result = await diff_router.list_diffusion_runs()
    assert result == []


# ═══════════════════════════════════════════════════════════════
#  Unit: get_diffusion_run
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_get_run_success(mock_registry):
    """Should return run details."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="completed",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.get_run.return_value = run

    result = await diff_router.get_diffusion_run("d1")
    assert result["run_id"] == "d1"
    assert result["status"] == "completed"


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_get_run_not_found(mock_registry):
    """Should raise 404 for unknown run."""
    mock_registry.get_run.return_value = None

    with pytest.raises(HTTPException) as exc:
        await diff_router.get_diffusion_run("missing")
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Unit: download_diffusion_model
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_download_model_not_completed(mock_registry):
    """Should raise 404 if run not completed."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="running",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.get_run.return_value = run

    with pytest.raises(HTTPException) as exc:
        await diff_router.download_diffusion_model("d1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_download_model_missing_run(mock_registry):
    """Should raise 404 for unknown run."""
    mock_registry.get_run.return_value = None

    with pytest.raises(HTTPException) as exc:
        await diff_router.download_diffusion_model("missing")
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Unit: generate_snapshot
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_generate_snapshot_not_completed(mock_registry):
    """Should raise 400 if run is not completed."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="queued",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.get_run.return_value = run

    with pytest.raises(HTTPException) as exc:
        await diff_router.generate_snapshot("d1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_generate_snapshot_success(mock_registry):
    """Should generate snapshot from trained model."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="completed",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.get_run.return_value = run
    mock_registry.get_run_dir.return_value = Path("/fake/dir")

    with patch("gridarena.diffusion.model_core.generate_snapshot", return_value={"snapshot": [[1.0, 2.0]]}):
        result = await diff_router.generate_snapshot("d1")
    assert "snapshot" in result


@pytest.mark.asyncio
@patch("gridarena.routers.diffusion.diffusion_registry")
async def test_generate_snapshot_failure(mock_registry):
    """Should raise 500 if generation fails."""
    run = DiffusionRunStatus(
        run_id="d1", grid_ids=["g1"], status="completed",
        created_at="2025-01-01T00:00:00", num_epochs=75,
    )
    mock_registry.get_run.return_value = run
    mock_registry.get_run_dir.return_value = Path("/fake/dir")

    with patch("gridarena.diffusion.model_core.generate_snapshot", side_effect=Exception("CUDA error")):
        with pytest.raises(HTTPException) as exc:
            await diff_router.generate_snapshot("d1")
        assert exc.value.status_code == 500


# ═══════════════════════════════════════════════════════════════
#  Unit: _fetch_grid_ids
# ═══════════════════════════════════════════════════════════════


@patch("gridarena.routers.diffusion.db.get_db_connection")
def test_fetch_grid_ids_success(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.fetchall.return_value = [("g1",), ("g2",)]

    result = diff_router._fetch_grid_ids()
    assert result == ["g1", "g2"]
    conn.close.assert_called_once()


@patch("gridarena.routers.diffusion.db.get_db_connection")
def test_fetch_grid_ids_db_error(mock_get_db):
    conn = MagicMock()
    cursor = MagicMock()
    mock_get_db.return_value = (conn, cursor)
    cursor.execute.side_effect = Exception("db fail")

    result = diff_router._fetch_grid_ids()
    assert result == []
    conn.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Integration: API endpoints
# ═══════════════════════════════════════════════════════════════


def test_list_runs_integration():
    """Should return a list (possibly empty) of diffusion runs."""
    response = client.get(f"{DIFF_PREFIX}/runs")
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_get_run_not_found_integration():
    """Should return 404 for non-existent run."""
    response = client.get(f"{DIFF_PREFIX}/runs/nonexistent_999")
    assert response.status_code == 404


def test_download_model_not_found_integration():
    """Should return 404 for non-existent run model."""
    response = client.get(f"{DIFF_PREFIX}/runs/nonexistent_999/model")
    assert response.status_code == 404


def test_start_training_missing_grid_integration():
    """Should return 404 when grid doesn't exist."""
    payload = {
        "grid_ids": ["nonexistent_grid_diff_999"],
        "num_epochs": 10,
    }
    response = client.post(f"{DIFF_PREFIX}/train", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_start_training_empty_grid_ids():
    """Should return 422 when grid_ids is empty."""
    payload = {
        "grid_ids": [],
        "num_epochs": 10,
    }
    response = client.post(f"{DIFF_PREFIX}/train", json=payload)
    assert response.status_code == 422


def test_start_training_invalid_epochs():
    """Should return 422 for epochs out of range."""
    payload = {
        "grid_ids": ["some_grid"],
        "num_epochs": 0,
    }
    response = client.post(f"{DIFF_PREFIX}/train", json=payload)
    assert response.status_code == 422


def test_generate_not_found_integration():
    """Should return 400/404 for non-existent run generation."""
    response = client.post(f"{DIFF_PREFIX}/generate/nonexistent_999")
    assert response.status_code in (400, 404)

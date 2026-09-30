import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gridarena.app import app  # Adjust the import according to your project structure


@pytest.fixture
def client():
    return TestClient(app)


def test_register_grid_valid(client):
    """Test for registering a grid with a valid JSON file."""

    # Define the path to the test grid file
    grid_file_path = os.path.join(os.path.dirname(__file__), "test_files", "mock_grid.json")

    # Read the file content
    with open(grid_file_path, "rb") as f:
        grid_file_content = f.read()

    # Test the POST request to register a grid
    response = client.post("/grid/", files={"file": ("mock_grid.json", grid_file_content)})

    assert response.status_code == 200
    assert "Grid 'grid001' registered successfully." in response.json()["message"]


def test_get_grid(client):
    """Test for retrieving grid data from the database."""

    # Test the GET request to retrieve grid data (e.g., Node table)
    response = client.get("/grid/data/grid001?table=Node")
    print(response.json())
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["table"] == "Node"
    assert response_data["grid_id"] == "grid001"
    assert len(response_data["records"]) == 6  # We have 6 mock nodes
    assert response_data["records"][0]["NodeId"] == "PT"


def test_delete_grid(client):
    """Test for deleting a grid."""

    # Test the DELETE request to delete a grid
    response = client.delete("/grid/grid001")

    assert response.status_code == 200
    assert (
        "Grid 'grid001' and all associated data were deleted successfully."
        in response.json()["message"]
    )

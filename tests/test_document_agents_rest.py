"""LLM-17: REST CRUD surface for document assistants."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gridarena.app import app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "document_agents"
CHAT_PREFIX = "/chat"

client = TestClient(app)


def _config(tmp_path):
    return {
        "allow_document_agents": True,
        "data_dir": tmp_path / "data",
        "chroma_db_path": tmp_path / "chroma_db",
        "max_source_mb": 5,
        "max_sources_per_agent": 20,
        "doc_chunks_per_answer": 3,
        "api_key": "k", "api_url": "http://fake", "model": "m",
        "verify_ssl": False, "temperature": 0.3,
        "max_tokens_with_tools": 2000, "max_tokens_interpretation": 800,
    }


def _paper_file():
    return ("files", ("paper.md", (FIXTURES_DIR / "paper.md").read_bytes(), "text/markdown"))


@pytest.fixture
def cfg(tmp_path):
    config = _config(tmp_path)
    with patch("gridarena.llm.config.get_llm_config", return_value=config):
        yield config


def test_create_agent_with_files_ingests_and_returns_manifest(cfg):
    resp = client.post(
        f"{CHAT_PREFIX}/agents",
        data={"name": "Paper Agent", "description": "A test agent"},
        files=[_paper_file()],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["agent"]["name"] == "Paper Agent"
    assert len(data["agent"]["sources"]) == 1
    assert data["agent"]["sources"][0]["filename"] == "paper.md"

    assert len(data["files"]) == 1
    assert data["files"][0]["status"] == "ingested"


def test_create_agent_requires_a_name(cfg):
    resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "   "})
    assert resp.status_code == 422


def test_create_agent_allows_no_files(cfg):
    resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "Empty Agent"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["agent"]["sources"] == []
    assert data["files"] == []


def test_create_agent_reports_per_file_rejection_without_failing_the_whole_call(cfg):
    resp = client.post(
        f"{CHAT_PREFIX}/agents",
        data={"name": "Mixed Agent"},
        files=[
            _paper_file(),
            ("files", ("notes.pdf", b"%PDF-1.4 fake", "application/pdf")),
        ],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    statuses = {f["filename"]: f["status"] for f in data["files"]}
    assert statuses["paper.md"] == "ingested"
    assert statuses["notes.pdf"] == "rejected"
    # the good file still landed in the manifest despite the bad one
    assert len(data["agent"]["sources"]) == 1


def test_list_and_get_agent(cfg):
    create_resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "Listed Agent"}, files=[_paper_file()])
    agent_id = create_resp.json()["agent"]["agent_id"]

    list_resp = client.get(f"{CHAT_PREFIX}/agents")
    assert list_resp.status_code == 200
    names = [a["name"] for a in list_resp.json()["agents"]]
    assert "Listed Agent" in names

    get_resp = client.get(f"{CHAT_PREFIX}/agents/{agent_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["agent_id"] == agent_id


def test_get_unknown_agent_404(cfg):
    resp = client.get(f"{CHAT_PREFIX}/agents/{'0' * 12}")
    assert resp.status_code == 404


def test_add_sources_to_existing_agent(cfg):
    create_resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "Growing Agent"})
    agent_id = create_resp.json()["agent"]["agent_id"]

    add_resp = client.post(f"{CHAT_PREFIX}/agents/{agent_id}/sources", files=[_paper_file()])
    assert add_resp.status_code == 200, add_resp.text
    assert len(add_resp.json()["agent"]["sources"]) == 1


def test_add_sources_to_unknown_agent_404(cfg):
    resp = client.post(f"{CHAT_PREFIX}/agents/{'0' * 12}/sources", files=[_paper_file()])
    assert resp.status_code == 404


def test_delete_source(cfg):
    create_resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "Deletable"}, files=[_paper_file()])
    agent = create_resp.json()["agent"]
    source_id = agent["sources"][0]["source_id"]

    del_resp = client.delete(f"{CHAT_PREFIX}/agents/{agent['agent_id']}/sources/{source_id}")
    assert del_resp.status_code == 200

    manifest = client.get(f"{CHAT_PREFIX}/agents/{agent['agent_id']}").json()
    assert manifest["sources"] == []


def test_delete_unknown_source_404(cfg):
    create_resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "No Sources"})
    agent_id = create_resp.json()["agent"]["agent_id"]
    resp = client.delete(f"{CHAT_PREFIX}/agents/{agent_id}/sources/{'0' * 12}")
    assert resp.status_code == 404


def test_delete_agent(cfg):
    create_resp = client.post(f"{CHAT_PREFIX}/agents", data={"name": "Doomed"}, files=[_paper_file()])
    agent_id = create_resp.json()["agent"]["agent_id"]

    del_resp = client.delete(f"{CHAT_PREFIX}/agents/{agent_id}")
    assert del_resp.status_code == 200

    assert client.get(f"{CHAT_PREFIX}/agents/{agent_id}").status_code == 404


def test_delete_unknown_agent_404(cfg):
    resp = client.delete(f"{CHAT_PREFIX}/agents/{'0' * 12}")
    assert resp.status_code == 404

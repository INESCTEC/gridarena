"""LLM-15: document-assistant ingestion -- validation, storage, chunking and
embedding of uploaded Markdown source files."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from gridarena.llm.documents import ingest, store

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "document_agents"


@pytest.fixture
def agent(tmp_path):
    data_dir = tmp_path / "data"
    chroma_db_path = tmp_path / "chroma_db"
    manifest = store.create_agent(data_dir, name="Test Agent", description="")
    return {"data_dir": data_dir, "chroma_db_path": chroma_db_path, "agent_id": manifest["agent_id"]}


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _collection(agent):
    client, ef = ingest._get_client_and_ef(agent["chroma_db_path"])
    return client.get_collection(name=ingest.collection_name(agent["agent_id"]), embedding_function=ef)


def test_ingest_records_chunk_metadata(agent):
    raw = _read_fixture("paper.md")
    result = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    assert result["status"] == "ingested"
    assert result["chunks"] > 1

    collection = _collection(agent)
    got = collection.get(ids=[f"{agent['agent_id']}:{result['source_id']}:{i}" for i in range(result["chunks"])])
    assert len(got["ids"]) == result["chunks"]
    for meta in got["metadatas"]:
        assert meta["source_id"] == result["source_id"]
        assert meta["filename"] == "paper.md"
        assert "anchor" in meta and meta["anchor"]
        assert "heading" in meta
        assert "heading_path" in meta

    # a chunk under "## Method" > "### Noise model" carries both the short leaf
    # heading and the full breadcrumb, and its anchor matches the breadcrumb slug
    noise_model_meta = next(m for m in got["metadatas"] if m["heading"] == "Noise model")
    assert noise_model_meta["heading_path"] == "Noise Robustness in Grid State Estimation > Method > Noise model"
    assert noise_model_meta["anchor"] == "noise-robustness-in-grid-state-estimation-method-noise-model"


def test_ingest_updates_manifest(agent):
    raw = _read_fixture("paper.md")
    result = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    manifest = store.load_manifest(agent["data_dir"], agent["agent_id"])
    assert len(manifest["sources"]) == 1
    entry = manifest["sources"][0]
    assert entry["source_id"] == result["source_id"]
    assert entry["title"] == "Noise Robustness in Grid State Estimation"
    # "Method" itself has no body text (only its subsections do), so it never
    # becomes a chunk of its own -- its children are what appear here.
    assert entry["headings"] == ["Introduction", "Noise model", "Estimation procedure", "Results"]
    assert entry["chunks"] == result["chunks"]


def test_document_with_no_headings_ingests_as_one_section_titled_after_filename(agent):
    raw = _read_fixture("no_headings.md")
    result = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "no_headings.md", raw,
        max_source_mb=5, max_sources=20,
    )

    assert result["status"] == "ingested"
    assert result["chunks"] == 1
    assert result["title"] == "no_headings.md"

    manifest = store.load_manifest(agent["data_dir"], agent["agent_id"])
    assert manifest["sources"][0]["headings"] == []


def test_pdf_upload_is_rejected(agent):
    with pytest.raises(HTTPException) as exc_info:
        ingest.ingest_file(
            agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.pdf", b"%PDF-1.4 fake",
            max_source_mb=5, max_sources=20,
        )
    assert exc_info.value.status_code == 415


def test_docx_upload_is_rejected(agent):
    with pytest.raises(HTTPException) as exc_info:
        ingest.ingest_file(
            agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.docx", b"PK\x03\x04 fake docx",
            max_source_mb=5, max_sources=20,
        )
    assert exc_info.value.status_code == 415


def test_non_utf8_upload_is_rejected(agent):
    raw = "café".encode("latin-1")  # not valid utf-8
    with pytest.raises(HTTPException) as exc_info:
        ingest.ingest_file(
            agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "bad.md", raw,
            max_source_mb=5, max_sources=20,
        )
    assert exc_info.value.status_code == 400


def test_oversized_upload_is_rejected(agent):
    raw = b"# Title\n\n" + b"x" * 1000
    with pytest.raises(HTTPException) as exc_info:
        ingest.ingest_file(
            agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "big.md", raw,
            max_source_mb=0.0001, max_sources=20,
        )
    assert exc_info.value.status_code == 413


def test_too_many_sources_is_rejected(agent):
    ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "no_headings.md",
        _read_fixture("no_headings.md"), max_source_mb=5, max_sources=1,
    )
    with pytest.raises(HTTPException) as exc_info:
        ingest.ingest_file(
            agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md",
            _read_fixture("paper.md"), max_source_mb=5, max_sources=1,
        )
    assert exc_info.value.status_code == 422


def test_duplicate_upload_is_skipped_not_reembedded(agent):
    raw = _read_fixture("paper.md")
    first = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )
    second = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    assert second["status"] == "duplicate"
    assert second["source_id"] == first["source_id"]

    manifest = store.load_manifest(agent["data_dir"], agent["agent_id"])
    assert len(manifest["sources"]) == 1


def test_retrying_after_a_failed_manifest_write_does_not_duplicate_chunks(agent):
    """Simulates: the embed step succeeded but the manifest write never
    landed (crash, disk full, etc.). Retrying the identical upload must not
    leave two copies of the same chunks in the collection."""
    raw = _read_fixture("paper.md")
    first = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    # Drop the manifest entry only -- as if the process died after upsert()
    # but before add_source_to_manifest() -- so the sha256 short-circuit can't
    # fire on retry.
    store.remove_source_from_manifest(agent["data_dir"], agent["agent_id"], first["source_id"])

    retry = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    assert retry["source_id"] == first["source_id"]  # content-derived id, not random
    assert retry["chunks"] == first["chunks"]

    collection = _collection(agent)
    all_ids = collection.get(where={"source_id": retry["source_id"]})["ids"]
    assert len(all_ids) == retry["chunks"]  # not double


def test_delete_source_removes_file_manifest_and_chunks(agent):
    raw = _read_fixture("paper.md")
    result = ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md", raw,
        max_source_mb=5, max_sources=20,
    )

    path_before = store.source_path(agent["data_dir"], agent["agent_id"], result["source_id"])
    assert path_before is not None and path_before.exists()

    assert ingest.delete_source(agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], result["source_id"])

    assert store.source_path(agent["data_dir"], agent["agent_id"], result["source_id"]) is None
    assert not path_before.exists()

    manifest = store.load_manifest(agent["data_dir"], agent["agent_id"])
    assert manifest["sources"] == []

    collection = _collection(agent)
    remaining = collection.get(where={"source_id": result["source_id"]})["ids"]
    assert remaining == []


def test_delete_agent_removes_directory_and_collection(agent):
    ingest.ingest_file(
        agent["data_dir"], agent["chroma_db_path"], agent["agent_id"], "paper.md",
        _read_fixture("paper.md"), max_source_mb=5, max_sources=20,
    )

    assert store.delete_agent(agent["data_dir"], agent["chroma_db_path"], agent["agent_id"])
    assert store.load_manifest(agent["data_dir"], agent["agent_id"]) is None

    client, ef = ingest._get_client_and_ef(agent["chroma_db_path"])
    with pytest.raises(Exception):
        client.get_collection(name=ingest.collection_name(agent["agent_id"]), embedding_function=ef)

"""LLM-10: heading-aware chunking so RAG retrieval returns sections of a doc,
not the entire document every time.

LLM-11: hash-based selective re-embedding, so an edited doc's collection is
rebuilt on the next startup without touching unrelated collections.
"""

import json
from pathlib import Path

import pytest

from gridarena.llm.rag import embedder
from gridarena.llm.rag.embedder import AGENT_DOC_FILES, chunk_markdown

DOCS_DIR = Path(__file__).resolve().parent.parent / "gridarena" / "llm" / "docs"


def test_grid_md_yields_more_than_one_chunk_with_headings():
    text = (DOCS_DIR / AGENT_DOC_FILES["GridAgent"]).read_text(encoding="utf-8")
    chunks = chunk_markdown(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["heading"], f"chunk has no heading: {chunk['text'][:80]!r}"
        assert chunk["text"].startswith(chunk["heading"])


def test_every_builtin_doc_chunks_cleanly():
    """Sanity sweep: every shipped agent doc should chunk without error and
    produce at least one chunk."""
    for agent_name, filename in AGENT_DOC_FILES.items():
        path = DOCS_DIR / filename
        assert path.exists(), f"missing doc file for {agent_name}: {path}"
        chunks = chunk_markdown(path.read_text(encoding="utf-8"))
        assert len(chunks) >= 1, f"{filename} produced no chunks"


def test_heading_nesting_builds_a_path():
    text = """# Grid API

## Functions

### Deleting a grid

Use this when you want to remove a grid entirely.
"""
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert chunks[0]["heading"] == "Grid API > Functions > Deleting a grid"
    assert chunks[0]["text"].startswith("Grid API > Functions > Deleting a grid: ")


def test_long_section_splits_into_overlapping_windows():
    body = " ".join(f"word{i}" for i in range(500))
    text = f"# Big Section\n\n{body}\n"

    chunks = chunk_markdown(text, max_section_words=180, overlap=40)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["heading"] == "Big Section"

    # consecutive windows must overlap
    first_words = chunks[0]["text"].split()
    second_words = chunks[1]["text"].split()
    assert first_words[-1] in second_words[: 40 + 5]


def test_document_with_no_headings_still_chunks():
    text = "Just some plain text with no markdown headings at all."
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert chunks[0]["heading"] == ""
    assert chunks[0]["text"] == text


def test_preamble_before_first_heading_is_its_own_chunk():
    text = "Intro paragraph before any heading.\n\n# First Heading\n\nBody text.\n"
    chunks = chunk_markdown(text)
    assert chunks[0]["heading"] == ""
    assert "Intro paragraph" in chunks[0]["text"]
    assert chunks[1]["heading"] == "First Heading"


# ═══════════════════════════════════════════════════════════════
#  LLM-11: manifest-based selective re-embedding
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def small_docs(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.md").write_text("# A\n\nHello world, this is doc A.\n", encoding="utf-8")
    (docs_dir / "b.md").write_text("# B\n\nGoodbye world, this is doc B.\n", encoding="utf-8")
    monkeypatch.setattr(embedder, "AGENT_DOC_FILES", {"AAgent": "a.md", "BAgent": "b.md"})
    return docs_dir


def test_first_run_embeds_and_writes_manifest(small_docs, tmp_path):
    db_path = tmp_path / "chroma_db"
    embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    manifest = json.loads((db_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["docs"].keys()) == {"AAgent", "BAgent"}
    for entry in manifest["docs"].values():
        assert entry["embedding_model"] == "test-model"
        assert entry["chunker_version"] == embedder.CHUNKER_VERSION
        assert entry["chunks"] >= 1


def test_second_run_with_no_changes_skips_everything(small_docs, tmp_path, caplog):
    db_path = tmp_path / "chroma_db"
    embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    caplog.clear()
    with caplog.at_level("INFO", logger="gridarena.llm.rag.embedder"):
        embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    assert "rebuilt collection" not in caplog.text
    assert "RAG: skipped unchanged collection(s) for AAgent, BAgent" in caplog.text


def test_editing_one_doc_rebuilds_only_that_collection(small_docs, tmp_path, caplog):
    db_path = tmp_path / "chroma_db"
    embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    (small_docs / "a.md").write_text("# A\n\nCompletely different content now.\n", encoding="utf-8")

    caplog.clear()
    with caplog.at_level("INFO", logger="gridarena.llm.rag.embedder"):
        embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    # AGENT_DOC_FILES insertion order is deterministic (AAgent, BAgent), so the
    # rebuilt/skipped lists -- and therefore these exact log lines -- are too.
    assert "RAG: rebuilt collection(s) for AAgent" in caplog.text
    assert "RAG: skipped unchanged collection(s) for BAgent" in caplog.text


def test_changing_embedding_model_forces_rebuild(small_docs, tmp_path, caplog):
    db_path = tmp_path / "chroma_db"
    embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="model-v1")

    caplog.clear()
    with caplog.at_level("INFO", logger="gridarena.llm.rag.embedder"):
        embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="model-v2")

    assert "RAG: rebuilt collection(s) for AAgent, BAgent" in caplog.text


def test_bumping_chunker_version_forces_rebuild(small_docs, tmp_path, monkeypatch, caplog):
    db_path = tmp_path / "chroma_db"
    embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    monkeypatch.setattr(embedder, "CHUNKER_VERSION", embedder.CHUNKER_VERSION + 1)

    caplog.clear()
    with caplog.at_level("INFO", logger="gridarena.llm.rag.embedder"):
        embedder.embed_all_docs(docs_dir=small_docs, db_path=db_path, embedding_model="test-model")

    assert "RAG: rebuilt collection(s) for AAgent, BAgent" in caplog.text

"""Ingestion pipeline for document-assistant source files.

No new third-party dependency: Markdown needs no parser beyond the LLM-10
heading-aware chunker already used for the built-in agent docs.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from gridarena.llm.documents import DOCUMENT_COLLECTION_PREFIX, slugify_heading_path, store
from gridarena.llm.rag.embedder import chunk_markdown

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = (".md", ".markdown")


def collection_name(agent_id: str) -> str:
    return f"{DOCUMENT_COLLECTION_PREFIX}{agent_id}"


def _get_client_and_ef(chroma_db_path: Path):
    import chromadb
    from chromadb.utils import embedding_functions

    chroma_db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_db_path))
    # Must match the embedding function the generic RAG index uses (see LLM-11):
    # a document assistant's collection is queried the same way. The path is
    # passed in explicitly (rather than read from get_llm_config() here) so
    # this module has no global config dependency and is straightforward to
    # point at an isolated database in tests.
    ef = embedding_functions.DefaultEmbeddingFunction()
    return client, ef


def validate_filename(filename: str) -> None:
    if not filename or not filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=415,
            detail=(
                f"'{filename}' was rejected: only Markdown files (.md, .markdown) are "
                "accepted. Convert other formats to Markdown first, keeping the headings."
            ),
        )


def decode_utf8(raw: bytes, filename: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail=f"'{filename}' is not valid UTF-8 text.")


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return fallback


def _delete_chunks(collection, agent_id: str, source_id: str, chunk_count: int) -> None:
    ids = [f"{agent_id}:{source_id}:{i}" for i in range(chunk_count)]
    if ids:
        try:
            collection.delete(ids=ids)
        except Exception:
            pass


def ingest_file(
    data_dir: Path, chroma_db_path: Path, agent_id: str, filename: str, raw: bytes,
    max_source_mb: float, max_sources: int,
) -> Dict[str, Any]:
    """Validate, save, chunk and embed one uploaded Markdown file.

    Returns a per-file result dict on success -- {"filename", "status":
    "ingested"|"duplicate", "source_id", "chunks", "title"} -- so a multi-file
    upload (LLM-17) can report each file's outcome individually. Raises
    HTTPException (415/400/413/422/404) on rejection.
    """
    validate_filename(filename)

    max_bytes = int(max_source_mb * 1024 * 1024)
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"'{filename}' is too large ({len(raw)} bytes; max {max_bytes} bytes).",
        )

    text = decode_utf8(raw, filename)
    content_hash = hashlib.sha256(raw).hexdigest()

    manifest = store.load_manifest(data_dir, agent_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such document agent: {agent_id}")

    # A file already present under this exact content hash is a no-op, not a
    # re-embed -- re-uploading the same source repeatedly must not duplicate it.
    existing = next((s for s in manifest["sources"] if s["sha256"] == content_hash), None)
    if existing is not None:
        return {
            "filename": filename, "status": "duplicate", "source_id": existing["source_id"],
            "chunks": existing["chunks"], "title": existing["title"],
        }

    if len(manifest["sources"]) >= max_sources:
        raise HTTPException(
            status_code=422,
            detail=f"This agent already has {len(manifest['sources'])} sources (max {max_sources}).",
        )

    chunks = chunk_markdown(text)
    if not chunks:
        raise HTTPException(status_code=422, detail=f"'{filename}' has no content to index.")

    # Derived from content, not random: retrying the exact same upload after a
    # partial failure (embed succeeded, manifest write didn't) recomputes the
    # same id and re-embeds at the same chunk ids via upsert below, so the
    # retry overwrites rather than duplicates -- no separate "resume" state to
    # track. A genuine sha256 match is already caught above and never reaches
    # here, so any source_id minted here is new to this agent's manifest.
    source_id = content_hash[:12]
    title = _extract_title(text, fallback=filename)

    dest = store.sources_dir(data_dir, agent_id) / f"{source_id}__{filename}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    client, ef = _get_client_and_ef(chroma_db_path)
    collection = client.get_or_create_collection(name=collection_name(agent_id), embedding_function=ef)

    documents = [c["text"] for c in chunks]
    metadatas = []
    headings = []  # short, deduplicated, order-preserving -- for the manifest/UI
    for i, c in enumerate(chunks):
        heading_path = c["heading"]
        heading_leaf = heading_path.rsplit(" > ", 1)[-1] if heading_path else ""
        metadatas.append({
            "source_id": source_id,
            "filename": filename,
            "heading": heading_leaf,
            "heading_path": heading_path,
            "anchor": slugify_heading_path(heading_path or title),
            "chunk_index": i,
        })
        if heading_leaf and heading_leaf not in headings:
            headings.append(heading_leaf)
    ids = [f"{agent_id}:{source_id}:{i}" for i in range(len(chunks))]
    # upsert, not add: ids are deterministic (agent_id:source_id:index), so a
    # retry after a partial failure overwrites rather than duplicates.
    collection.upsert(documents=documents, metadatas=metadatas, ids=ids)

    source_entry = {
        "source_id": source_id,
        "filename": filename,
        "sha256": content_hash,
        "bytes": len(raw),
        "chunks": len(chunks),
        "title": title,
        "headings": headings,
        "uploaded_at": store.now(),
    }
    store.add_source_to_manifest(data_dir, agent_id, source_entry)

    logger.info("Ingested '%s' (%d chunks) for document agent %s", filename, len(chunks), agent_id)
    return {
        "filename": filename, "status": "ingested", "source_id": source_id,
        "chunks": len(chunks), "title": title,
    }


def delete_source(data_dir: Path, chroma_db_path: Path, agent_id: str, source_id: str) -> bool:
    manifest = store.load_manifest(data_dir, agent_id)
    if manifest is None:
        return False
    existing = next((s for s in manifest["sources"] if s["source_id"] == source_id), None)
    if existing is None:
        return False

    client, ef = _get_client_and_ef(chroma_db_path)
    try:
        collection = client.get_collection(name=collection_name(agent_id), embedding_function=ef)
        _delete_chunks(collection, agent_id, source_id, existing["chunks"])
    except Exception:
        pass

    path = store.source_path(data_dir, agent_id, source_id)
    if path is not None and path.exists():
        path.unlink()

    store.remove_source_from_manifest(data_dir, agent_id, source_id)
    return True


def delete_collection(chroma_db_path: Path, agent_id: str) -> None:
    client, ef = _get_client_and_ef(chroma_db_path)
    try:
        client.delete_collection(collection_name(agent_id))
    except Exception:
        pass

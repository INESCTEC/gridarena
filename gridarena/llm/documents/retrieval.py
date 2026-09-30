"""Citation-aware retrieval for a single document assistant's own collection."""

from pathlib import Path
from typing import Any, Dict, List

from gridarena.llm.documents import ingest


def search(chroma_db_path: Path, agent_id: str, query: str, k: int) -> List[Dict[str, Any]]:
    """Query only this agent's own collection ("{prefix}{agent_id}", never any
    other agent's or the generic assistant's). Returns excerpts carrying enough
    metadata to build both the LLM-facing reference block and the citations
    returned to the client: text, source_id, filename, heading (short, for the
    citation chip), heading_path (full breadcrumb, for the reference block's
    "section" label), anchor (for the source-viewer link), and a distance score.
    """
    client, ef = ingest._get_client_and_ef(chroma_db_path)
    try:
        collection = client.get_collection(name=ingest.collection_name(agent_id), embedding_function=ef)
    except Exception:
        return []

    results = collection.query(query_texts=[query], n_results=k)
    docs = results["documents"][0] if results.get("documents") else []
    metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    distances = results["distances"][0] if results.get("distances") else [None] * len(docs)

    excerpts = []
    for doc, meta, distance in zip(docs, metadatas, distances):
        meta = meta or {}
        excerpts.append({
            "text": doc,
            "source_id": meta.get("source_id"),
            "filename": meta.get("filename"),
            "heading": meta.get("heading", ""),
            "heading_path": meta.get("heading_path", ""),
            "anchor": meta.get("anchor", ""),
            "score": distance,
        })
    return excerpts

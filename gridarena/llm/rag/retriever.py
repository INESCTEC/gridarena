import logging

from gridarena.llm.config import get_llm_config
from gridarena.llm.documents import DOCUMENT_COLLECTION_PREFIX

logger = logging.getLogger(__name__)

_client = None
_ef = None


def _get_client():
    global _client, _ef
    if _client is None:
        import chromadb
        from chromadb.utils import embedding_functions

        config = get_llm_config()
        db_path = config["chroma_db_path"]
        db_path.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(db_path))
        # Must be the exact same embedding function embedder.py used to build each
        # collection, or a query against it returns nothing with no error -- see
        # LVGPLAY_LLM_EMBEDDING_MODEL / config.py's "embedding_model" for the name
        # both sides are checked against via the RAG manifest.
        logger.debug("RAG query embedding model: %s", config["embedding_model"])
        _ef = embedding_functions.DefaultEmbeddingFunction()
    return _client, _ef


def get_relevant_docs(query: str, agent_names: list[str], n_results: int = 3) -> str:
    """Retrieve doc chunks for the generic assistant's built-in agents only.

    A document-assistant collection is named "{DOCUMENT_COLLECTION_PREFIX}{agent_id}"
    (see gridarena/llm/documents/). Refusing any name with that prefix here is a hard
    structural guarantee that a document assistant's content can never reach the
    generic assistant's prompt or tools, on top of the fact that get_relevant_agents()
    only ever returns built-in names -- belt and suspenders against a future caller
    passing one through.
    """
    for agent_name in agent_names:
        if agent_name.startswith(DOCUMENT_COLLECTION_PREFIX):
            raise ValueError(f"Refusing to query a document-assistant collection from the generic path: {agent_name}")

    client, ef = _get_client()
    rendered_chunks = []

    for agent_name in agent_names:
        try:
            collection = client.get_collection(name=agent_name, embedding_function=ef)
            results = collection.query(query_texts=[query], n_results=n_results)
            docs = results["documents"][0] if results["documents"] else []
            metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            for doc, meta in zip(docs, metadatas):
                source = (meta or {}).get("source", agent_name)
                heading = (meta or {}).get("heading", "")
                label = f"{source} — {heading}" if heading else source
                rendered_chunks.append(f"[{label}]\n{doc}")
        except Exception as e:
            logger.debug("No RAG collection for %s: %s", agent_name, e)

    if not rendered_chunks:
        return ""

    return "\n\n---\n\n".join(rendered_chunks)

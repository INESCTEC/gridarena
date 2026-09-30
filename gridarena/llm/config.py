import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def get_llm_config() -> dict:
    return {
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "api_url": os.environ.get("LLM_API_URL", "https://cpes-llm.inesctec.pt/api"),
        "model": os.environ.get("LLM_MODEL", "gemma4-31b"),
        "docs_dir": BASE_DIR / "docs",
        "chroma_db_path": BASE_DIR / "rag" / "chroma_db",
        # Named explicitly (rather than left as an unnamed default) so embedder.py and
        # retriever.py can be checked against a single source of truth, and so the
        # RAG manifest can detect drift if this ever changes. Currently the only
        # embedding function actually wired up is chromadb's bundled ONNX MiniLM
        # (DefaultEmbeddingFunction), which is what this default names.
        "embedding_model": os.environ.get("LVGPLAY_LLM_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "verify_ssl": os.environ.get("LLM_VERIFY_SSL", "false").lower() == "true",
        "temperature": 0.3,
        "max_tokens_with_tools": 2000,
        "max_tokens_interpretation": 800,
        # Writable runtime state that must live outside the installed package --
        # e.g. document-assistant storage (Phase 4B). Never assume this is the
        # source tree: it may be a mounted volume in a container.
        "data_dir": Path(os.environ.get("LVGPLAY_DATA_DIR", "./data/llm")),
        # Document assistants (Phase 4B) -- disabled by default.
        "allow_document_agents": os.environ.get("LVGPLAY_ALLOW_DOCUMENT_AGENTS", "0") == "1",
        "max_source_mb": float(os.environ.get("LVGPLAY_LLM_MAX_SOURCE_MB", "5")),
        "max_sources_per_agent": int(os.environ.get("LVGPLAY_LLM_MAX_SOURCES_PER_AGENT", "20")),
        "doc_chunks_per_answer": int(os.environ.get("LVGPLAY_LLM_DOC_CHUNKS_PER_ANSWER", "6")),
    }

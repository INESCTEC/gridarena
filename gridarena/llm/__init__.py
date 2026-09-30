import logging

from gridarena.llm.chat import ChatSession
from gridarena.llm.config import get_llm_config

logger = logging.getLogger(__name__)


def init_rag():
    config = get_llm_config()
    config["data_dir"].mkdir(parents=True, exist_ok=True)

    if not config["api_key"]:
        logger.warning("LLM_API_KEY not set — chat functionality will be unavailable")
        return

    from gridarena.llm.rag.embedder import embed_all_docs
    embed_all_docs(
        docs_dir=config["docs_dir"], db_path=config["chroma_db_path"],
        embedding_model=config["embedding_model"],
    )
    logger.info("RAG initialization complete")

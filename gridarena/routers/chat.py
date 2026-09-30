"""Chat Router — WebSocket endpoint, full-page chat UI, config page, and the
document-assistant WebSocket + source routes (Phase 4B)."""

import logging
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from gridarena.llm.chat import ChatSession

from ._upload_guard import ensure_upload_size_ok

logger = logging.getLogger(__name__)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


_AGENT_DESCRIPTIONS = {
    "GridAgent": "Manages electrical network models — register, query, and delete grid topologies (nodes, connections, cables).",
    "HistoricalAgent": "Handles time-series measurement data — upload, retrieve, and delete historical power and voltage records.",
    "PhaseAgent": "Phase Identification Benchmark — download labelled/anonymised data, submit phase guesses, and evaluate accuracy.",
    "TopologyAgent": "Topology Discovery Benchmark — reconstruct grid wiring from smart-meter data, submit guesses, and score.",
    "StateAgent": "State Estimation Benchmark — predict missing voltage values at unobserved nodes, submit estimates, and score.",
    "VoltageAgent": "Voltage Control Benchmark — propose corrective power adjustments for voltage violations, submit solutions, and score.",
    "PowerflowAgent": "Runs Newton-Raphson power flow simulations on registered grids and retrieves computed voltages.",
}


def _build_agent_config() -> dict:
    """Introspect the real LLM code and return safe metadata."""
    from gridarena.llm.config import get_llm_config
    from gridarena.llm.dispatcher import KEYWORD_TO_AGENT, TOOL_TO_AGENT_CLASS
    from gridarena.llm.tools import ALL_TOOLS
    from gridarena.llm.rag.embedder import AGENT_DOC_FILES

    config = get_llm_config()

    tool_schemas = {}
    for t in ALL_TOOLS:
        fn = t["function"]
        tool_schemas[fn["name"]] = fn.get("description", "")

    agent_names = sorted(set(cls.__name__ for cls in TOOL_TO_AGENT_CLASS.values()))

    # Only tools currently advertised to the model (LLM-6 may be gating some off) --
    # this list is what the assistant can actually do right now, not everything an
    # agent class knows how to handle.
    advertised = set(tool_schemas)

    agents = []
    for name in agent_names:
        tools = sorted(
            tn for tn, cls in TOOL_TO_AGENT_CLASS.items()
            if cls.__name__ == name and tn in advertised
        )
        keywords = sorted(
            kw for kw, agent_list in KEYWORD_TO_AGENT.items()
            if name in agent_list
        )
        agents.append({
            "name": name,
            "description": _AGENT_DESCRIPTIONS.get(name, ""),
            "tools": [{"name": tn, "description": tool_schemas.get(tn, "")} for tn in tools],
            "keywords": keywords,
            "has_rag_docs": name in AGENT_DOC_FILES,
            "rag_doc_file": AGENT_DOC_FILES.get(name),
        })

    has_key = bool(config.get("api_key"))

    return {
        "model": config.get("model", ""),
        "api_url": config.get("api_url", ""),
        "api_key_configured": has_key,
        "temperature": config.get("temperature"),
        "max_tokens_with_tools": config.get("max_tokens_with_tools"),
        "max_tokens_interpretation": config.get("max_tokens_interpretation"),
        "verify_ssl": config.get("verify_ssl"),
        "allow_document_agents": config.get("allow_document_agents", False),
        "agents": agents,
        "total_tools": len(ALL_TOOLS),
    }


@router.get("/config", tags=["Chat"])
async def get_chat_config():
    """Return LLM agent configuration metadata (no secrets exposed)."""
    return _build_agent_config()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat/page.html", {
        "request": request,
        "title": "Chat Assistant",
        "active": "chat",
    })


@router.get("/ui/config", response_class=HTMLResponse, include_in_schema=False)
async def chat_config_page(request: Request):
    """Configuration overview page for the Chat Assistant."""
    data = _build_agent_config()
    return templates.TemplateResponse("chat/config.html", {
        "request": request,
        "title": "Chat Assistant Configuration",
        "active": "chat_config",
        "config": data,
    })


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()

    async def send_status(msg: dict):
        await websocket.send_json(msg)

    session = ChatSession(on_status=send_status)
    logger.info("WebSocket connected: session %s", session.session_id)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "user_message":
                try:
                    response = await session.process_message(data["content"])
                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": response,
                    })
                except RuntimeError as e:
                    if "LLM_API_KEY is not configured" in str(e):
                        logger.warning("Chat used with no LLM_API_KEY configured")
                        await websocket.send_json({
                            "type": "error",
                            "content": "The chat assistant is not configured on this server "
                                        "(missing LLM_API_KEY). Contact an administrator.",
                        })
                    else:
                        logger.error("Chat error: %s", e, exc_info=True)
                        await websocket.send_json({
                            "type": "error",
                            "content": "An internal error occurred while processing your message. "
                                        "Please try again.",
                        })
                except Exception as e:
                    logger.error("Chat error: %s", e, exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "content": "An internal error occurred while processing your message. "
                                    "Please try again.",
                    })
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session %s", session.session_id)


# ═══════════════════════════════════════════════════════════════
#  Document assistants (Phase 4B) — llm_fix_plan.md LLM-16/17
# ═══════════════════════════════════════════════════════════════


def _require_document_agents_enabled() -> dict:
    from gridarena.llm.config import get_llm_config

    config = get_llm_config()
    if not config["allow_document_agents"]:
        raise HTTPException(status_code=404, detail="Document assistants are not enabled on this server.")
    return config


async def _ingest_uploads(config: dict, agent_id: str, files: List[UploadFile]) -> List[dict]:
    """Ingest each uploaded file, reporting per-file status rather than failing
    the whole call -- one bad file in a batch shouldn't lose the good ones."""
    from gridarena.llm.documents import ingest

    max_bytes = int(config["max_source_mb"] * 1024 * 1024)
    results = []
    for f in files:
        try:
            ensure_upload_size_ok(f, max_bytes=max_bytes)
            raw = await f.read()
            result = ingest.ingest_file(
                config["data_dir"], config["chroma_db_path"], agent_id, f.filename, raw,
                max_source_mb=config["max_source_mb"], max_sources=config["max_sources_per_agent"],
            )
        except HTTPException as e:
            result = {"filename": f.filename, "status": "rejected", "detail": e.detail}
        results.append(result)
    return results


@router.post("/agents", tags=["Chat"])
async def create_document_agent(
    name: str = Form(...),
    description: str = Form(""),
    files: List[UploadFile] = File(default=[]),
):
    """Create a document assistant and ingest any Markdown files attached at
    creation time. Returns the new manifest plus each file's ingest status."""
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")

    manifest = store.create_agent(config["data_dir"], name=name, description=description.strip())
    file_results = await _ingest_uploads(config, manifest["agent_id"], files)
    manifest = store.load_manifest(config["data_dir"], manifest["agent_id"])

    return {"agent": manifest, "files": file_results}


@router.get("/agents", tags=["Chat"])
async def list_document_agents():
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    return {"agents": store.list_agents(config["data_dir"])}


@router.get("/agents/ui", response_class=HTMLResponse, include_in_schema=False)
async def document_agent_page(request: Request, agent_id: str | None = Query(None)):
    """Full page for a single document assistant's conversation. With no
    agent_id it renders an empty state -- reached only via the site-wide
    picker popup, which always passes one."""
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    agent = None
    if agent_id:
        agent = store.load_manifest(config["data_dir"], agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="No such document agent.")

    return templates.TemplateResponse("chat/agent_page.html", {
        "request": request,
        "title": agent["name"] if agent else "Document Assistants",
        "active": "chat",
        "agent": agent,
    })


@router.get("/agents/{agent_id}", tags=["Chat"])
async def get_document_agent(agent_id: str):
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    manifest = store.load_manifest(config["data_dir"], agent_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="No such document agent.")
    return manifest


@router.post("/agents/{agent_id}/sources", tags=["Chat"])
async def add_document_agent_sources(agent_id: str, files: List[UploadFile] = File(...)):
    """Add one or more Markdown documents to an existing document assistant."""
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    if store.load_manifest(config["data_dir"], agent_id) is None:
        raise HTTPException(status_code=404, detail="No such document agent.")

    file_results = await _ingest_uploads(config, agent_id, files)
    manifest = store.load_manifest(config["data_dir"], agent_id)
    return {"agent": manifest, "files": file_results}


@router.delete("/agents/{agent_id}/sources/{source_id}", tags=["Chat"])
async def delete_document_agent_source(agent_id: str, source_id: str):
    from gridarena.llm.documents import ingest

    config = _require_document_agents_enabled()
    if not ingest.delete_source(config["data_dir"], config["chroma_db_path"], agent_id, source_id):
        raise HTTPException(status_code=404, detail="No such source.")
    return {"status": "deleted"}


@router.delete("/agents/{agent_id}", tags=["Chat"])
async def delete_document_agent(agent_id: str):
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    if not store.delete_agent(config["data_dir"], config["chroma_db_path"], agent_id):
        raise HTTPException(status_code=404, detail="No such document agent.")
    return {"status": "deleted"}


async def _check_ws_api_key(websocket: WebSocket) -> bool:
    """Minimal API-key gate for the document-assistant WebSocket.

    Standing in for improvement_plan.md task C2 (a shared require_api_key_ws
    dependency for the whole API), which this codebase does not have yet.
    Reads the same LVGPLAY_API_KEY env var C2 is expected to use, so this can
    be deleted in favour of the shared dependency once C2 lands, with no
    behaviour change for a deployment that already set the variable.
    """
    expected = os.environ.get("LVGPLAY_API_KEY")
    if not expected:
        return True
    provided = websocket.query_params.get("api_key")
    if provided == expected:
        return True
    await websocket.close(code=1008)
    return False


@router.websocket("/agents/{agent_id}/ws")
async def document_chat_websocket(websocket: WebSocket, agent_id: str):
    from gridarena.llm.document_chat import DocumentChatSession
    from gridarena.llm.documents import store

    try:
        config = _require_document_agents_enabled()
    except HTTPException:
        await websocket.close(code=1008)
        return

    if not await _check_ws_api_key(websocket):
        return

    manifest = store.load_manifest(config["data_dir"], agent_id)
    if manifest is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session = DocumentChatSession(
        agent_id=agent_id,
        chroma_db_path=config["chroma_db_path"],
        config=config,
        k=config["doc_chunks_per_answer"],
    )
    logger.info("Document chat WebSocket connected: agent=%s session=%s", agent_id, session.session_id)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "user_message":
                try:
                    result = await session.process_message(data["content"])
                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": result["answer"],
                        "citations": result["citations"],
                    })
                except RuntimeError as e:
                    if "LLM_API_KEY is not configured" in str(e):
                        await websocket.send_json({
                            "type": "error",
                            "content": "The chat assistant is not configured on this server "
                                        "(missing LLM_API_KEY). Contact an administrator.",
                        })
                    else:
                        logger.error("Document chat error: %s", e, exc_info=True)
                        await websocket.send_json({
                            "type": "error",
                            "content": "An internal error occurred while processing your message. "
                                        "Please try again.",
                        })
                except Exception as e:
                    logger.error("Document chat error: %s", e, exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "content": "An internal error occurred while processing your message. "
                                    "Please try again.",
                    })
    except WebSocketDisconnect:
        logger.info("Document chat WebSocket disconnected: agent=%s session=%s", agent_id, session.session_id)


@router.get("/agents/{agent_id}/sources/{source_id}", tags=["Chat"])
async def get_document_source_raw(agent_id: str, source_id: str):
    """Raw Markdown download for one attached source."""
    from gridarena.llm.documents import store

    config = _require_document_agents_enabled()
    path = store.source_path(config["data_dir"], agent_id, source_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No such source.")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@router.get("/agents/{agent_id}/sources/{source_id}/view", response_class=HTMLResponse, include_in_schema=False)
async def get_document_source_view(request: Request, agent_id: str, source_id: str):
    """Source rendered to HTML with `id` attributes on every heading, so a
    citation link (…/view#some-anchor) jumps straight to the cited section."""
    from gridarena.llm.documents import render, store

    config = _require_document_agents_enabled()
    path = store.source_path(config["data_dir"], agent_id, source_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No such source.")

    manifest = store.load_manifest(config["data_dir"], agent_id)
    source_meta = next((s for s in manifest["sources"] if s["source_id"] == source_id), None)
    title = source_meta["title"] if source_meta else path.name

    body_html = render.render_markdown_with_anchors(path.read_text(encoding="utf-8"))
    return templates.TemplateResponse("chat/source_view.html", {
        "request": request,
        "title": title,
        "active": "chat",
        "body_html": body_html,
    })

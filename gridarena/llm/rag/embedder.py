import hashlib
import json
import logging
import re
from pathlib import Path
from typing import List, Tuple

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

AGENT_DOC_FILES = {
    "GridAgent": "grid.md",
    "HistoricalAgent": "historical.md",
    "MeasurementsAgent": "measurements.md",
    "PhaseAgent": "phase.md",
    "TopologyAgent": "topology.md",
    "StateAgent": "state_estimation.md",
    "VoltageAgent": "voltage_control.md",
    "PowerflowAgent": "powerflow.md",
}

# Bump whenever chunk_markdown's splitting logic changes -- the manifest below uses
# this to decide whether a collection needs re-embedding even if the source file hasn't.
CHUNKER_VERSION = 1
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MANIFEST_FILENAME = "manifest.json"

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_DEFAULT_MAX_SECTION_WORDS = 180
_DEFAULT_OVERLAP_WORDS = 40


def split_into_sections(text: str) -> List[Tuple[List[str], str]]:
    """Split markdown into (heading_path, body) pairs by heading nesting.

    heading_path is the stack of headings leading to a section, e.g.
    ["Grid Agent", "Functions", "delete_grid"] for text under a level-3 "###
    delete_grid" heading nested under "## Functions" nested under "# Grid Agent".

    Exported (not just used internally by chunk_markdown) because the
    document-assistant source viewer (LLM-16) needs the exact same heading
    nesting to stamp `id` attributes that match the anchors computed at ingest
    time (LLM-15) -- both must derive from one shared walk of the document.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        body = text.strip()
        return [([], body)] if body else []

    sections: List[Tuple[List[str], str]] = []
    stack: List[Tuple[int, str]] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(([], preamble))

    for idx, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

        sections.append(([t for _, t in stack], body))

    return sections


def chunk_markdown(
    text: str,
    max_section_words: int = _DEFAULT_MAX_SECTION_WORDS,
    overlap: int = _DEFAULT_OVERLAP_WORDS,
) -> List[dict]:
    """Heading-aware chunking.

    Splits on markdown headings first, then splits any section longer than
    max_section_words into overlapping windows. Most of the built-in docs are
    shorter than the old flat 600-word chunk size, so with that scheme each
    collection held exactly one chunk and every query returned the entire
    document; splitting by heading first means a query returns the section it
    actually matched.

    Returns a list of {"heading": "A > B > C", "text": "A > B > C: ..."} dicts --
    "text" is what gets embedded and stored (prefixed with its heading path so the
    embedding itself carries that context, not just the metadata beside it), and
    "heading" is kept separately for citation-style rendering (see retriever.py).
    """
    chunks: List[dict] = []

    for heading_path, body in split_into_sections(text):
        if not body:
            continue
        heading = " > ".join(heading_path)
        words = body.split()

        if len(words) <= max_section_words:
            windows = [body]
        else:
            windows = []
            i = 0
            while i < len(words):
                windows.append(" ".join(words[i : i + max_section_words]))
                if i + max_section_words >= len(words):
                    break
                i += max_section_words - overlap

        for window in windows:
            prefixed = f"{heading}: {window}" if heading else window
            chunks.append({"heading": heading, "text": prefixed})

    return chunks


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest(db_path: Path) -> dict:
    manifest_path = db_path / MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Corrupt RAG manifest at %s (%s) — rebuilding all collections", manifest_path, e)
        return {}


def _save_manifest(db_path: Path, docs_manifest: dict) -> None:
    manifest_path = db_path / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps({"docs": docs_manifest}, indent=2), encoding="utf-8")


def embed_all_docs(docs_dir: Path = None, db_path: Path = None, embedding_model: str = None):
    """(Re-)embed only the collections whose source doc content, embedding model,
    or chunker version have changed since the last run.

    Previously this ran once ever (llm/__init__.py skipped it whenever
    chroma.sqlite3 already existed), so an edited doc never reached the index
    unless someone deleted the whole database by hand. The manifest recorded here
    makes each collection's staleness individually checkable, so a doc edit is
    picked up on the next startup without a full rebuild, and unrelated
    collections are left untouched.
    """
    if docs_dir is None:
        docs_dir = Path(__file__).resolve().parent.parent / "docs"
    if db_path is None:
        db_path = Path(__file__).resolve().parent / "chroma_db"
    if embedding_model is None:
        embedding_model = DEFAULT_EMBEDDING_MODEL

    db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_path))
    ef = embedding_functions.DefaultEmbeddingFunction()

    prev_docs_manifest = _load_manifest(db_path).get("docs", {})
    new_docs_manifest = {}
    rebuilt, skipped = [], []

    for agent_name, filename in AGENT_DOC_FILES.items():
        doc_path = docs_dir / filename
        if not doc_path.exists():
            logger.warning("Skipping %s — %s not found", agent_name, doc_path)
            continue

        text = doc_path.read_text(encoding="utf-8")
        content_hash = _sha256(text)

        prev = prev_docs_manifest.get(agent_name, {})
        unchanged = (
            prev.get("sha256") == content_hash
            and prev.get("embedding_model") == embedding_model
            and prev.get("chunker_version") == CHUNKER_VERSION
        )
        try:
            client.get_collection(name=agent_name, embedding_function=ef)
            collection_exists = True
        except Exception:
            collection_exists = False

        if unchanged and collection_exists:
            skipped.append(agent_name)
            new_docs_manifest[agent_name] = prev
            continue

        chunks = chunk_markdown(text)
        if not chunks:
            logger.warning("No content chunks for %s", agent_name)
            continue

        try:
            client.delete_collection(agent_name)
        except Exception:
            pass

        collection = client.create_collection(name=agent_name, embedding_function=ef)
        collection.add(
            documents=[c["text"] for c in chunks],
            metadatas=[{"source": filename, "heading": c["heading"]} for c in chunks],
            ids=[f"{agent_name}_chunk_{i}" for i in range(len(chunks))],
        )

        new_docs_manifest[agent_name] = {
            "sha256": content_hash,
            "embedding_model": embedding_model,
            "chunker_version": CHUNKER_VERSION,
            "chunks": len(chunks),
        }
        rebuilt.append(agent_name)
        logger.info("Embedded %d chunks for %s", len(chunks), agent_name)

    _save_manifest(db_path, new_docs_manifest)

    if rebuilt:
        logger.info("RAG: rebuilt collection(s) for %s", ", ".join(rebuilt))
    if skipped:
        logger.info("RAG: skipped unchanged collection(s) for %s", ", ".join(skipped))
    logger.info("RAG database saved to: %s", db_path)

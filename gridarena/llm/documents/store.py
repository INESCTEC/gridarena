"""Filesystem storage for document assistants: one manifest + a sources/
directory per agent, under LVGPLAY_DATA_DIR (never inside the installed
package -- see LLM-13).

    data/llm/document_agents/<agent_id>/
        agent.json                       # manifest
        sources/<source_id>__<original filename>

agent_id and source_id are always server-generated (never taken from a
request), but every path built from one is still validated against the
expected id shape before use -- the same defence-in-depth already applied to
run_id elsewhere in this codebase (see improvement_plan.md task 14).
"""

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(data_dir: Path) -> Path:
    return Path(data_dir) / "document_agents"


def _agent_dir(data_dir: Path, agent_id: str) -> Path:
    _validate_id(agent_id, "agent_id")
    return _root(data_dir) / agent_id


def _manifest_path(data_dir: Path, agent_id: str) -> Path:
    return _agent_dir(data_dir, agent_id) / "agent.json"


def sources_dir(data_dir: Path, agent_id: str) -> Path:
    return _agent_dir(data_dir, agent_id) / "sources"


def load_manifest(data_dir: Path, agent_id: str) -> Optional[Dict[str, Any]]:
    path = _manifest_path(data_dir, agent_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(data_dir: Path, manifest: Dict[str, Any]) -> None:
    agent_id = _validate_id(manifest["agent_id"], "agent_id")
    path = _manifest_path(data_dir, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now()
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def create_agent(data_dir: Path, name: str, description: str) -> Dict[str, Any]:
    agent_id = new_id()
    sources_dir(data_dir, agent_id).mkdir(parents=True, exist_ok=True)
    manifest = {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "created_at": now(),
        "updated_at": now(),
        "sources": [],
    }
    save_manifest(data_dir, manifest)
    return manifest


def list_agents(data_dir: Path) -> List[Dict[str, Any]]:
    root = _root(data_dir)
    if not root.exists():
        return []
    agents = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not _ID_RE.match(child.name):
            continue
        manifest = load_manifest(data_dir, child.name)
        if manifest is not None:
            agents.append(manifest)
    return agents


def delete_agent(data_dir: Path, chroma_db_path: Path, agent_id: str) -> bool:
    """Remove an agent's directory and its Chroma collection."""
    agent_dir = _agent_dir(data_dir, agent_id)
    if not agent_dir.exists():
        return False
    shutil.rmtree(agent_dir)

    # Deferred import: ingest.py imports store.py, so importing it back at this
    # module's top level would be circular.
    from gridarena.llm.documents import ingest
    ingest.delete_collection(chroma_db_path, agent_id)
    return True


def source_path(data_dir: Path, agent_id: str, source_id: str) -> Optional[Path]:
    """Resolve a source's file path ONLY via the manifest -- never by
    concatenating agent_id/source_id/filename directly. A source_id that isn't
    actually listed in the manifest resolves to None even if it matches the id
    shape, so a guessed or stale id can never reach a file."""
    _validate_id(source_id, "source_id")
    manifest = load_manifest(data_dir, agent_id)
    if manifest is None:
        return None
    for src in manifest.get("sources", []):
        if src["source_id"] == source_id:
            path = sources_dir(data_dir, agent_id) / f"{source_id}__{src['filename']}"
            return path if path.exists() else None
    return None


def add_source_to_manifest(data_dir: Path, agent_id: str, source: Dict[str, Any]) -> Dict[str, Any]:
    manifest = load_manifest(data_dir, agent_id)
    if manifest is None:
        raise ValueError(f"No such document agent: {agent_id}")
    manifest["sources"] = [s for s in manifest["sources"] if s["source_id"] != source["source_id"]]
    manifest["sources"].append(source)
    save_manifest(data_dir, manifest)
    return manifest


def remove_source_from_manifest(data_dir: Path, agent_id: str, source_id: str) -> Optional[Dict[str, Any]]:
    manifest = load_manifest(data_dir, agent_id)
    if manifest is None:
        return None
    before = len(manifest["sources"])
    manifest["sources"] = [s for s in manifest["sources"] if s["source_id"] != source_id]
    if len(manifest["sources"]) == before:
        return None
    save_manifest(data_dir, manifest)
    return manifest

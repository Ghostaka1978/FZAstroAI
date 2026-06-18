from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..json_store import atomic_write_json


@dataclass(frozen=True)
class StoredDevSession:
    id: str
    created_at: str
    request: str
    mode: str
    selected_files: tuple[str, ...]
    plan_markdown: str


def save_dev_session(root: Path | str, session: StoredDevSession) -> Path:
    directory = Path(root).resolve() / ".fzastro_ai_dev_sessions"
    path = directory / f"{session.id}.json"
    atomic_write_json(path, asdict(session), indent=2)
    return path


def make_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

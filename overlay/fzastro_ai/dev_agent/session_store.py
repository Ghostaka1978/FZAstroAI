from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


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
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session.id}.json"
    path.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
    return path


def make_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

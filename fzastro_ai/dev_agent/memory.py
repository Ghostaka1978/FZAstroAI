from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .prompt import PROJECT_RULES


def default_memory_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "FZAstroAI"
    return Path.home() / ".fzastro_ai"


@dataclass(frozen=True)
class DeveloperAgentMemory:
    rules: tuple[str, ...]
    path: str
    last_project_root: str = ""


def load_developer_agent_memory(
    memory_dir: Path | str | None = None,
) -> DeveloperAgentMemory:
    """Load stable project facts for Developer Agent Mode."""

    directory = Path(memory_dir) if memory_dir is not None else default_memory_dir()
    path = directory / "developer_agent_memory.json"
    rules = list(PROJECT_RULES)
    last_project_root = ""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("rules", []):
                if isinstance(item, str) and item and item not in rules:
                    rules.append(item)
            last_project_root = str(data.get("last_project_root") or "").strip()
        except Exception:
            pass
    return DeveloperAgentMemory(
        rules=tuple(rules), path=str(path), last_project_root=last_project_root
    )


def save_developer_agent_memory(
    rules: tuple[str, ...] | list[str],
    memory_dir: Path | str | None = None,
    *,
    last_project_root: Path | str | None = None,
) -> DeveloperAgentMemory:
    directory = Path(memory_dir) if memory_dir is not None else default_memory_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "developer_agent_memory.json"
    unique_rules = tuple(
        dict.fromkeys(str(rule).strip() for rule in rules if str(rule).strip())
    )
    root_text = str(last_project_root or "").strip()
    path.write_text(
        json.dumps(
            {"rules": list(unique_rules), "last_project_root": root_text}, indent=2
        ),
        encoding="utf-8",
    )
    return DeveloperAgentMemory(
        rules=unique_rules, path=str(path), last_project_root=root_text
    )


def save_developer_agent_last_project_root(
    project_root: Path | str,
    memory_dir: Path | str | None = None,
) -> DeveloperAgentMemory:
    """Persist the last valid Developer Agent project root.

    The project root is a user convenience setting, not an authorization
    boundary. Safety checks still resolve and validate every file operation
    against the currently selected root.
    """

    current = load_developer_agent_memory(memory_dir)
    root = Path(project_root).expanduser().resolve()
    return save_developer_agent_memory(
        current.rules,
        memory_dir=memory_dir,
        last_project_root=str(root),
    )

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_BLOCKED_DIRS = {"external", "bundled_apps"}
DEFAULT_MUTATION_BLOCKED_DIRS = DEFAULT_BLOCKED_DIRS | {
    ".git",
    ".venv",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
}

SAFE_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "compileall"),
    ("python", "-m", "pytest"),
    ("python.exe", "-m", "compileall"),
    ("python.exe", "-m", "pytest"),
    ("python3", "-m", "compileall"),
    ("python3", "-m", "pytest"),
    ("py", "-m", "compileall"),
    ("py", "-m", "pytest"),
    ("py.exe", "-m", "compileall"),
    ("py.exe", "-m", "pytest"),
)

DANGEROUS_COMMAND_WORDS = {
    "del",
    "erase",
    "format",
    "kill",
    "pkill",
    "powershell",
    "rd",
    "reg",
    "rm",
    "rmdir",
    "shutdown",
    "start",
    "stop",
}


class DevAgentSafetyError(ValueError):
    """Raised when an agent tool request violates project safety rules."""


@dataclass(frozen=True)
class SafePath:
    relative: str
    absolute: Path


def _parts_for(relative_path: str) -> tuple[str, ...]:
    raw = str(relative_path or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw.startswith("/") or ":" in raw or path.is_absolute():
        raise DevAgentSafetyError(f"Unsafe path: {relative_path!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise DevAgentSafetyError(f"Unsafe path traversal: {relative_path!r}")
    return path.parts


def resolve_project_path(
    root: Path | str,
    relative_path: str,
    *,
    allow_blocked: bool = False,
    blocked_dirs: set[str] | None = None,
) -> SafePath:
    """Resolve a project-relative path and guarantee it stays inside root."""

    root_path = Path(root).resolve()
    parts = _parts_for(relative_path)
    blocked = DEFAULT_MUTATION_BLOCKED_DIRS if blocked_dirs is None else blocked_dirs
    if not allow_blocked and parts and parts[0] in blocked:
        raise DevAgentSafetyError(f"Blocked project area: {parts[0]}")
    absolute = (root_path / Path(*parts)).resolve()
    try:
        absolute.relative_to(root_path)
    except ValueError as exc:
        raise DevAgentSafetyError(
            f"Path escapes project root: {relative_path!r}"
        ) from exc
    return SafePath(relative="/".join(parts), absolute=absolute)


def is_path_blocked(
    relative_path: str, *, blocked_dirs: set[str] | None = None
) -> bool:
    try:
        parts = _parts_for(relative_path)
    except DevAgentSafetyError:
        return True
    blocked = DEFAULT_MUTATION_BLOCKED_DIRS if blocked_dirs is None else blocked_dirs
    return bool(parts and parts[0] in blocked)


def command_requires_approval(command: tuple[str, ...] | list[str]) -> bool:
    """Return True unless the command matches the small validation allow-list."""

    if not command:
        return True
    normalized = tuple(str(part).strip() for part in command if str(part).strip())
    if not normalized:
        return True
    lowered = tuple(
        Path(part).name.lower() if i == 0 else part.lower()
        for i, part in enumerate(normalized)
    )
    executable = lowered[0]
    if any(word in executable for word in DANGEROUS_COMMAND_WORDS):
        return True
    if any(lowered[: len(prefix)] == prefix for prefix in SAFE_COMMAND_PREFIXES):
        return False
    return True


def format_command(command: tuple[str, ...] | list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_SOURCE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".ps1",
    ".spec",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
}

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "AppData",
    "build",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "__pycache__",
}

DEFAULT_IGNORE_NAMES = {
    ".coverage",
    "fzastroai.log",
    "document_knowledge.sqlite3",
    "memory.json",
    "history.json",
}

GENERATED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".bak",
    ".orig",
    ".rej",
)

BACKUP_MARKERS = (
    ".broken",
    ".bak_",
    "bak_",
    ".blackfix.bak",
    ".futurefix.bak",
)


@dataclass(frozen=True)
class ProjectFile:
    """Compact metadata for one project file."""

    path: str
    size: int
    extension: str
    role: str
    symbols: tuple[str, ...] = field(default_factory=tuple)
    imports: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProjectScan:
    """Static project scan result used by the code-building workflow."""

    root: str
    files: tuple[ProjectFile, ...]
    ignored_count: int = 0
    oversized_count: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def python_count(self) -> int:
        return sum(1 for file in self.files if file.extension == ".py")

    @property
    def test_count(self) -> int:
        return sum(1 for file in self.files if file.role == "test")

    @property
    def total_bytes(self) -> int:
        return sum(file.size for file in self.files)

    def by_path(self) -> Mapping[str, ProjectFile]:
        return {file.path: file for file in self.files}


def _normalize_path(path: Path) -> str:
    return path.as_posix()


def _should_ignore_path(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path

    parts = set(relative.parts)
    if parts.intersection(DEFAULT_IGNORE_DIRS):
        return True

    name = path.name
    lower_name = name.lower()

    if name in DEFAULT_IGNORE_NAMES:
        return True

    if lower_name.endswith(GENERATED_SUFFIXES):
        return True

    return any(marker in lower_name for marker in BACKUP_MARKERS)


def _classify_file(relative_path: str) -> str:
    lower = relative_path.lower()
    name = Path(relative_path).name.lower()

    if (
        lower.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
    ):
        return "test"
    if lower.startswith("docs/") or name in {
        "readme.md",
        "release_validation.md",
        "rc3_final_production_notes.md",
    }:
        return "docs"
    if lower.startswith("fzastro_ai/ui/"):
        return "ui"
    if lower.startswith("fzastro_ai/actions/"):
        return "actions"
    if lower.startswith("fzastro_ai/workers/") or name.endswith("worker.py"):
        return "worker"
    if lower.startswith("fzastro_ai/astro_tools/"):
        return "astro_tools"
    if lower.startswith("fzastro_ai/dev_agent/"):
        return "dev_agent"
    if name.endswith(".ps1") or "build" in name or "deploy" in name:
        return "build"
    if lower.startswith("fzastro_ai/"):
        return "core"
    return "project"


def _extract_python_symbols(
    path: Path, max_symbols: int = 80
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except Exception:
        return (), ()

    symbols: list[str] = []
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])

        if len(symbols) >= max_symbols and len(imports) >= max_symbols:
            break

    return tuple(dict.fromkeys(symbols[:max_symbols])), tuple(
        dict.fromkeys(imports[:max_symbols])
    )


def iter_project_files(
    root: Path | str,
    *,
    extensions: Iterable[str] | None = None,
    max_file_size: int = 600_000,
) -> Iterable[ProjectFile]:
    """Yield project files worth considering for developer context."""

    root_path = Path(root).resolve()
    allowed = set(extensions or DEFAULT_SOURCE_EXTENSIONS)

    for current_root, dir_names, file_names in os.walk(root_path):
        current = Path(current_root)
        dir_names[:] = [
            directory
            for directory in dir_names
            if not _should_ignore_path(current / directory, root_path)
        ]

        for file_name in sorted(file_names):
            absolute = current / file_name
            if _should_ignore_path(absolute, root_path):
                continue

            extension = absolute.suffix.lower()
            if extension not in allowed:
                continue

            try:
                size = absolute.stat().st_size
            except OSError:
                continue

            if size > max_file_size:
                continue

            relative = _normalize_path(absolute.relative_to(root_path))
            symbols: tuple[str, ...] = ()
            imports: tuple[str, ...] = ()
            if extension == ".py":
                symbols, imports = _extract_python_symbols(absolute)

            yield ProjectFile(
                path=relative,
                size=size,
                extension=extension,
                role=_classify_file(relative),
                symbols=symbols,
                imports=imports,
            )


def scan_project(
    root: Path | str,
    *,
    extensions: Iterable[str] | None = None,
    max_file_size: int = 600_000,
) -> ProjectScan:
    """Scan a project tree and return a compact, deterministic inventory."""

    root_path = Path(root).resolve()
    files: list[ProjectFile] = []
    ignored_count = 0
    oversized_count = 0
    allowed = set(extensions or DEFAULT_SOURCE_EXTENSIONS)

    for current_root, dir_names, file_names in os.walk(root_path):
        current = Path(current_root)
        kept_dirs = []
        for directory in dir_names:
            if _should_ignore_path(current / directory, root_path):
                ignored_count += 1
            else:
                kept_dirs.append(directory)
        dir_names[:] = kept_dirs

        for file_name in sorted(file_names):
            absolute = current / file_name
            if _should_ignore_path(absolute, root_path):
                ignored_count += 1
                continue
            if absolute.suffix.lower() not in allowed:
                ignored_count += 1
                continue
            try:
                size = absolute.stat().st_size
            except OSError:
                ignored_count += 1
                continue
            if size > max_file_size:
                oversized_count += 1
                continue

            relative = _normalize_path(absolute.relative_to(root_path))
            symbols: tuple[str, ...] = ()
            imports: tuple[str, ...] = ()
            if absolute.suffix.lower() == ".py":
                symbols, imports = _extract_python_symbols(absolute)

            files.append(
                ProjectFile(
                    path=relative,
                    size=size,
                    extension=absolute.suffix.lower(),
                    role=_classify_file(relative),
                    symbols=symbols,
                    imports=imports,
                )
            )

    files.sort(key=lambda item: item.path.lower())
    return ProjectScan(
        root=str(root_path),
        files=tuple(files),
        ignored_count=ignored_count,
        oversized_count=oversized_count,
    )

from __future__ import annotations

import ast
import re
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .project_scanner import ProjectFile, ProjectScan, scan_project
from .safety import DevAgentSafetyError, resolve_project_path


class DevFileToolError(ValueError):
    """Raised when a safe developer file tool cannot complete."""


class DeveloperFileTools:
    """Safe, project-root-bounded file inspection tools for OpenClaude."""

    def __init__(self, project_root: Path | str, *, max_read_bytes: int = 300_000):
        self.project_root = Path(project_root).resolve()
        self.max_read_bytes = max_read_bytes
        self._last_scan: ProjectScan | None = None

    def scan(self) -> ProjectScan:
        self._last_scan = scan_project(self.project_root)
        return self._last_scan

    def list_files(
        self,
        *,
        role: str | None = None,
        pattern: str | None = None,
        limit: int = 250,
    ) -> list[dict[str, object]]:
        scan = self._last_scan or self.scan()
        regex = re.compile(pattern, re.IGNORECASE) if pattern else None
        files: Iterable[ProjectFile] = scan.files
        if role:
            files = (file for file in files if file.role == role)
        if regex:
            files = (file for file in files if regex.search(file.path))
        return [asdict(file) for file in list(files)[: max(1, limit)]]

    def read_file(self, relative_path: str, *, max_chars: int = 50_000) -> str:
        safe = resolve_project_path(
            self.project_root,
            relative_path,
            allow_blocked=True,
            blocked_dirs={
                ".git",
                ".venv",
                "build",
                "dist",
                "__pycache__",
                ".pytest_cache",
            },
        )
        if not safe.absolute.exists() or not safe.absolute.is_file():
            raise DevFileToolError(f"File not found: {safe.relative}")
        size = safe.absolute.stat().st_size
        if size > self.max_read_bytes:
            raise DevFileToolError(
                f"File too large for safe read: {safe.relative} ({size} bytes)"
            )
        text = safe.absolute.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            return (
                text[:max_chars].rstrip()
                + "\n# ... file truncated by Developer Agent ..."
            )
        return text

    def read_file_range(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        if start_line < 1 or end_line < start_line:
            raise DevFileToolError("Invalid line range")
        text = self.read_file(relative_path, max_chars=self.max_read_bytes)
        lines = text.splitlines()
        selected = lines[start_line - 1 : end_line]
        return "\n".join(
            f"{line_no}: {line}"
            for line_no, line in enumerate(selected, start=start_line)
        )

    def search_text(
        self,
        query: str,
        *,
        case_sensitive: bool = False,
        limit: int = 100,
        context_lines: int = 1,
    ) -> list[dict[str, object]]:
        if not query:
            raise DevFileToolError("Search query is empty")
        scan = self._last_scan or self.scan()
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags)
        except re.error:
            regex = re.compile(re.escape(query), flags)
        matches: list[dict[str, object]] = []
        for file in scan.files:
            if file.extension not in {
                ".py",
                ".md",
                ".txt",
                ".ps1",
                ".json",
                ".toml",
                ".yaml",
                ".yml",
                ".ini",
                ".cfg",
                ".spec",
            }:
                continue
            try:
                text = self.read_file(file.path, max_chars=self.max_read_bytes)
            except (DevFileToolError, DevAgentSafetyError, OSError):
                continue
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                matches.append(
                    {
                        "path": file.path,
                        "line": index + 1,
                        "text": line.strip(),
                        "context": "\n".join(lines[start:end]),
                    }
                )
                if len(matches) >= limit:
                    return matches
        return matches

    def show_symbol(self, symbol: str, *, limit: int = 20) -> list[dict[str, object]]:
        if not symbol:
            raise DevFileToolError("Symbol name is empty")
        scan = self._last_scan or self.scan()
        results: list[dict[str, object]] = []
        for file in scan.files:
            if file.extension != ".py" or symbol not in file.symbols:
                continue
            try:
                text = self.read_file(file.path, max_chars=self.max_read_bytes)
                tree = ast.parse(text)
            except Exception:
                results.append({"path": file.path, "symbol": symbol, "line": None})
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    )
                    and node.name == symbol
                ):
                    results.append(
                        {
                            "path": file.path,
                            "symbol": symbol,
                            "line": getattr(node, "lineno", None),
                            "kind": type(node).__name__,
                        }
                    )
                    if len(results) >= limit:
                        return results
        return results

    def summarize_changes(self, paths: Iterable[str]) -> dict[str, object]:
        changed: list[dict[str, object]] = []
        python_changed = False
        for raw in paths:
            safe = resolve_project_path(self.project_root, raw, allow_blocked=False)
            exists = safe.absolute.exists()
            suffix = safe.absolute.suffix.lower()
            if suffix == ".py":
                python_changed = True
            changed.append(
                {
                    "path": safe.relative,
                    "exists": exists,
                    "extension": suffix,
                    "size": (
                        safe.absolute.stat().st_size
                        if exists and safe.absolute.is_file()
                        else 0
                    ),
                }
            )
        return {
            "changed_files": changed,
            "python_changed": python_changed,
            "exe_rebuild_required": python_changed,
        }

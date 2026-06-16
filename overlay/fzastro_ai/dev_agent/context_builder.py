from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .project_scanner import ProjectFile, ProjectScan, scan_project
from .task_classifier import DevTask, classify_dev_task

TRACEBACK_PATH_RE = re.compile(r'File "(?P<path>[^"]+\.py)", line (?P<line>\d+)')


@dataclass(frozen=True)
class ContextFile:
    """One selected file with a rank and optional text excerpt."""

    path: str
    score: float
    role: str
    reason: str
    excerpt: str = ""
    symbols: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DevContext:
    """The compact developer context shown to the user/model."""

    task: DevTask
    root: str
    files: tuple[ContextFile, ...]
    summary: str
    prompt_package: str


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", text or "")}


def _path_matches_hint(path: str, hint: str) -> bool:
    normalized_path = path.replace("\\", "/").lower()
    normalized_hint = hint.replace("\\", "/").lower()
    return normalized_path.endswith(normalized_hint) or normalized_hint in normalized_path


def _traceback_path_hints(extra_text: str) -> tuple[str, ...]:
    hints: list[str] = []
    for match in TRACEBACK_PATH_RE.finditer(extra_text or ""):
        raw_path = match.group("path").replace("\\", "/")
        parts = raw_path.split("/")
        for index, part in enumerate(parts):
            if part == "fzastro_ai" or part == "tests":
                hints.append("/".join(parts[index:]))
                break
        else:
            hints.append(parts[-1])
    return tuple(dict.fromkeys(hints))


def _score_file(file: ProjectFile, task: DevTask, extra_text: str = "") -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    lower_path = file.path.lower()
    path_tokens = _tokenize(file.path.replace("/", " ").replace("_", " "))
    symbol_tokens = _tokenize(" ".join(file.symbols))
    request_tokens = set(task.terms)

    overlap = request_tokens.intersection(path_tokens | symbol_tokens)
    if overlap:
        score += len(overlap) * 5.0
        reasons.append("matches request terms: " + ", ".join(sorted(overlap)[:6]))

    all_hints = tuple(task.path_hints) + _traceback_path_hints(extra_text)
    for hint in all_hints:
        if _path_matches_hint(file.path, hint):
            score += 40.0
            reasons.append(f"explicit path hint: {hint}")
            break

    if task.role_hints and file.role in task.role_hints:
        score += 10.0
        reasons.append(f"role hint: {file.role}")

    if task.mode == "test" and file.role == "test":
        score += 7.0
        reasons.append("test-mode candidate")
    elif task.mode == "release" and file.role in {"docs", "build"}:
        score += 8.0
        reasons.append("release-mode candidate")
    elif task.mode == "patch" and file.role in {"core", "ui", "actions", "worker", "astro_tools"}:
        score += 3.0

    if "fzastro_ai/app.py" == lower_path:
        score += 2.0
        reasons.append("main application integration point")

    if lower_path.endswith("/__init__.py") and score > 0:
        score += 1.5
        reasons.append("package export/integration point")

    return score, reasons


def _read_excerpt(root: Path, path: str, max_chars: int) -> str:
    absolute = root / path
    try:
        text = absolute.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    if len(text) <= max_chars:
        return text

    head = max_chars // 2
    tail = max_chars - head
    return text[:head].rstrip() + "\n\n# ... excerpt truncated ...\n\n" + text[-tail:].lstrip()


def _make_summary(task: DevTask, selected: list[ContextFile], scan: ProjectScan) -> str:
    lines = [
        f"Mode: {task.mode}",
        f"Confidence: {task.confidence:.2f}",
        f"Project files scanned: {scan.file_count} ({scan.python_count} Python, {scan.test_count} tests)",
        f"Selected context files: {len(selected)}",
    ]
    if task.role_hints:
        lines.append("Role hints: " + ", ".join(task.role_hints))
    if task.path_hints:
        lines.append("Path hints: " + ", ".join(task.path_hints))
    return "\n".join(lines)


def build_prompt_package(
    task: DevTask,
    selected: list[ContextFile],
    *,
    max_chars: int = 42_000,
) -> str:
    """Build the model-facing, reviewable context package."""

    header = [
        "# FZAstro AI Developer Workbench Context",
        "",
        "## User request",
        task.request or "(empty request)",
        "",
        "## Visible workflow rules",
        "- Inspect relevant files before proposing edits.",
        "- Prefer unified diffs over full-file rewrites.",
        "- Preserve existing behavior unless the request explicitly changes it.",
        "- Add or update regression tests when behavior changes.",
        "- After patching, run compileall and targeted pytest when possible.",
        "",
        "## Selected files",
    ]

    for item in selected:
        header.append(f"- {item.path} [{item.role}] — {item.reason}")

    parts = ["\n".join(header).rstrip()]
    remaining = max_chars - len(parts[0])

    for item in selected:
        if remaining <= 1200:
            break
        excerpt = item.excerpt
        if not excerpt:
            continue
        fence = "```"
        block = f"\n\n## File: {item.path}\n{fence}\n{excerpt}\n{fence}\n"
        if len(block) > remaining:
            block = block[: remaining - 80].rstrip() + "\n# ... context package truncated ...\n```\n"
        parts.append(block)
        remaining -= len(block)

    return "".join(parts).strip()


def build_dev_context(
    root: Path | str,
    request: str,
    *,
    scan: ProjectScan | None = None,
    extra_text: str = "",
    max_files: int = 12,
    max_excerpt_chars: int = 8_000,
    max_prompt_chars: int = 42_000,
) -> DevContext:
    """Select and package files likely to be useful for a coding task."""

    root_path = Path(root).resolve()
    project_scan = scan or scan_project(root_path)
    task = classify_dev_task(request)

    ranked: list[tuple[float, ProjectFile, list[str]]] = []
    for file in project_scan.files:
        score, reasons = _score_file(file, task, extra_text=extra_text)
        if score > 0:
            ranked.append((score, file, reasons))

    if not ranked:
        ranked = [
            (1.0, file, ["general project context"])
            for file in project_scan.files
            if file.path in {"README.md", "fzastro_ai/app.py", "fzastro_ai/config.py"}
        ]

    ranked.sort(key=lambda item: (-item[0], item[1].path.lower()))
    selected: list[ContextFile] = []
    for score, file, reasons in ranked[:max_files]:
        selected.append(
            ContextFile(
                path=file.path,
                score=round(score, 2),
                role=file.role,
                reason="; ".join(dict.fromkeys(reasons)),
                excerpt=_read_excerpt(root_path, file.path, max_excerpt_chars),
                symbols=file.symbols,
            )
        )

    summary = _make_summary(task, selected, project_scan)
    prompt_package = build_prompt_package(task, selected, max_chars=max_prompt_chars)
    return DevContext(
        task=task,
        root=str(root_path),
        files=tuple(selected),
        summary=summary,
        prompt_package=prompt_package,
    )

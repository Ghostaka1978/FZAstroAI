from __future__ import annotations

import re
from dataclasses import dataclass, field

MODE_KEYWORDS = {
    "patch": {
        "add",
        "build",
        "change",
        "create",
        "fix",
        "implement",
        "improve",
        "patch",
        "refactor",
        "remove",
        "update",
    },
    "test": {
        "compile",
        "coverage",
        "fail",
        "failing",
        "pytest",
        "regression",
        "test",
        "traceback",
        "validate",
    },
    "release": {
        "build_exe",
        "changelog",
        "deploy",
        "docs",
        "github release",
        "release",
        "tag",
        "version",
    },
    "ask": {
        "explain",
        "overview",
        "where",
        "why",
        "what",
        "understand",
    },
}

ROLE_HINTS = {
    "web_companion": {
        "api",
        "auth",
        "credential",
        "lan",
        "localhost",
        "server",
        "token",
        "web companion",
        "web_companion",
    },
    "ui": {
        "button",
        "dialog",
        "label",
        "layout",
        "screen",
        "tab",
        "ui",
        "widget",
        "window",
    },
    "actions": {"action", "handler", "open", "trigger"},
    "worker": {"background", "thread", "worker", "shutdown", "timeout"},
    "astro_tools": {"astro", "bortle", "moon", "seeing", "solar", "target", "sun"},
    "dev_agent": {
        "developer agent",
        "dev agent",
        "dev_agent",
        "scanner",
        "tool loop",
        "test runner",
    },
    "docs": {"about", "docs", "help", "markdown", "readme", "release notes"},
    "build": {"build", "exe", "installer", "pyinstaller", "powershell", "release"},
    "test": {"pytest", "regression", "smoke", "test"},
}

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_.-]+)?|[A-Za-z0-9_.-]+\.py"
)

PROJECT_AUDIT_PATTERNS = (
    re.compile(
        r"\b(all|every|entire|whole)\b.{0,40}\b(python|py|code|source|project|app|files|modules)\b"
    ),
    re.compile(
        r"\b(python|py|code|source|project|app|files|modules)\b.{0,40}\b(all|every|entire|whole)\b"
    ),
    re.compile(
        r"\b(deep|full|complete|comprehensive)\s+(analysis|analyse|analyze|review|audit)\b"
    ),
    re.compile(
        r"\b(analyse|analyze|review|audit)\s+(my|the|this)\s+(app|project|codebase|code)\b"
    ),
    re.compile(r"\b(identify|find|list)\s+(risks|issues|problems)\b"),
    re.compile(r"\b(risk assessment|project audit|codebase audit)\b"),
)


@dataclass(frozen=True)
class DevTask:
    """Normalized representation of a developer-workbench request."""

    request: str
    mode: str
    terms: tuple[str, ...] = field(default_factory=tuple)
    path_hints: tuple[str, ...] = field(default_factory=tuple)
    role_hints: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    scope: str = "focused"


def _normalize_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in TOKEN_RE.finditer(text.lower()):
        term = match.group(0)
        if len(term) < 2:
            continue
        if term in {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "into",
            "please",
        }:
            continue
        terms.append(term)
    return tuple(dict.fromkeys(terms))


def _extract_path_hints(text: str) -> tuple[str, ...]:
    raw_hints = [match.group(0).replace("\\", "/") for match in PATH_RE.finditer(text)]
    hints: list[str] = []
    known_roots = ("fzastro_ai/", "tests/", "docs/", "scripts/", "resources/")
    known_suffixes = (
        ".py",
        ".md",
        ".ps1",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".spec",
        ".txt",
    )
    for hint in raw_hints:
        lower = hint.lower()
        if lower.endswith(known_suffixes) or lower.startswith(known_roots):
            hints.append(hint)
    return tuple(dict.fromkeys(hints))


def _inferred_path_hints(lower: str) -> tuple[str, ...]:
    """Return inferred path hints.

    Path hints are intentionally reserved for paths the user explicitly names.
    Earlier builds injected domain-specific files here, which made the planner
    brittle. Relevance now comes from generic task terms, content evidence,
    import/test relationships, and explicit user-provided paths.
    """

    return ()


def _keyword_matches(lower: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    if any(ch in keyword for ch in " _-/."):
        return keyword.lower() in lower
    return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", lower) is not None


def _detect_scope(lower: str, path_hints: tuple[str, ...]) -> str:
    """Detect whether a task needs a focused context or whole-project audit index."""

    if path_hints:
        return "focused"
    if any(pattern.search(lower) for pattern in PROJECT_AUDIT_PATTERNS):
        return "project_audit"
    return "focused"


def classify_dev_task(request: str) -> DevTask:
    """Classify a code-building request into a visible workflow mode."""

    clean = str(request or "").strip()
    lower = clean.lower()
    terms = _normalize_terms(lower)
    path_hints = tuple(
        dict.fromkeys(_extract_path_hints(clean) + _inferred_path_hints(lower))
    )

    scores = {mode: 0 for mode in MODE_KEYWORDS}
    for mode, keywords in MODE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                scores[mode] += 2 if " " in keyword else 1

    if path_hints and scores["ask"] == max(scores.values()):
        scores["patch"] += 1

    mode = max(scores, key=scores.get)
    if scores[mode] == 0:
        mode = "ask"

    scope = _detect_scope(lower, path_hints)

    role_scores: dict[str, int] = {}
    for role, keywords in ROLE_HINTS.items():
        matched_keywords = [
            keyword for keyword in keywords if _keyword_matches(lower, keyword)
        ]
        if role == "ui" and matched_keywords == ["ui"]:
            constraint_markers = (
                "do not break",
                "dont break",
                "preserve",
                "without breaking",
            )
            concrete_ui_terms = (
                "button",
                "dialog",
                "layout",
                "screen",
                "tab",
                "widget",
                "window",
                "style",
            )
            if any(marker in lower for marker in constraint_markers) and not any(
                term in lower for term in concrete_ui_terms
            ):
                matched_keywords = []
        score = len(matched_keywords)
        if score:
            role_scores[role] = score

    role_hints = tuple(
        role
        for role, _score in sorted(
            role_scores.items(), key=lambda item: (-item[1], item[0])
        )
    )

    confidence = min(
        1.0,
        0.25
        + (scores.get(mode, 0) * 0.12)
        + (len(role_hints) * 0.08)
        + (0.12 if scope == "project_audit" else 0.0),
    )

    return DevTask(
        request=clean,
        mode=mode,
        terms=terms,
        path_hints=path_hints,
        role_hints=role_hints,
        confidence=round(confidence, 2),
        scope=scope,
    )

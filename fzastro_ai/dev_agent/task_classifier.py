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
        "code",
        "developer",
        "diff",
        "patch",
        "project",
        "scanner",
        "test runner",
    },
    "docs": {"about", "docs", "help", "markdown", "readme", "release notes"},
    "build": {"build", "exe", "installer", "pyinstaller", "powershell", "release"},
    "test": {"pytest", "regression", "smoke", "test"},
}

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
PATH_RE = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.py")


@dataclass(frozen=True)
class DevTask:
    """Normalized representation of a developer-workbench request."""

    request: str
    mode: str
    terms: tuple[str, ...] = field(default_factory=tuple)
    path_hints: tuple[str, ...] = field(default_factory=tuple)
    role_hints: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0


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
    hints = [match.group(0).replace("\\", "/") for match in PATH_RE.finditer(text)]
    return tuple(dict.fromkeys(hints))


def classify_dev_task(request: str) -> DevTask:
    """Classify a code-building request into a visible workflow mode."""

    clean = str(request or "").strip()
    lower = clean.lower()
    terms = _normalize_terms(lower)
    path_hints = _extract_path_hints(clean)

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

    role_scores: dict[str, int] = {}
    for role, keywords in ROLE_HINTS.items():
        score = sum(1 for keyword in keywords if keyword in lower)
        if score:
            role_scores[role] = score

    role_hints = tuple(
        role
        for role, _score in sorted(
            role_scores.items(), key=lambda item: (-item[1], item[0])
        )
    )

    confidence = min(
        1.0, 0.25 + (scores.get(mode, 0) * 0.12) + (len(role_hints) * 0.08)
    )

    return DevTask(
        request=clean,
        mode=mode,
        terms=terms,
        path_hints=path_hints,
        role_hints=role_hints,
        confidence=round(confidence, 2),
    )

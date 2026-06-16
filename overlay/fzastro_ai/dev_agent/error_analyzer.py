from __future__ import annotations

import re
from dataclasses import dataclass, field

TRACEBACK_RE = re.compile(r'File "(?P<file>[^"]+\.py)", line (?P<line>\d+), in (?P<func>[^\n]+)')
PYTEST_FAIL_RE = re.compile(r"^_{3,}\s+(?P<name>[^_].*?)\s+_{3,}$", re.MULTILINE)
MISSING_ATTR_RE = re.compile(r"AttributeError:\s+(?P<message>.+)")
IMPORT_RE = re.compile(r"(?:ImportError|ModuleNotFoundError):\s+(?P<message>.+)")


@dataclass(frozen=True)
class FailureSummary:
    headline: str
    files: tuple[str, ...] = field(default_factory=tuple)
    failed_tests: tuple[str, ...] = field(default_factory=tuple)
    likely_causes: tuple[str, ...] = field(default_factory=tuple)
    excerpt: str = ""


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def analyze_failure_output(output: str, *, max_excerpt: int = 5000) -> FailureSummary:
    text = str(output or "")
    files: list[str] = []
    causes: list[str] = []

    for match in TRACEBACK_RE.finditer(text):
        raw = match.group("file").replace("\\", "/")
        parts = raw.split("/")
        for index, part in enumerate(parts):
            if part in {"fzastro_ai", "tests"}:
                files.append("/".join(parts[index:]))
                break
        else:
            files.append(parts[-1])

    failed_tests = [match.group("name").strip() for match in PYTEST_FAIL_RE.finditer(text)]

    attr = MISSING_ATTR_RE.search(text)
    if attr:
        causes.append("AttributeError: " + attr.group("message").strip())

    imp = IMPORT_RE.search(text)
    if imp:
        causes.append("Import problem: " + imp.group("message").strip())

    if "SyntaxError" in text:
        causes.append("Syntax error detected")
    if "AssertionError" in text:
        causes.append("Assertion failure detected")
    if "KeyboardInterrupt" in text:
        causes.append("Operation was interrupted")

    headline = "No failure detected"
    if failed_tests:
        headline = f"{len(failed_tests)} pytest failure(s) detected"
    elif causes:
        headline = causes[0]
    elif text.strip():
        headline = "Command failed; review output excerpt"

    excerpt = text[-max_excerpt:] if len(text) > max_excerpt else text
    return FailureSummary(
        headline=headline,
        files=_unique(files),
        failed_tests=_unique(failed_tests),
        likely_causes=_unique(causes),
        excerpt=excerpt.strip(),
    )

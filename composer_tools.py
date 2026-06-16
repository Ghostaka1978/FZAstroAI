"""Helpers for preparing user-composer text before sending.

The functions in this module intentionally stay Qt-free so composer formatting
behavior can be unit tested without starting the GUI.
"""

from __future__ import annotations

import re

_LANGUAGE_RE = re.compile(r"[^A-Za-z0-9_+.#-]+")


def normalize_code_language(language: str | None) -> str:
    """Return a safe fenced-code language tag.

    Markdown code-fence info strings should not contain spaces or arbitrary
    punctuation.  Keep common language tag characters and strip everything else.
    """

    text = str(language or "").strip().lower()
    return _LANGUAGE_RE.sub("", text)


def fenced_code_block(code: str, language: str | None = "") -> str:
    """Return *code* wrapped in a Markdown fenced code block."""

    safe_language = normalize_code_language(language)
    body = str(code or "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.rstrip("\n")
    return f"```{safe_language}\n{body}\n```"


def empty_fenced_code_block(language: str | None = "") -> tuple[str, int]:
    """Return an empty fenced code block and the cursor position inside it."""

    safe_language = normalize_code_language(language)
    prefix = f"```{safe_language}\n"
    text = f"{prefix}\n```"
    return text, len(prefix)

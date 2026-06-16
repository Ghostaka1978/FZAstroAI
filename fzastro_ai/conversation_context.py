"""Conversation-continuity helpers for model prompt construction."""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Any


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for item in content:
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("type") or "").casefold()

            if item_type in {"text", "input_text"}:
                parts.append(str(item.get("text") or ""))
            elif item_type in {"image", "image_url", "input_image"}:
                parts.append("[image attachment]")

        return "\n".join(part for part in parts if part).strip()

    return str(content or "")


def _strip_large_attachment_bodies(text: str) -> str:
    """Keep attachment metadata while removing old large file bodies.

    The current request already receives the full attachment content. For older
    turns, this compact context should remind the model what happened without
    duplicating thousands of lines of source code into the system prompt.
    """
    if "BEGIN ATTACHED FILE:" not in text:
        return text

    pattern = re.compile(
        r"(?s)(BEGIN ATTACHED FILE:\s*([^\n]+)\n).*?(END ATTACHED FILE:\s*\2)",
    )
    return pattern.sub(
        lambda match: (
            f"{match.group(1)}[previous attachment body omitted from compact recent-chat summary]\n"
            f"{match.group(3)}"
        ),
        text,
    )


def _compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()

    if len(text) <= max_chars:
        return text

    head = max(0, max_chars - 80)
    return text[:head].rstrip() + " ... [truncated]"


def build_recent_chat_context(
    messages: Iterable[Mapping[str, Any]],
    *,
    max_messages: int = 8,
    max_chars_per_message: int = 1200,
    max_total_chars: int = 8000,
) -> str:
    """Return a compact system-prompt appendix for recent chat continuity."""
    safe_messages = list(messages or [])[-max(0, int(max_messages)) :]
    rows = []
    used_chars = 0

    for message in safe_messages:
        role = str(message.get("role") or "message").strip().lower()

        if role not in {"user", "assistant", "system"}:
            role = "message"

        content = _content_to_text(message.get("content"))
        content = _strip_large_attachment_bodies(content)
        content = _compact_text(content, max_chars_per_message)

        if not content:
            continue

        row = f"{role.upper()}: {content}"

        if used_chars + len(row) > max_total_chars:
            break

        rows.append(row)
        used_chars += len(row)

    if not rows:
        return ""

    return (
        "\n\n[RECENT CHAT CONTEXT]\n"
        "The following compact transcript summarizes recent turns in the current chat. "
        "Use it for follow-up references such as 'last chat', 'above', 'that file', or 'continue'.\n"
        + "\n".join(rows)
        + "\n[/RECENT CHAT CONTEXT]"
    )

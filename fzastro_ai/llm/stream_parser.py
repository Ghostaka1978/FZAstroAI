"""Shared helpers for streamed OpenAI-compatible chat chunks."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_REASONING_KEYS = ("thinking", "reasoning", "reasoning_content")


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    try:
        if hasattr(value, "model_dump"):
            data = value.model_dump()
        elif hasattr(value, "dict"):
            data = value.dict()
        else:
            return {}
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _first_choice(chunk: Any) -> Any:
    choices = getattr(chunk, "choices", None)

    if not choices:
        return None

    try:
        return choices[0]
    except (IndexError, TypeError):
        return None


def _first_nonempty_mapping_value(mapping: dict[str, Any], keys: tuple[str, ...]):
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _first_nonempty_attr_value(value: Any, keys: tuple[str, ...]):
    for key in keys:
        found = getattr(value, key, None)
        if found:
            return found
    return None


def extract_delta_text(chunk: Any) -> str:
    """Return streamed assistant text from a provider chunk, if present."""
    choice = _first_choice(chunk)
    delta = getattr(choice, "delta", None)
    content = getattr(delta, "content", None)

    if content is None:
        content = _as_mapping(delta).get("content")

    if content is None:
        content = _as_mapping(getattr(delta, "model_extra", None)).get("content")

    return "" if content is None else str(content)


def extract_delta_reasoning(chunk: Any) -> str:
    """Return streamed hidden/thinking text from common provider variants."""
    choice = _first_choice(chunk)
    delta = getattr(choice, "delta", None)

    reasoning = _first_nonempty_attr_value(delta, _REASONING_KEYS)
    if reasoning:
        return str(reasoning)

    reasoning = _first_nonempty_mapping_value(_as_mapping(delta), _REASONING_KEYS)
    if reasoning:
        return str(reasoning)

    for extra_source in (
        getattr(delta, "model_extra", None),
        getattr(choice, "model_extra", None),
        getattr(chunk, "model_extra", None),
    ):
        reasoning = _first_nonempty_mapping_value(
            _as_mapping(extra_source), _REASONING_KEYS
        )
        if reasoning:
            return str(reasoning)

    return ""


def is_expected_stream_close_error(error: BaseException) -> bool:
    """Return True for errors commonly caused by closing a live stream."""
    message = f"{type(error).__module__}.{type(error).__name__}: {error}".casefold()
    expected_markers = (
        "winerror 10038",
        "not a socket",
        "responseclosed",
        "streamclosed",
        "closedresourceerror",
        "operation aborted",
    )
    return any(marker in message for marker in expected_markers)


def looks_like_repetition_loop(text: str, profile: str | None = None) -> bool:
    """Detect obvious local-model repetition loops in recent output text."""
    tail = str(text or "")[-5000:].casefold()
    tokens = re.findall(r"[^\W_]+", tail, flags=re.UNICODE)

    if len(tokens) < 70:
        return False

    counts = Counter(tokens)
    most_common_count = counts.most_common(1)[0][1]

    if most_common_count >= 20 and most_common_count / len(tokens) >= 0.20:
        return True

    if len(tokens) >= 120 and len(counts) / len(tokens) < 0.25:
        return True

    trigrams = Counter(
        tuple(tokens[index : index + 3]) for index in range(len(tokens) - 2)
    )

    if trigrams and trigrams.most_common(1)[0][1] >= 8:
        return True

    return False

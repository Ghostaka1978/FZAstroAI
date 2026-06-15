"""Small helpers for routing persona/profile questions to local app state."""

from __future__ import annotations

import re

ASSISTANT_PERSONA_PROMPT = "What is your persona ?"

_REJECT_TERMS = (
    "monitor",
    "displaycal",
    "calibrite",
    "icc",
    "color management",
    "colorsync",
    "screen calibration",
    "display calibration",
)


def _normalise_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def is_assistant_persona_status_query(text: str) -> bool:
    """Return True when the user is asking for FZAstro's active persona.

    The composer used to insert "my current persona", which the LLM could
    interpret as the user's profile and route to web search.  This detector
    keeps assistant/app persona requests local while avoiding obvious monitor
    calibration/profile questions.
    """
    value = _normalise_text(text)

    if not value:
        return False

    if any(term in value for term in _REJECT_TERMS):
        return False

    if "active calibration profile" in value and (
        "persona" in value or "assistant" in value or "fzastro" in value
    ):
        return True

    if re.search(
        r"\bwhat(?:\s+is|'s)?\s+(?:your|fzastro(?:\s+ai)?(?:'s)?|the\s+assistant(?:'s)?)\s+current\s+(?:persona|profile)\b",
        value,
    ):
        return True

    if "current persona" in value and (
        "assistant" in value or "fzastro" in value or "your" in value
    ):
        return True

    # Backward-compatible handling for the old composer text.  Keep this narrow:
    # it must mention persona plus calibration/profile wording, not only "my
    # profile", which could refer to the user.
    if "my current persona" in value and (
        "calibration profile" in value or "active calibration" in value
    ):
        return True

    return False

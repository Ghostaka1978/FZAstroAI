"""Backward-compatible voice command-router shim.

The offline voice implementation lives in :mod:`fzastro_ai.voice.command_router`.
This module is kept so older imports such as ``fzastro_ai.command_router`` do not
break startup after applying partial patches.
"""

from __future__ import annotations

from .voice.command_router import (
    VoiceCommandResult,
    resolve_voice_command,
    voice_command_grammar,
    voice_help_examples,
)

__all__ = [
    "VoiceCommandResult",
    "resolve_voice_command",
    "voice_command_grammar",
    "voice_help_examples",
]

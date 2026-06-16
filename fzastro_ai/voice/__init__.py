"""Offline voice-command helpers for FZAstro AI."""

from .command_router import (
    VoiceCommandResult,
    resolve_voice_command,
    voice_help_examples,
)

__all__ = ["VoiceCommandResult", "resolve_voice_command", "voice_help_examples"]

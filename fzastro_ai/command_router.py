"""Compatibility wrapper for :mod:
zastro_ai.voice.command_router.

The implementation was moved during package cleanup. This module keeps older
imports working without importing from outside the package root.
"""

from .voice.command_router import *  # noqa: F401,F403

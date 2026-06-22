"""Compatibility wrapper for Developer Agent safety helpers.

Older modules imported Developer Agent safety functions from
``fzastro_ai.safety``.  The implementation now lives in
``fzastro_ai.dev_agent.safety``; this module preserves the legacy import path
without duplicating safety logic.
"""

from .dev_agent.safety import *  # noqa: F401,F403

"""Compatibility wrapper for the Developer Agent project scanner.

Older FZAstro modules imported project scanning helpers from
``fzastro_ai.project_scanner``.  The implementation now lives in
``fzastro_ai.dev_agent.project_scanner``; this module keeps legacy imports
working without duplicating scanner logic.
"""

from .dev_agent.project_scanner import *  # noqa: F401,F403

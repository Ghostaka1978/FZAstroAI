"""Compatibility wrapper for :mod:`fzastro_ai.workers.web_search_worker`.

The implementation was moved during package cleanup. This module keeps older
imports working without importing from outside the package root.
"""

from .workers.web_search_worker import *  # noqa: F401,F403

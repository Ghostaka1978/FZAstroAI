"""Compatibility wrapper for :mod:
zastro_ai.workers.python_execution_worker.

The implementation was moved during package cleanup. This module keeps older
imports working without importing from outside the package root.
"""

from .workers.python_execution_worker import *  # noqa: F401,F403

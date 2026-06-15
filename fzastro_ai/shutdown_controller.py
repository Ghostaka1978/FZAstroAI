"""Backward-compatible import shim for the shutdown controller mixin.

The implementation lives in :mod:`fzastro_ai.controllers.shutdown_controller`.
This module keeps older local checkouts, stale bytecode, and external imports from
breaking after the controller extraction refactor.
"""

from .controllers.shutdown_controller import ShutdownControllerMixin

__all__ = ["ShutdownControllerMixin"]

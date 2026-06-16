"""AI Developer Workbench backend primitives.

This package is intentionally UI-agnostic.  It provides safe project scanning,
context selection, visible planning, patch bookkeeping, and local check runners
that can be wired into the desktop UI without giving the model direct file-write
control.
"""

from .context_builder import ContextFile, DevContext, build_dev_context
from .dev_session import DevAgentSession, DevSessionResult
from .project_scanner import ProjectFile, ProjectScan, scan_project
from .task_classifier import DevTask, classify_dev_task

__all__ = [
    "ContextFile",
    "DevAgentSession",
    "DevContext",
    "DevSessionResult",
    "DevTask",
    "ProjectFile",
    "ProjectScan",
    "build_dev_context",
    "classify_dev_task",
    "scan_project",
]

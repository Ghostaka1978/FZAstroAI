"""Subprocess helpers for Developer Workbench / OpenClaude flows.

Developer actions run inside the FZAstro UI.  On Windows, plain
``subprocess.run``/``Popen`` can briefly show a console window for helper tools
such as Git, pytest, PowerShell, or OpenClaude fallback scripts.  Keep those
helper processes quiet unless a real embedded terminal is explicitly hosting
interactive output.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Return kwargs that prevent helper console windows on Windows.

    The kwargs are safe to merge into ``subprocess.run`` or ``subprocess.Popen``.
    Non-Windows platforms intentionally receive no extra arguments.
    """

    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    kwargs["startupinfo"] = startupinfo
    return kwargs

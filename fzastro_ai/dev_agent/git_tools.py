from __future__ import annotations

import subprocess
from pathlib import Path

from .subprocess_utils import hidden_subprocess_kwargs


def git_available(root: Path | str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=Path(root).resolve(),
            text=True,
            capture_output=True,
            timeout=10,
            **hidden_subprocess_kwargs(),
        )
    except Exception:
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def git_status_short(root: Path | str) -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=Path(root).resolve(),
        text=True,
        capture_output=True,
        timeout=30,
        **hidden_subprocess_kwargs(),
    )
    return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()


def suggest_commit_command(summary: str) -> str:
    clean = " ".join(str(summary or "Improve developer workbench").split())
    clean = clean.replace('"', "'")[:72]
    return f'git add . && git commit -m "{clean}"'

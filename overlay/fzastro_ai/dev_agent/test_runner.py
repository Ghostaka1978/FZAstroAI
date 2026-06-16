from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .error_analyzer import FailureSummary, analyze_failure_output


@dataclass(frozen=True)
class CheckResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part)

    def failure_summary(self) -> FailureSummary:
        return analyze_failure_output(self.combined_output)


def run_command(
    root: Path | str,
    command: list[str] | tuple[str, ...],
    *,
    timeout_seconds: int = 180,
) -> CheckResult:
    import time

    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=Path(root).resolve(),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - started
        return CheckResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_seconds=round(elapsed, 2),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CheckResult(
            command=tuple(command),
            returncode=124,
            stdout=stdout,
            stderr=(stderr + f"\nCommand timed out after {timeout_seconds}s").strip(),
            elapsed_seconds=float(timeout_seconds),
        )


def run_compileall(root: Path | str, *, timeout_seconds: int = 180) -> CheckResult:
    return run_command(
        root,
        [sys.executable, "-m", "compileall", "-q", "fzastro_ai", "tests"],
        timeout_seconds=timeout_seconds,
    )


def run_pytest(
    root: Path | str,
    targets: list[str] | tuple[str, ...] | None = None,
    *,
    timeout_seconds: int = 300,
) -> CheckResult:
    command = [sys.executable, "-m", "pytest", "-q"]
    if targets:
        command.extend(targets)
    return run_command(root, command, timeout_seconds=timeout_seconds)

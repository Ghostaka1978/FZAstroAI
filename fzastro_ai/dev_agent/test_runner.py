from __future__ import annotations

__test__ = False

import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .error_analyzer import FailureSummary, analyze_failure_output
from .safety import DevAgentSafetyError, command_requires_approval, format_command


class ValidationPreset(str, Enum):
    COMPILE_ONLY = "Compile Only"
    FAST_UNIT_TESTS = "Fast Unit Tests"
    FEATURE_TESTS = "Feature Tests"
    FULL_PYTEST = "Full Pytest"
    BUILD_EXE = "Build EXE"
    RELEASE_VALIDATION = "Release Validation"


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

    @property
    def command_text(self) -> str:
        return format_command(self.command)

    def failure_summary(self) -> FailureSummary:
        return analyze_failure_output(self.combined_output)


@dataclass(frozen=True)
class ValidationProfile:
    name: str
    kind: str
    reason: str


def detect_validation_profile(root: Path | str) -> ValidationProfile:
    """Infer safe validation defaults for the selected project root.

    FZAstro's own repository has a known layout and targeted regression suite.
    Any other Python folder should use generic project-root validation, so the
    Developer Agent behaves like a coding agent instead of assuming FZAstro
    files exist in every selected project.
    """

    root_path = Path(root).resolve()
    if (root_path / "main.py").exists() and (root_path / "fzastro_ai").is_dir():
        return ValidationProfile(
            name="FZAstro AI",
            kind="fzastro",
            reason="main.py and fzastro_ai/ detected",
        )

    if any(root_path.glob("*.py")) or (root_path / "tests").is_dir():
        return ValidationProfile(
            name="Generic Python",
            kind="generic_python",
            reason="Python files or tests detected",
        )

    return ValidationProfile(
        name="Generic Project",
        kind="generic",
        reason="no FZAstro layout detected",
    )


def _has_pytest_tests(root: Path | str) -> bool:
    root_path = Path(root).resolve()
    tests_dir = root_path / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        return True
    return any(root_path.glob("test_*.py"))


def _skipped_result(command: tuple[str, ...], message: str) -> CheckResult:
    return CheckResult(
        command=command, returncode=0, stdout=message, stderr="", elapsed_seconds=0.0
    )


def run_command(
    root: Path | str,
    command: list[str] | tuple[str, ...],
    *,
    timeout_seconds: int = 180,
) -> CheckResult:
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


def run_command_safe(
    root: Path | str,
    command: list[str] | tuple[str, ...],
    *,
    approved: bool = False,
    timeout_seconds: int = 180,
) -> CheckResult:
    """Run a command only if it is allow-listed or explicitly approved."""

    normalized = tuple(str(part) for part in command)
    if command_requires_approval(normalized) and not approved:
        raise DevAgentSafetyError(
            "Command requires explicit approval: " + format_command(normalized)
        )
    return run_command(root, normalized, timeout_seconds=timeout_seconds)


def run_compileall(root: Path | str, *, timeout_seconds: int = 180) -> CheckResult:
    profile = detect_validation_profile(root)
    targets = ["main.py", "fzastro_ai", "tests"] if profile.kind == "fzastro" else ["."]
    return run_command(
        root,
        [sys.executable, "-m", "compileall", "-q", *targets],
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


def infer_pytest_targets(changed_paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Infer targeted pytest files from changed project modules."""

    targets: list[str] = []
    for raw in changed_paths:
        path = str(raw).replace("\\", "/")
        if path.startswith("tests/") and path.endswith(".py"):
            if path not in targets:
                targets.append(path)
            continue
        if not path.endswith(".py") or path.startswith(("external/", "bundled_apps/")):
            continue
        stem = Path(path).stem
        candidates = [f"tests/test_{stem}.py"]
        if path.startswith("fzastro_ai/"):
            candidates.extend(
                [
                    f"tests/test_{stem.replace('_dialog', '')}.py",
                    f"tests/test_{stem.replace('_worker', '')}.py",
                ]
            )
        for candidate in candidates:
            if candidate not in targets:
                targets.append(candidate)
    return tuple(targets)


def existing_targets(root: Path | str, targets: tuple[str, ...]) -> tuple[str, ...]:
    root_path = Path(root).resolve()
    return tuple(target for target in targets if (root_path / target).exists())


def command_for_preset(
    root: Path | str,
    preset: ValidationPreset | str,
    *,
    changed_paths: list[str] | tuple[str, ...] = (),
) -> tuple[str, ...]:
    selected = ValidationPreset(preset)
    profile = detect_validation_profile(root)
    if selected == ValidationPreset.COMPILE_ONLY:
        targets = (
            ("main.py", "fzastro_ai", "tests") if profile.kind == "fzastro" else (".",)
        )
        return (sys.executable, "-m", "compileall", "-q", *targets)
    if selected == ValidationPreset.FAST_UNIT_TESTS:
        if profile.kind == "fzastro":
            return (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_dev_agent_project_scanner.py",
                "tests/test_dev_agent_context_builder.py",
                "tests/test_dev_agent_patch_applier.py",
                "tests/test_dev_agent_error_analyzer.py",
                "tests/test_dev_agent_file_tools.py",
                "tests/test_dev_agent_test_runner.py",
            )
        if _has_pytest_tests(root):
            return (sys.executable, "-m", "pytest", "-q")
        return (sys.executable, "-m", "pytest", "-q")
    if selected == ValidationPreset.FEATURE_TESTS:
        targets = existing_targets(root, infer_pytest_targets(changed_paths))
        if targets:
            return (sys.executable, "-m", "pytest", "-q", *targets)
        if _has_pytest_tests(root):
            return (sys.executable, "-m", "pytest", "-q")
        return (sys.executable, "-m", "pytest", "-q")
    if selected == ValidationPreset.FULL_PYTEST:
        return (sys.executable, "-m", "pytest", "-q")
    if selected == ValidationPreset.BUILD_EXE:
        return (
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/build_exe.ps1",
        )
    if selected == ValidationPreset.RELEASE_VALIDATION:
        return (
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/validate_release.ps1",
        )
    raise ValueError(f"Unsupported validation preset: {preset!r}")


def run_validation_preset(
    root: Path | str,
    preset: ValidationPreset | str,
    *,
    changed_paths: list[str] | tuple[str, ...] = (),
    approved: bool = False,
    timeout_seconds: int | None = None,
) -> CheckResult:
    selected = ValidationPreset(preset)
    command = command_for_preset(root, selected, changed_paths=changed_paths)
    profile = detect_validation_profile(root)
    if selected in {
        ValidationPreset.FAST_UNIT_TESTS,
        ValidationPreset.FEATURE_TESTS,
        ValidationPreset.FULL_PYTEST,
    }:
        if profile.kind != "fzastro" and not _has_pytest_tests(root):
            return _skipped_result(
                command,
                (
                    f"Skipped pytest: no tests discovered in {Path(root).resolve()}.\n"
                    f"Detected validation profile: {profile.name} ({profile.reason})."
                ),
            )
    default_timeout = {
        ValidationPreset.COMPILE_ONLY: 180,
        ValidationPreset.FAST_UNIT_TESTS: 240,
        ValidationPreset.FEATURE_TESTS: 300,
        ValidationPreset.FULL_PYTEST: 600,
        ValidationPreset.BUILD_EXE: 1800,
        ValidationPreset.RELEASE_VALIDATION: 1800,
    }[selected]
    return run_command_safe(
        root,
        command,
        approved=approved,
        timeout_seconds=timeout_seconds or default_timeout,
    )

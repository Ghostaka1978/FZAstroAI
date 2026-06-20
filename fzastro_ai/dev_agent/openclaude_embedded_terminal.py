"""Embedded OpenClaude terminal helpers.

The Developer Workbench can use OpenClaude in two ways:

* embedded terminal mode, implemented here with Windows ConPTY through pywinpty

The embedded path is optional and deliberately capability-detected at runtime so
source builds, tests, and non-Windows environments keep working without pywinpty.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from .openclaude_bridge import (
    OpenClaudeBridgeError,
    OpenClaudeLaunchConfig,
    build_openclaude_environment,
    get_openclaude_tool_status,
    validate_openclaude_project_root,
    write_openclaude_launcher,
)


@dataclass(frozen=True)
class EmbeddedTerminalSupport:
    """Runtime support state for the embedded OpenClaude terminal."""

    supported: bool
    backend: str
    reason: str
    install_hint: str = ""


@dataclass(frozen=True)
class OpenClaudeEmbeddedCommand:
    """Command context for starting OpenClaude inside an embedded PTY."""

    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    support: EmbeddedTerminalSupport


def pywinpty_install_hint() -> str:
    """Return a precise install hint for the current runtime.

    Source runs can install into the active Python environment. Frozen EXE runs
    cannot add Python packages to the embedded PyInstaller runtime, so the fix is
    to install pywinpty in the build venv and rebuild the EXE.
    """

    if getattr(sys, "frozen", False):
        return (
            "Install pywinpty in the build venv, then rebuild the EXE: "
            "scripts\\setup_openclaude_companion.ps1 -InstallEmbeddedTerminalBackend; "
            "scripts\\build_exe.ps1"
        )
    return (
        "Run scripts\\setup_openclaude_companion.ps1 -InstallEmbeddedTerminalBackend "
        "with the same Python used by FZAstro, or run DEPLOY.bat to prepare and package it."
    )


def get_embedded_terminal_support() -> EmbeddedTerminalSupport:
    """Return whether true in-app terminal embedding is available.

    OpenClaude's interactive UI expects terminal semantics. On Windows, FZAstro
    provides that through ConPTY using the optional ``pywinpty`` package. Other
    platforms can still use the external-terminal launcher.
    """

    if os.name != "nt":
        return EmbeddedTerminalSupport(
            supported=False,
            backend="external-terminal",
            reason="Embedded OpenClaude terminal requires Windows ConPTY.",
            install_hint="Embedded terminal mode is Windows-only; prepare pywinpty in setup/build/deploy on Windows.",
        )

    try:
        importlib.import_module("winpty")
    except Exception as exc:
        return EmbeddedTerminalSupport(
            supported=False,
            backend="missing-pywinpty",
            reason=f"pywinpty is not available: {exc}",
            install_hint=pywinpty_install_hint(),
        )

    return EmbeddedTerminalSupport(
        supported=True,
        backend="pywinpty-conpty",
        reason="Windows ConPTY backend is available.",
    )


def build_openclaude_embedded_command(
    config: OpenClaudeLaunchConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> OpenClaudeEmbeddedCommand:
    """Build the command and environment for an embedded OpenClaude terminal."""

    root = validate_openclaude_project_root(config.project_root)
    support = get_embedded_terminal_support()
    status = get_openclaude_tool_status(env=env)
    if not status.openclaude_path:
        raise OpenClaudeBridgeError(
            "OpenClaude is not installed. Install with: npm install -g @gitlawb/openclaude@latest"
        )

    process_env = dict(os.environ if env is None else env)
    process_env.update(build_openclaude_environment(config))

    # Node/npm installers sometimes update PATH after the current process was
    # created. Keep the same deploy-aware search additions as the external
    # launcher so the embedded terminal can find npm global shims.
    appdata = process_env.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    path_entries = [str(Path(r"C:\Program Files\nodejs")), str(Path(appdata) / "npm")]
    existing_path = process_env.get("PATH", "")
    for entry in reversed(path_entries):
        if entry and entry not in existing_path:
            existing_path = entry + os.pathsep + existing_path
    process_env["PATH"] = existing_path

    # Run through the generated PowerShell launcher rather than spawning the
    # npm .cmd shim directly.  For the embedded terminal we intentionally do
    # NOT use -NoExit: OpenClaude owns the terminal.  If the user exits
    # OpenClaude or presses Ctrl+C until it closes, the PTY should close cleanly
    # instead of dropping into an orphaned PowerShell prompt that repeats ^C.
    launcher_path = write_openclaude_launcher(config)
    if os.name == "nt":
        command = (
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher_path),
        )
    else:
        command = (status.openclaude_path,)

    return OpenClaudeEmbeddedCommand(
        command=command,
        cwd=root,
        env=process_env,
        support=support,
    )


def command_to_cmdline(command: tuple[str, ...]) -> str:
    """Return a Windows-safe command line for pywinpty.spawn."""

    return subprocess.list2cmdline(tuple(str(part) for part in command))


def format_embedded_terminal_status(config: OpenClaudeLaunchConfig) -> str:
    """Markdown status block for the embedded terminal path."""

    support = get_embedded_terminal_support()
    tool_status = get_openclaude_tool_status()
    missing = ", ".join(tool_status.missing) if tool_status.missing else "none"
    readiness = "ready" if support.supported and tool_status.is_ready else "needs setup"
    return "\n".join(
        [
            "# Embedded OpenClaude Terminal",
            "",
            f"**State:** {readiness}",
            f"**Backend:** `{support.backend}`",
            f"**Reason:** {support.reason}",
            f"**Missing tools:** {missing}",
            f"**Project:** `{Path(config.project_root).expanduser()}`",
            f"**Model:** `{config.model}`",
            f"**Endpoint:** `{config.base_url}`",
            "",
            "## Behavior",
            "- The embedded terminal uses Windows ConPTY through pywinpty when available.",
            "- pywinpty is prepared by requirements/setup/build/deploy, not installed from the app UI.",
            "- If ConPTY is unavailable, fix setup/build/deploy; the app does not expose a separate external terminal action.",
            "- Normal FZAstro chat still uses Ollama/OpenAI-compatible APIs directly.",
            "",
            f"**Setup hint:** {support.install_hint or 'No extra setup needed.'}",
        ]
    )

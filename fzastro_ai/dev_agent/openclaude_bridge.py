"""OpenClaude companion launcher helpers.

This module intentionally keeps OpenClaude outside the normal FZAstro chat
runtime. FZAstro continues to talk directly to Ollama/OpenAI-compatible
providers, while the Developer Workbench can launch OpenClaude as a separate
coding-agent terminal with the same selected model and endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Sequence

from ..config import API_KEY, APP_DIR, BASE_URL, DEFAULT_MODEL_NAME

OPENCLAUDE_NPM_PACKAGE = "@gitlawb/openclaude@latest"
OPENCLAUDE_STATE_DIR = APP_DIR / "openclaude"
OPENCLAUDE_LAUNCHER_NAME = "run_openclaude_companion.ps1"
OPENCLAUDE_PROMPT_NAME = "latest_openclaude_prompt.md"
OPENCLAUDE_CONTEXT_NAME = "latest_project_context.md"
OPENCLAUDE_OUTPUT_LOG_NAME = "latest_openclaude_output.log"
OPENCLAUDE_DIFF_NAME = "latest_diff.patch"
OPENCLAUDE_REPORT_NAME = "latest_report.md"


@dataclass(frozen=True)
class OpenClaudeToolStatus:
    """Resolved local OpenClaude toolchain state."""

    node_path: str
    npm_path: str
    openclaude_path: str
    missing: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class OpenClaudeLaunchConfig:
    """Runtime settings passed from FZAstro to the OpenClaude terminal."""

    project_root: Path
    model: str = DEFAULT_MODEL_NAME
    base_url: str = BASE_URL
    api_key: str = API_KEY
    install_if_missing: bool = False


@dataclass(frozen=True)
class OpenClaudeLaunchResult:
    """Result returned after preparing or launching the companion terminal."""

    ok: bool
    message: str
    script_path: Path
    command: tuple[str, ...]
    status: OpenClaudeToolStatus
    safe_prompt: str
    prompt_path: Path | None = None


class OpenClaudeBridgeError(RuntimeError):
    """Raised when the OpenClaude companion cannot be prepared safely."""


# ---------------------------------------------------------------------------
# Command and project-root resolution
# ---------------------------------------------------------------------------


def _env_value(env: Mapping[str, str] | None, key: str, default: str = "") -> str:
    source = env if env is not None else os.environ
    return str(source.get(key, default) or "")


def _path_entries(env: Mapping[str, str] | None = None) -> list[str]:
    raw = _env_value(env, "PATH")
    return [part for part in raw.split(os.pathsep) if part]


def _common_windows_candidates(
    command: str, env: Mapping[str, str] | None = None
) -> list[Path]:
    # Tests and callers may pass a deliberately restricted env mapping. In that
    # case, do not silently escape to the real machine's Program Files/AppData;
    # only use well-known Windows fallback locations when using the real process
    # environment or when the caller supplied those variables explicitly.
    if env is None:
        appdata = _env_value(env, "APPDATA", str(Path.home() / "AppData" / "Roaming"))
        program_files = _env_value(env, "ProgramFiles", r"C:\Program Files")
        program_files_x86 = _env_value(
            env, "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
    else:
        appdata = str(env.get("APPDATA", "") or "")
        program_files = str(env.get("ProgramFiles", "") or "")
        program_files_x86 = str(env.get("ProgramFiles(x86)", "") or "")

    lower = command.lower()
    candidates: list[Path] = []
    if lower == "node":
        candidates.extend(
            [
                Path(program_files) / "nodejs" / "node.exe",
                Path(program_files_x86) / "nodejs" / "node.exe",
            ]
        )
    elif lower == "npm":
        candidates.extend(
            [
                Path(program_files) / "nodejs" / "npm.cmd",
                Path(program_files_x86) / "nodejs" / "npm.cmd",
                Path(appdata) / "npm" / "npm.cmd",
            ]
        )
    elif lower == "openclaude":
        candidates.extend(
            [
                Path(appdata) / "npm" / "openclaude.cmd",
                Path(program_files) / "nodejs" / "openclaude.cmd",
            ]
        )
    return candidates


def find_command(command: str, env: Mapping[str, str] | None = None) -> str:
    """Find a command through PATH plus common Windows Node/npm locations."""

    names = [command]
    if not command.lower().endswith((".cmd", ".exe", ".bat")):
        names.extend([f"{command}.cmd", f"{command}.exe", f"{command}.bat"])

    path_entries = _path_entries(env)
    path = os.pathsep.join(path_entries)
    for name in names:
        for entry in path_entries:
            candidate = Path(entry) / name
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        found = shutil.which(name, path=path or None)
        if found:
            return str(Path(found))

    for candidate in _common_windows_candidates(command, env):
        if candidate.exists():
            return str(candidate)

    return ""


def get_openclaude_tool_status(
    env: Mapping[str, str] | None = None,
) -> OpenClaudeToolStatus:
    node_path = find_command("node", env=env)
    npm_path = find_command("npm", env=env)
    openclaude_path = find_command("openclaude", env=env)
    missing: list[str] = []
    if not node_path:
        missing.append("node")
    if not npm_path:
        missing.append("npm")
    if not openclaude_path:
        missing.append("openclaude")
    return OpenClaudeToolStatus(
        node_path=node_path,
        npm_path=npm_path,
        openclaude_path=openclaude_path,
        missing=tuple(missing),
    )


def looks_like_fzastro_source_root(path: Path | str) -> bool:
    root = Path(path).expanduser()
    return (
        root.exists()
        and root.is_dir()
        and (root / "main.py").is_file()
        and (root / "fzastro_ai").is_dir()
        and (root / "tests").is_dir()
    )


def validate_openclaude_project_root(path: Path | str) -> Path:
    """Validate that OpenClaude has a real workspace folder.

    OpenClaude is now the visible workspace agent.  FZAstro no longer blocks
    non-FZAstro folders here: the selected folder is the user's active coding
    workspace, and OpenClaude can create/edit files, run Python or shell
    commands, inspect git, and report results inside that workspace.  FZAstro
    still detects FZAstro source markers separately so prompts can be more
    specific when the workspace is the app source tree.
    """

    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise OpenClaudeBridgeError(f"Workspace folder does not exist: {root}")
    return root


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------


def powershell_single_quote(value: object) -> str:
    """Return a PowerShell single-quoted literal."""

    text = str(value if value is not None else "")
    return "'" + text.replace("'", "''") + "'"


def build_openclaude_environment(config: OpenClaudeLaunchConfig) -> dict[str, str]:
    model = str(config.model or DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
    base_url = str(config.base_url or BASE_URL).strip() or BASE_URL
    api_key = str(config.api_key or API_KEY).strip() or API_KEY
    return {
        "CLAUDE_CODE_USE_OPENAI": "1",
        "OPENAI_BASE_URL": base_url,
        "OPENAI_MODEL": model,
        "OPENAI_API_KEY": api_key,
        "FZASTRO_PROJECT_ROOT": str(Path(config.project_root).expanduser().resolve()),
    }


def _mode_intent(mode: str) -> str:
    clean_mode = str(mode or "plan").strip().lower()
    if clean_mode in {"patch", "patch-run-tests", "patch_and_test", "agent_patch"}:
        return (
            "Mode guidance: patch work is allowed. You may create or edit files, "
            "run Python, tests, scripts, and git commands inside the selected workspace when useful. "
            "Report the commands you ran and the results you observed."
        )
    if clean_mode in {"review", "review-only", "agent_review"}:
        return (
            "Mode guidance: review only. Inspect and explain the workspace, but do not modify files "
            "unless the user explicitly changes mode or asks you to proceed."
        )
    return (
        "Mode guidance: plan first. Inspect what you need, explain the likely next action, "
        "and proceed naturally if the user asks for implementation."
    )


def _safety_intent(safety: str) -> str:
    clean_safety = str(safety or "ask-before-editing").strip().lower()
    if clean_safety in {"read-only", "readonly", "no-edits"}:
        return "Safety guidance: do not edit files."
    if clean_safety in {"ask-before-editing", "ask_before_editing", "confirm-edits"}:
        return "Safety guidance: before meaningful file edits, briefly state what you intend to change and ask for confirmation."
    return "Safety guidance: operate carefully in the selected workspace and summarize changes clearly."


def build_openclaude_project_context(
    config: OpenClaudeLaunchConfig,
    *,
    mode: str = "plan",
    safety: str = "ask-before-editing",
) -> str:
    """Build the FZAstro-aware context pack for the embedded OpenClaude terminal."""

    env_map = build_openclaude_environment(config)
    root = Path(config.project_root).expanduser()
    return "\n".join(
        [
            "# FZAstro OpenClaude Context",
            "",
            "This file is generated by FZAstro AI before starting OpenClaude.",
            "It gives OpenClaude the selected workspace, model, endpoint, and local project defaults.",
            "",
            "## Workspace",
            f"- Project root: `{root}`",
            f"- Workspace type: `{'FZAstro source checkout' if looks_like_fzastro_source_root(root) else 'generic workspace'}`",
            "- Normal app runtime remains direct Ollama/OpenAI-compatible API access.",
            "- OpenClaude is the interactive workspace agent for coding, file creation, shell/Python commands, tests, and git work.",
            "",
            "## Runtime",
            "- Provider style: Ollama/OpenAI-compatible",
            f"- Model: `{env_map['OPENAI_MODEL']}`",
            f"- Endpoint: `{env_map['OPENAI_BASE_URL']}`",
            "",
            "## Project Rules",
            "- OpenClaude owns the interactive review/edit/test flow inside the terminal.",
            "- FZAstro does not paste hidden prompts or simulate the old DEV pipeline.",
            "",
            "## Workspace Capabilities",
            "- You may inspect files, create files, edit files, run Python and shell commands, run tests/scripts, and inspect or update git according to the user task and AGENTS.md rules.",
            "- Report concrete command results instead of claiming validation happened.",
            "- For astronomy hardware/N.I.N.A. actions, keep the response informational unless the app explicitly exposes a safe tool for that action.",
        ]
    )


def write_openclaude_project_context(
    config: OpenClaudeLaunchConfig,
    *,
    mode: str = "plan",
    safety: str = "ask-before-editing",
) -> Path:
    OPENCLAUDE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    context_path = OPENCLAUDE_STATE_DIR / OPENCLAUDE_CONTEXT_NAME
    context_path.write_text(
        build_openclaude_project_context(config, mode=mode, safety=safety),
        encoding="utf-8",
    )
    return context_path


def ensure_openclaude_agents_file(
    config: OpenClaudeLaunchConfig,
    *,
    mode: str = "plan",
    safety: str = "ask-before-editing",
) -> Path:
    """Create a lightweight AGENTS.md rule file for OpenClaude workspaces.

    The file is created only when missing, so user-authored project rules are
    never overwritten.  It gives OpenClaude/Codex-style agents stable local
    guidance without FZAstro pasting a long prompt into the terminal UI.
    """

    root = validate_openclaude_project_root(config.project_root)
    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        return agents_path

    content = "\n".join(
        [
            "# FZAstro / OpenClaude Workspace Rules",
            "",
            "- Inspect relevant files before editing.",
            "- Prefer small, reviewable patches over broad rewrites.",
            "- Do not modify unrelated files.",
            "- Run appropriate validation after code changes when practical.",
            "- For Python changes in FZAstro AI, prefer:",
            "  - `python -m compileall -q main.py fzastro_ai tests`",
            "  - `pytest -q` or the smallest relevant pytest target.",
            "- Report concrete command output and remaining risks.",
            "- Ask before destructive commands, deployment actions, or large refactors.",
            "- Do not start astronomy hardware, N.I.N.A. sequences, guiding, capture, or power actions from this workspace.",
            "- Use normal OpenClaude judgment for review, editing, tests, and git work unless the user gives stricter instructions.",
            "",
        ]
    )
    agents_path.write_text(content, encoding="utf-8")
    return agents_path


def openclaude_artifact_paths() -> dict[str, Path]:
    OPENCLAUDE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "state_dir": OPENCLAUDE_STATE_DIR,
        "prompt": OPENCLAUDE_STATE_DIR / OPENCLAUDE_PROMPT_NAME,
        "context": OPENCLAUDE_STATE_DIR / OPENCLAUDE_CONTEXT_NAME,
        "output_log": OPENCLAUDE_STATE_DIR / OPENCLAUDE_OUTPUT_LOG_NAME,
        "diff": OPENCLAUDE_STATE_DIR / OPENCLAUDE_DIFF_NAME,
        "report": OPENCLAUDE_STATE_DIR / OPENCLAUDE_REPORT_NAME,
    }


def build_openclaude_task_prompt(
    task: str = "",
    *,
    mode: str = "plan",
    context_path: Path | str | None = None,
    output_log_path: Path | str | None = None,
    diff_path: Path | str | None = None,
    report_path: Path | str | None = None,
) -> str:
    """Build the OpenClaude prompt handed from FZAstro to OpenClaude.

    The prompt is retained for compatibility/export tooling. The visible app flow
    is terminal-first: OpenClaude receives workspace defaults through environment
    and AGENTS.md, then behaves like the normal CLI.
    """

    clean_task = str(task or "").strip()
    if not clean_task:
        clean_task = (
            "Inspect the repository and identify the main app entry point, the "
            "Developer Workbench / dev agent files, the OpenClaude companion files, "
            "the Web Companion files, the related tests, and the current model/provider configuration."
        )

    artifacts = openclaude_artifact_paths()
    context_text = str(context_path or artifacts["context"])
    output_log_text = str(output_log_path or artifacts["output_log"])
    diff_text = str(diff_path or artifacts["diff"])
    report_text = str(report_path or artifacts["report"])
    intent = _mode_intent(mode)

    return "\n".join(
        [
            "You are OpenClaude running inside FZAstro's selected workspace.",
            "",
            "Read this FZAstro-generated context first:",
            context_text,
            "",
            "Use the selected workspace as the source of truth. Do not guess file contents.",
            "Interact normally as a coding agent: inspect files, create files, edit files, run Python/shell/tests/scripts, and inspect or update git according to the user task and AGENTS.md rules.",
            "Report the concrete commands you ran and the observed results. Do not claim tests passed unless you actually ran them.",
            "Avoid real astronomy hardware/N.I.N.A. actions unless FZAstro exposes an explicit safe tool for that action.",
            "",
            "Mode and safety guidance:",
            f"- {intent}",
            "",
            "Task:",
            clean_task,
            "",
            "Useful FZAstro artifact targets if you choose to write reports or exports:",
            f"- Output log target: {output_log_text}",
            f"- Diff export target: {diff_text}",
            f"- Report target: {report_text}",
        ]
    )


def safe_first_prompt() -> str:
    return build_openclaude_task_prompt("", mode="plan")


def write_openclaude_task_prompt(prompt: str) -> Path:
    OPENCLAUDE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    prompt_path = OPENCLAUDE_STATE_DIR / OPENCLAUDE_PROMPT_NAME
    prompt_path.write_text(str(prompt or safe_first_prompt()), encoding="utf-8")
    return prompt_path


def build_openclaude_launcher_script(config: OpenClaudeLaunchConfig) -> str:
    env = build_openclaude_environment(config)
    install_flag = "$true" if config.install_if_missing else "$false"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$Host.UI.RawUI.WindowTitle = 'FZAstro OpenClaude Companion'",
        "",
        "$nodeDir = 'C:\\Program Files\\nodejs'",
        "$npmGlobal = Join-Path $env:APPDATA 'npm'",
        "foreach ($entry in @($nodeDir, $npmGlobal)) {",
        '    if ($entry -and (Test-Path -LiteralPath $entry) -and ($env:Path -notlike "*$entry*")) {',
        "        $env:Path = $entry + ';' + $env:Path",
        "    }",
        "}",
        "",
    ]
    for key, value in env.items():
        lines.append(f"$env:{key} = {powershell_single_quote(value)}")
    lines.extend(
        [
            "",
            f"$installIfMissing = {install_flag}",
            "$projectRoot = $env:FZASTRO_PROJECT_ROOT",
            "Set-Location -LiteralPath $projectRoot",
            "",
            "$nodeCommand = Get-Command node -ErrorAction SilentlyContinue",
            "if (-not $nodeCommand) {",
            "    Write-Host 'Node.js was not found on PATH.' -ForegroundColor Yellow",
            "    Write-Host 'Install it with: winget install OpenJS.NodeJS.LTS'",
            "    Read-Host 'Press Enter to close' | Out-Null",
            "    exit 2",
            "}",
            "",
            "$npmCommand = Get-Command npm -ErrorAction SilentlyContinue",
            "if (-not $npmCommand) {",
            "    Write-Host 'npm was not found on PATH.' -ForegroundColor Yellow",
            "    Write-Host 'Close/reopen PowerShell after installing Node.js, or add C:\\Program Files\\nodejs to PATH.'",
            "    Read-Host 'Press Enter to close' | Out-Null",
            "    exit 3",
            "}",
            "",
            "$openClaudeCommand = Get-Command openclaude -ErrorAction SilentlyContinue",
            "if (-not $openClaudeCommand -and $installIfMissing) {",
            f"    Write-Host 'Installing OpenClaude npm package: {OPENCLAUDE_NPM_PACKAGE}'",
            f"    & $npmCommand.Source install -g {OPENCLAUDE_NPM_PACKAGE}",
            "    $openClaudeCommand = Get-Command openclaude -ErrorAction SilentlyContinue",
            "}",
            "",
            "if (-not $openClaudeCommand) {",
            "    Write-Host 'OpenClaude is not installed.' -ForegroundColor Yellow",
            f"    Write-Host 'Install with: npm install -g {OPENCLAUDE_NPM_PACKAGE}'",
            "    Read-Host 'Press Enter to close' | Out-Null",
            "    exit 4",
            "}",
            "",
            "& $openClaudeCommand.Source",
        ]
    )
    return "\n".join(lines) + "\n"


def write_openclaude_launcher(config: OpenClaudeLaunchConfig) -> Path:
    root = validate_openclaude_project_root(config.project_root)
    normalized = OpenClaudeLaunchConfig(
        project_root=root,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        install_if_missing=config.install_if_missing,
    )
    OPENCLAUDE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    script_path = OPENCLAUDE_STATE_DIR / OPENCLAUDE_LAUNCHER_NAME
    script_path.write_text(
        build_openclaude_launcher_script(normalized), encoding="utf-8"
    )
    return script_path


def build_terminal_launch_command(script_path: Path) -> tuple[str, ...]:
    script = str(Path(script_path).expanduser().resolve())
    if os.name == "nt":
        return (
            "cmd.exe",
            "/c",
            "start",
            "FZAstro OpenClaude",
            "powershell.exe",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
        )

    shell = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"
    return (shell, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", script)


def launch_openclaude_companion(
    config: OpenClaudeLaunchConfig,
    *,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    task_prompt: str | None = None,
) -> OpenClaudeLaunchResult:
    status = get_openclaude_tool_status(env=env)
    prompt = str(task_prompt or safe_first_prompt())
    prompt_path = write_openclaude_task_prompt(prompt)
    script_path = write_openclaude_launcher(config)
    command = build_terminal_launch_command(script_path)

    if dry_run:
        return OpenClaudeLaunchResult(
            ok=True,
            message="OpenClaude companion launch command prepared.",
            script_path=script_path,
            command=command,
            status=status,
            safe_prompt=prompt,
            prompt_path=prompt_path,
        )

    try:
        subprocess.Popen(command, cwd=str(Path(config.project_root).resolve()))
    except Exception as exc:  # pragma: no cover - platform/process dependent
        raise OpenClaudeBridgeError(
            f"Could not launch OpenClaude terminal: {exc}"
        ) from exc

    return OpenClaudeLaunchResult(
        ok=True,
        message="OpenClaude companion launched in a separate terminal.",
        script_path=script_path,
        command=command,
        status=status,
        safe_prompt=prompt,
        prompt_path=prompt_path,
    )


def format_openclaude_status_markdown(
    config: OpenClaudeLaunchConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    status = get_openclaude_tool_status(env=env)
    root_text = str(Path(config.project_root).expanduser())
    env_map = build_openclaude_environment(config)
    missing = ", ".join(status.missing) if status.missing else "none"
    readiness = "ready" if status.is_ready else "needs setup"
    source_ok = looks_like_fzastro_source_root(config.project_root)
    source_state = (
        "valid FZAstro source checkout"
        if source_ok
        else "not a FZAstro source checkout"
    )
    return "\n".join(
        [
            "# OpenClaude Companion Status",
            "",
            f"**State:** {readiness}",
            f"**Missing tools:** {missing}",
            f"**Project:** `{root_text}` ({source_state})",
            f"**Model:** `{env_map['OPENAI_MODEL']}`",
            f"**Endpoint:** `{env_map['OPENAI_BASE_URL']}`",
            "",
            "## Tool paths",
            f"- Node: `{status.node_path or 'not found'}`",
            f"- npm: `{status.npm_path or 'not found'}`",
            f"- OpenClaude: `{status.openclaude_path or 'not found'}`",
            "",
            "## Deploy behavior",
            "- FZAstro keeps using Ollama/OpenAI-compatible APIs directly for normal chat.",
            "- OpenClaude runs in the selected workspace using the selected FZAstro model.",
            "- The runtime launcher is generated under AppData/Roaming/FZAstroAI/openclaude so frozen EXE builds do not depend on source-relative scripts.",
        ]
    )

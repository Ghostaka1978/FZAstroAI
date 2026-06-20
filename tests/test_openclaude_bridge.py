from pathlib import Path
import os

import pytest

from fzastro_ai.dev_agent.openclaude_bridge import (
    OpenClaudeBridgeError,
    OpenClaudeLaunchConfig,
    build_openclaude_environment,
    build_openclaude_launcher_script,
    build_openclaude_project_context,
    build_openclaude_task_prompt,
    get_openclaude_tool_status,
    launch_openclaude_companion,
    looks_like_fzastro_source_root,
    openclaude_artifact_paths,
    powershell_single_quote,
    safe_first_prompt,
    validate_openclaude_project_root,
)


def make_fzastro_root(tmp_path: Path) -> Path:
    root = tmp_path / "FZAstroAI"
    (root / "fzastro_ai").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return root


def test_openclaude_environment_uses_selected_runtime(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(
        project_root=root,
        model="rafw007/qwen3-coder:latest",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
    )

    env = build_openclaude_environment(config)

    assert env["CLAUDE_CODE_USE_OPENAI"] == "1"
    assert env["OPENAI_MODEL"] == "rafw007/qwen3-coder:latest"
    assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "ollama"
    assert env["FZASTRO_PROJECT_ROOT"] == str(root.resolve())


def test_project_root_validation_accepts_real_workspace_folder(tmp_path):
    root = make_fzastro_root(tmp_path)
    assert looks_like_fzastro_source_root(root)
    assert validate_openclaude_project_root(root) == root.resolve()

    generic_workspace = tmp_path / "generic-workspace"
    generic_workspace.mkdir()
    assert not looks_like_fzastro_source_root(generic_workspace)
    assert (
        validate_openclaude_project_root(generic_workspace)
        == generic_workspace.resolve()
    )

    missing = tmp_path / "missing"
    with pytest.raises(OpenClaudeBridgeError, match="Workspace folder does not exist"):
        validate_openclaude_project_root(missing)


def test_tool_status_finds_commands_from_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ["node", "npm", "openclaude"]:
        command = bin_dir / name
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)

    status = get_openclaude_tool_status(env={"PATH": str(bin_dir)})

    assert status.is_ready
    assert status.missing == ()
    assert status.node_path.endswith("node")
    assert status.npm_path.endswith("npm")
    assert status.openclaude_path.endswith("openclaude")


def test_tool_status_reports_missing_openclaude(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ["node", "npm"]:
        command = bin_dir / name
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)

    status = get_openclaude_tool_status(env={"PATH": str(bin_dir)})

    assert not status.is_ready
    assert status.missing == ("openclaude",)


def test_powershell_launcher_script_is_deploy_aware(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(
        project_root=root,
        model="qwen's coder",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        install_if_missing=True,
    )

    script = build_openclaude_launcher_script(config)

    assert "$env:CLAUDE_CODE_USE_OPENAI = '1'" in script
    assert "$env:OPENAI_MODEL = 'qwen''s coder'" in script
    assert "C:\\Program Files\\nodejs" in script
    assert "Join-Path $env:APPDATA 'npm'" in script
    assert "install -g @gitlawb/openclaude@latest" in script
    assert "Set-Location -LiteralPath $projectRoot" in script


def test_powershell_single_quote_escapes_quotes():
    assert powershell_single_quote("a'b") == "'a''b'"


def test_safe_first_prompt_bootstraps_workspace_agent():
    prompt = safe_first_prompt()

    assert "selected workspace" in prompt
    assert "Interact normally as a coding agent" in prompt
    assert "latest_project_context.md" in prompt


def test_launch_dry_run_prepares_command_and_prompt(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(project_root=root, model="qwen3:32b")

    result = launch_openclaude_companion(config, dry_run=True, env={"PATH": ""})

    assert result.ok
    assert result.script_path.exists()
    assert result.command
    assert result.prompt_path is not None
    assert result.prompt_path.exists()
    assert "selected workspace" in result.safe_prompt
    assert "latest_project_context.md" in result.safe_prompt


def test_openclaude_task_prompt_uses_user_task_and_patch_mode():
    prompt = build_openclaude_task_prompt(
        "Improve OpenClaude timeout labels", mode="patch-run-tests"
    )

    assert "Improve OpenClaude timeout labels" in prompt
    assert "patch work is allowed" in prompt
    assert "Do not claim tests passed" in prompt


def test_launcher_script_starts_openclaude_without_prompt_preamble(tmp_path):
    root = make_fzastro_root(tmp_path)
    script = build_openclaude_launcher_script(OpenClaudeLaunchConfig(project_root=root))

    assert "& $openClaudeCommand.Source" in script
    assert "latest_openclaude_prompt.md" not in script
    assert "Prompt file:" not in script
    assert "Ready. FZAstro" not in script


def test_openclaude_project_context_contains_workspace_guidance(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(
        project_root=root,
        model="rafw007/qwen36-a3b-claude-coder:latest",
        base_url="http://localhost:11434/v1",
    )

    context = build_openclaude_project_context(
        config, mode="patch-run-tests", safety="ask-before-editing"
    )

    assert "FZAstro OpenClaude Context" in context
    assert str(root) in context
    assert "OpenClaude owns the interactive review/edit/test flow" in context
    assert "old DEV pipeline" in context
    assert "Workspace Capabilities" in context
    assert "run Python and shell commands" in context
    assert "FZAstro source checkout" in context


def test_openclaude_task_prompt_references_workspace_artifacts(tmp_path):
    paths = openclaude_artifact_paths()
    prompt = build_openclaude_task_prompt(
        "Patch the OpenClaude workspace",
        mode="patch-run-tests",
        context_path=paths["context"],
        output_log_path=paths["output_log"],
        diff_path=paths["diff"],
        report_path=paths["report"],
    )

    assert "selected workspace" in prompt
    assert "Useful FZAstro artifact targets" in prompt
    assert "latest_project_context.md" in prompt
    assert "latest_openclaude_output.log" in prompt
    assert "latest_diff.patch" in prompt
    assert "latest_report.md" in prompt

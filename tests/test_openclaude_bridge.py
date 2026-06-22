from pathlib import Path
import os

import pytest

from fzastro_ai.dev_agent.openclaude_bridge import (
    OpenClaudeBridgeError,
    OpenClaudeLaunchConfig,
    audit_openclaude_project_root,
    build_openclaude_environment,
    build_openclaude_launcher_script,
    build_openclaude_project_context,
    build_openclaude_task_prompt,
    openclaude_workspace_isolation_lines,
    get_openclaude_tool_status,
    normalize_claude_code_max_output_tokens,
    normalize_claude_code_max_context_tokens,
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
        max_output_tokens="24000",
    )

    env = build_openclaude_environment(config)

    assert env["CLAUDE_CODE_USE_OPENAI"] == "1"
    assert env["OPENAI_MODEL"] == "rafw007/qwen3-coder:latest"
    assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "ollama"
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "24000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "128000"
    assert env["OPENAI_MAX_CONTEXT_TOKENS"] == "128000"
    assert "FZASTRO_OPENCLAUDE_API_KEY_FILE" not in env
    assert env["FZASTRO_OPENCLAUDE_SETTINGS_FILE"].endswith("openclaude_settings.json")
    assert env["FZASTRO_OPENCLAUDE_GIT_TOKEN_FILE"].endswith("openclaude_settings.json")
    assert env["FZASTRO_PROJECT_ROOT"] == str(root.resolve())
    assert env["OPENCLAUDE_WORKSPACE_ROOT"] == str(root.resolve())
    assert env["FZASTRO_WORKSPACE_BOUNDARY"] == str(root.resolve())
    assert env["GIT_CEILING_DIRECTORIES"] == str(root.resolve().parent)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_0"] == ""


def test_openclaude_launcher_forwards_args_and_caps_output_tokens(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(project_root=root, model="qwen3:32b")

    script = build_openclaude_launcher_script(config)

    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" in script
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" in script
    assert "OPENAI_MAX_CONTEXT_TOKENS" in script
    assert "CLAUDE_CODE_USE_POWERSHELL_TOOL" in script
    assert "16000" in script
    assert "& $openClaudeCommand.Source @args" in script
    assert "openclaude --continue" in script


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


def test_openclaude_workspace_audit_blocks_parent_git_checkout_leak(tmp_path):
    parent_repo = tmp_path / "parent-repo"
    selected = parent_repo / "subproject"
    selected.mkdir(parents=True)
    (parent_repo / ".git").mkdir()

    with pytest.raises(OpenClaudeBridgeError, match="inside another Git checkout"):
        audit_openclaude_project_root(selected)

    with pytest.raises(OpenClaudeBridgeError, match="inside another Git checkout"):
        validate_openclaude_project_root(selected)


def test_openclaude_workspace_audit_blocks_broad_folder_with_nested_repos(tmp_path):
    broad = tmp_path / "Dropbox"
    nested = broad / "ProjectA"
    nested.mkdir(parents=True)
    (nested / ".git").mkdir()

    with pytest.raises(OpenClaudeBridgeError, match="contains nested Git projects"):
        audit_openclaude_project_root(broad)


def test_openclaude_workspace_audit_allows_exact_repo_root(tmp_path):
    root = make_fzastro_root(tmp_path)
    (root / ".git").mkdir()

    audit = audit_openclaude_project_root(root)

    assert audit.root == root.resolve()
    assert audit.git_root == root.resolve()
    assert audit.nested_git_roots == ()


def test_openclaude_workspace_isolation_lines_are_explicit(tmp_path):
    root = make_fzastro_root(tmp_path)
    (root / ".git").mkdir()

    lines = openclaude_workspace_isolation_lines(root)

    assert lines[0] == "Workspace isolation: active ✓"
    assert f"Workspace boundary: {root.resolve()}" in lines
    assert f"Git ceiling: {root.resolve().parent}" in lines
    assert "Nested Git workspaces: none detected" in lines


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
        api_key="sk-secret-not-in-script",
        install_if_missing=True,
    )

    script = build_openclaude_launcher_script(config)

    assert "$env:CLAUDE_CODE_USE_OPENAI = '1'" in script
    assert "$env:CLAUDE_CODE_USE_POWERSHELL_TOOL = '1'" in script
    assert "$env:OPENAI_MODEL = 'qwen''s coder'" in script
    assert "sk-secret-not-in-script" not in script
    assert "FZASTRO_OPENCLAUDE_API_KEY_FILE" not in script
    assert "FZASTRO_OPENCLAUDE_SETTINGS_FILE" in script
    assert "FZASTRO_OPENCLAUDE_GIT_TOKEN_FILE" in script
    assert "ConvertFrom-Json" in script
    assert "C:\\Program Files\\nodejs" in script
    assert "Join-Path $env:APPDATA 'npm'" in script
    assert "install -g @gitlawb/openclaude@latest" in script
    assert "Set-Location -LiteralPath $resolvedProjectRoot" in script
    assert "$env:GIT_CEILING_DIRECTORIES" in script
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in script
    assert "$env:GIT_CONFIG_NOSYSTEM = '1'" in script
    assert "$env:GIT_CONFIG_KEY_0 = 'credential.helper'" in script
    assert "workspace boundary mismatch" in script.lower()


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
    assert "hard safety boundary" in prompt


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
    assert "Workspace boundary" in context
    assert (
        "Do not read, summarize, modify, or infer details from sibling/parent projects"
        in context
    )
    assert (
        "Git credential helpers from system/global Git config are disabled" in context
    )


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


def test_openclaude_environment_supplies_git_api_token_only_when_configured(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(
        project_root=root,
        model="qwen3:32b",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        git_api_token="github_pat_repo_secret",
    )

    env = build_openclaude_environment(config)

    assert env["GITHUB_TOKEN"] == "github_pat_repo_secret"
    assert env["GH_TOKEN"] == "github_pat_repo_secret"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_launcher_script_reads_git_api_token_without_embedding_secret(tmp_path):
    root = make_fzastro_root(tmp_path)
    config = OpenClaudeLaunchConfig(
        project_root=root,
        api_key="sk-model-secret",
        git_api_token="github_pat_secret_not_in_script",
    )

    script = build_openclaude_launcher_script(config)

    assert "github_pat_secret_not_in_script" not in script
    assert "sk-model-secret" not in script
    assert "$env:GITHUB_TOKEN = [string]$apiSettings.git_api_token" in script
    assert "$env:GH_TOKEN = [string]$apiSettings.git_api_token" in script
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in script


def test_openclaude_max_output_tokens_normalizer_clamps_provider_budget():
    assert normalize_claude_code_max_output_tokens("512") == "1024"
    assert normalize_claude_code_max_output_tokens("16000") == "16000"
    assert normalize_claude_code_max_output_tokens("999999") == "24000"
    assert normalize_claude_code_max_output_tokens("not-a-number") == "16000"


def test_openclaude_context_cap_is_fixed_at_128000():
    assert normalize_claude_code_max_context_tokens() == "128000"
    assert normalize_claude_code_max_context_tokens("999999") == "128000"
    assert normalize_claude_code_max_context_tokens("4096") == "8192"

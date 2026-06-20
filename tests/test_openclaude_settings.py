from pathlib import Path
import os

from fzastro_ai.dev_agent.openclaude_settings import (
    clear_openclaude_api_key,
    load_openclaude_api_settings,
    openclaude_api_key_state,
    save_openclaude_api_key,
)


def test_openclaude_api_key_saves_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings_file = (
        tmp_path / "appdata" / "FZAstroAI" / "openclaude" / "openclaude_settings.json"
    )

    saved = save_openclaude_api_key("sk-test-secret", settings_file=settings_file)
    loaded = load_openclaude_api_settings(settings_file=settings_file)

    assert saved.has_api_key
    assert loaded.api_key == "sk-test-secret"
    assert Path(loaded.path) == settings_file
    assert workspace not in settings_file.parents
    assert not (workspace / "openclaude_settings.json").exists()


def test_openclaude_api_key_file_is_private_when_supported(tmp_path):
    settings_file = tmp_path / "settings.json"

    save_openclaude_api_key("sk-private", settings_file=settings_file)

    if os.name != "nt":
        mode = settings_file.stat().st_mode & 0o777
        assert mode == 0o600


def test_openclaude_api_key_clear_removes_file(tmp_path):
    settings_file = tmp_path / "settings.json"

    save_openclaude_api_key("sk-to-clear", settings_file=settings_file)
    assert settings_file.exists()

    cleared = clear_openclaude_api_key(settings_file=settings_file)

    assert not cleared.has_api_key
    assert not settings_file.exists()
    assert load_openclaude_api_settings(settings_file=settings_file).api_key == ""


def test_openclaude_api_key_state_never_exposes_value(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings = save_openclaude_api_key("sk-visible-bug", settings_file=settings_file)

    state = openclaude_api_key_state(settings, fallback_api_key="ollama")

    assert "stored locally" in state
    assert "hidden" in state
    assert "sk-visible-bug" not in state


def test_openclaude_git_api_token_saves_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings_file = (
        tmp_path / "appdata" / "FZAstroAI" / "openclaude" / "openclaude_settings.json"
    )

    from fzastro_ai.dev_agent.openclaude_settings import save_openclaude_git_api_token

    saved = save_openclaude_git_api_token(
        "github_pat_secret", settings_file=settings_file
    )
    loaded = load_openclaude_api_settings(settings_file=settings_file)

    assert saved.has_git_api_token
    assert loaded.git_api_token == "github_pat_secret"
    assert Path(loaded.path) == settings_file
    assert workspace not in settings_file.parents
    assert not (workspace / "openclaude_settings.json").exists()


def test_openclaude_git_token_state_never_exposes_value(tmp_path):
    from fzastro_ai.dev_agent.openclaude_settings import (
        openclaude_git_token_state,
        save_openclaude_git_api_token,
    )

    settings_file = tmp_path / "settings.json"
    settings = save_openclaude_git_api_token(
        "github_pat_visible_bug", settings_file=settings_file
    )

    state = openclaude_git_token_state(settings)

    assert "stored locally" in state
    assert "hidden" in state
    assert "github_pat_visible_bug" not in state


def test_openclaude_git_api_token_clear_preserves_model_key(tmp_path):
    from fzastro_ai.dev_agent.openclaude_settings import (
        clear_openclaude_git_api_token,
        save_openclaude_git_api_token,
    )

    settings_file = tmp_path / "settings.json"
    save_openclaude_api_key("sk-model", settings_file=settings_file)
    save_openclaude_git_api_token("github_pat_repo", settings_file=settings_file)

    cleared = clear_openclaude_git_api_token(settings_file=settings_file)

    assert cleared.api_key == "sk-model"
    assert cleared.git_api_token == ""
    assert settings_file.exists()

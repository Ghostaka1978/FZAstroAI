from pathlib import Path


def dev_workbench_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "fzastro_ai"
        / "ui"
        / "dev_workbench_dialog.py"
    ).read_text(encoding="utf-8")


def test_claude_terminal_has_no_status_button_in_header():
    source = dev_workbench_source()

    assert "terminal_header.addWidget(self.openclaude_status_button)" not in source
    assert "self.openclaude_status_button.setVisible(False)" in source
    assert "OpenClaude terminal state:" in source


def test_session_git_identity_is_explicitly_workspace_scoped():
    source = dev_workbench_source()

    assert "Git root path:" in source
    assert "Git identity source: selected workspace .git/config only" in source
    assert "Git parent/sibling repos: not queried" in source
    assert "Git remote from selected clone:" in source
    assert "Git root: {Path(top).name" not in source


def test_openclaude_launch_button_is_action_not_status_badge():
    source = dev_workbench_source()

    assert 'text = "Restart"' in source
    assert 'text = "● Running"' not in source
    assert 'text = "● Stopped"' not in source


def test_session_uses_git_token_file_name_not_api_key_file():
    source = dev_workbench_source()

    assert "FZASTRO_OPENCLAUDE_GIT_TOKEN_FILE=" in source
    assert "FZASTRO_OPENCLAUDE_API_KEY_FILE=" not in source
    assert "Git API token file: AppData only / hidden / not scanned" in source


def test_session_warns_when_running_terminal_settings_are_stale():
    source = dev_workbench_source()

    assert "_openclaude_launch_snapshot" in source
    assert (
        "Restart required: running OpenClaude was launched with older settings"
        in source
    )
    assert "Running settings: current" in source


def test_session_tab_uses_scroll_area_for_long_diagnostics():
    source = dev_workbench_source()

    assert "self.session_config_scroll = QScrollArea()" in source
    assert "self.session_config_scroll.setWidgetResizable(True)" in source
    assert (
        "self.session_config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)"
        in source
    )
    assert "self.session_config_scroll.setWidget(config_box)" in source
    assert "self.session_config_panel = self.session_config_scroll" in source
    assert (
        "self.session_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)"
        in source
    )

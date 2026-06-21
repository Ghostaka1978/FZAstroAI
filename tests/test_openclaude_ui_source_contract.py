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
    assert "config_layout.addLayout(session_action_row)" in source
    assert "self.openclaude_status_button.setVisible(True)" in source
    assert "Claude Terminal state:" in source


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


def test_openclaude_terminal_exposes_image_handoff_controls():
    source = dev_workbench_source()

    assert 'QPushButton("Paste Image")' in source
    assert 'QPushButton("Attach Image")' in source
    assert 'QPushButton("Send Shot")' in source
    assert "paste_clipboard_image_to_openclaude" in source
    assert "attach_image_file_to_openclaude" in source
    assert "send_terminal_screenshot_to_openclaude" in source
    assert "build_image_handoff_prompt" in source
    assert "openclaude_paste_image_button" in source
    assert "openclaude_attach_image_button" in source
    assert "openclaude_send_screenshot_button" in source


def test_openclaude_terminal_exposes_jump_to_top_scrollback():
    source = dev_workbench_source()

    assert 'QPushButton("Top")' in source
    assert "openclaude_top_button" in source
    assert "scroll_to_top()" in source
    assert "Jump to the oldest retained OpenClaude terminal scrollback." in source


def test_openclaude_dev_git_diagnostics_hide_helper_consoles():
    source = dev_workbench_source()

    assert "from ..dev_agent.subprocess_utils import hidden_subprocess_kwargs" in source
    assert "**hidden_subprocess_kwargs()" in source


def test_openclaude_terminal_has_recovery_action_buttons():
    source = dev_workbench_source()

    assert 'QPushButton("Continue")' in source
    assert 'QPushButton("Resume")' in source
    assert 'QPushButton("Prompt")' in source
    assert 'QPushButton("Help")' in source
    assert "run_openclaude_continue" in source
    assert "run_openclaude_resume_last" in source
    assert "start_openclaude_shell_prompt" in source
    assert "send_openclaude_help_command" in source
    assert "openclaude --continue" in source
    assert "openclaude --resume" in source
    assert 'worker.send_input(clean_command.rstrip("\\r\\n") + "\\r")' in source


def test_openclaude_terminal_header_groups_actions_by_compact_submenus():
    source = dev_workbench_source()

    assert "QToolButton" in source
    assert "QMenu" in source
    assert "self.openclaude_session_menu_button = _menu_button(" in source
    assert "self.openclaude_claude_menu_button = _menu_button(" in source
    assert "self.openclaude_input_menu_button = _menu_button(" in source
    assert "self.openclaude_view_menu_button = _menu_button(" in source
    assert "terminal_header.addWidget(self.openclaude_session_menu_button)" in source
    assert "terminal_header.addWidget(self.openclaude_claude_menu_button)" in source
    assert "terminal_header.addWidget(self.openclaude_input_menu_button)" in source
    assert "terminal_header.addWidget(self.openclaude_view_menu_button)" in source
    assert "Page Down" in source
    assert "page_down_openclaude_terminal" in source
    assert "terminal_header.addWidget(self.openclaude_continue_button)" not in source
    assert "terminal_header.addWidget(self.openclaude_resume_button)" not in source
    assert "terminal_header.addWidget(self.openclaude_shell_button)" not in source


def test_openclaude_prompt_is_separate_tabbed_shell():
    source = dev_workbench_source()

    assert "self.openclaude_prompt_frame = QFrame()" in source
    assert (
        'self.workspace_tabs.addTab(self.openclaude_prompt_frame, "Prompt")' in source
    )
    assert "self.openclaude_prompt_output = OpenClaudeTerminalWidget()" in source
    assert "start_openclaude_prompt_terminal" in source
    assert "self.openclaude_prompt_worker" in source
    assert "shell_only=True" in source


def test_session_tab_shows_powershell_tool_environment():
    source = dev_workbench_source()

    assert "CLAUDE_CODE_USE_POWERSHELL_TOOL=" in source
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS=" in source
    assert "session_summary_label" in source
    assert "Prompt tab state:" in source


def test_openclaude_terminal_exposes_common_slash_command_actions():
    source = dev_workbench_source()

    assert 'QPushButton("Ctx")' in source
    assert 'QPushButton("Output")' in source
    assert 'QPushButton("Clear")' in source
    assert 'QPushButton("Config")' in source
    assert 'QPushButton("Buddy")' in source
    assert "send_openclaude_ctx_command" in source
    assert "set_openclaude_output_budget" in source
    assert "send_openclaude_clear_command" in source
    assert "send_openclaude_config_command" in source
    assert "send_openclaude_buddy_command" in source
    assert "_send_openclaude_slash_command" in source
    assert "Set Output Tokens" in source
    assert 'worker.send_input(clean_command.rstrip("\\r\\n") + "\\r")' in source


def test_session_tab_keeps_prompt_and_help_out_of_visible_actions():
    source = dev_workbench_source()

    assert "session_action_row.addWidget(self.session_help_button)" not in source
    assert "session_action_row.addWidget(self.session_prompt_button)" not in source
    assert 'session_action_row.addWidget(QLabel("Shell:"))' not in source
    assert "self.session_help_button.setVisible(False)" in source
    assert "self.session_prompt_button.setVisible(False)" in source


def test_openclaude_terminal_output_is_buffered_for_ui_responsiveness():
    source = dev_workbench_source()

    assert "_openclaude_terminal_output_buffer" in source
    assert "_flush_openclaude_terminal_output" in source
    assert "timer.start(24)" in source
    assert (
        "Buffering keeps the UI responsive during high-frequency TUI repaint bursts."
        in source
    )


def test_openclaude_terminals_are_stopped_before_window_close_and_exe_cleanup():
    source = dev_workbench_source()
    shutdown_source = (
        Path(__file__).resolve().parents[1]
        / "fzastro_ai"
        / "controllers"
        / "shutdown_controller.py"
    ).read_text(encoding="utf-8-sig")

    assert "def shutdown_embedded_terminals_for_close" in source
    assert "def prepare_for_app_shutdown" in source
    assert "def closeEvent" in source
    assert "_MEI extraction directory" in source
    assert "self._stop_openclaude_workspace_on_exit()" in shutdown_source
    assert "Stopping OpenClaude terminals" in shutdown_source


def test_build_packages_python_openclaude_backend_and_treats_external_tools_as_runtime_prereqs():
    build_source = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_exe.ps1"
    ).read_text(encoding="utf-8-sig")
    docs_source = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8-sig"
    )

    assert "Prepare embedded OpenClaude runtime" in build_source
    assert "-InstallEmbeddedTerminalBackend" in build_source
    assert "-InstallTerminalFrontend" in build_source
    assert 'modules.append("winpty")' in build_source
    assert "pywinpty/winpty is required" in build_source
    assert "External prerequisites" in docs_source
    assert "OpenClaude CLI" in docs_source
    assert "Ollama" in docs_source


def test_openclaude_session_shows_prerequisites_and_changeable_ctx_budget():
    source = dev_workbench_source()

    assert "External prerequisites:" in source
    assert "OpenClaude CLI:" in source
    assert "Ollama CLI:" in source
    assert "Prerequisite policy: external tools are detected and reported" in source
    assert "save_openclaude_max_output_tokens" in source
    assert "openclaude_max_output_tokens_state" in source
    assert "max_output_tokens=self._active_openclaude_max_output_tokens()" in source
    assert "output-token setting changed" in source
    assert "Output tokens:" in source

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_window_defaults_apply_shared_palette_stylesheet_and_activation():
    text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "window_utils.py").read_text(
        encoding="utf-8-sig"
    )

    assert "def apply_fzastro_window_palette" in text
    assert "QPalette.Window" in text
    assert "QPalette.Highlight" in text
    assert "def apply_fzastro_window_stylesheet" in text
    assert "from .styles import get_main_stylesheet" in text
    assert "window.setStyleSheet(get_main_stylesheet())" in text
    assert "def bring_window_to_front" in text
    assert "window.activateWindow()" in text


def test_chat_renderer_separates_plain_text_from_markdown_display():
    text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "message_widgets.py").read_text(
        encoding="utf-8-sig"
    )

    assert "def render_text_block(text, news_mode=False, user_mode=False, plain_mode=False)" in text
    assert "html.escape(text).splitlines()" in text
    assert 'plain_mode=block.format == "plain"' in text
    assert 'extensions=["fenced_code", "tables", "sane_lists", "nl2br"]' in text
    assert "overflow-wrap: anywhere" in text
    assert ".chat-copy pre" in text
    assert ".chat-copy table" in text


def test_seeing_cloud_labels_are_explicitly_forecast_model_values():
    text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "seeing_dialog.py").read_text(
        encoding="utf-8-sig"
    )

    assert 'return "Mostly clear"' in text
    assert "if pct <= 25:" in text
    assert "if pct <= 55:" in text
    assert "Cloud forecast" in text
    assert "Forecast model points for selected day" in text
    assert "day forecast cloud" in text
    assert "Forecast cloud" in text
    assert "day avg" in text
    assert "7Timer ASTRO + Open-Meteo Cloud + Moon/Dark" in text
    assert "Twilight cloud forecast" in text
    assert "twilight avg" in text
    assert "twilight forecast cloud" in text
    assert "TWILIGHT" in text
    assert "Best window" in text
    assert "twilight fallback" in text


def test_seeing_dialog_owns_twilight_helpers_used_by_day_blocks():
    text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "seeing_dialog.py").read_text(
        encoding="utf-8-sig"
    )

    dialog_start = text.index("class SeeingDialog")
    build_start = text.index("def _build_24h_blocks", dialog_start)
    dialog_preamble = text[dialog_start:build_start]

    assert "def _is_twilight_row" in dialog_preamble
    assert "def _imaging_rows" in dialog_preamble
    assert "def _planning_scope" in dialog_preamble
    assert "self._is_twilight_row(row)" in text[build_start:]
    assert "self._imaging_rows(block_rows)" in text[build_start:]
    assert "self._planning_scope(block_rows)" in text[build_start:]


def test_main_app_hosts_tool_windows_in_workspace_tabs():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(
        encoding="utf-8-sig"
    )
    workspace_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "workspace_tabs.py"
    ).read_text(encoding="utf-8-sig")
    main_layout_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "main_layout.py"
    ).read_text(encoding="utf-8-sig")

    assert "WorkspaceTabsMixin" in app_text
    assert "self.create_workspace_tabs(chat_surface)" in app_text
    assert "self.composer_shell = composer_shell" in app_text
    assert "class WorkspaceTabsMixin" in workspace_text
    assert "def open_workspace_tab" in workspace_text
    assert "def close_workspace_tab" in workspace_text
    assert "def _update_workspace_chat_chrome" in workspace_text
    assert "composer_shell.setVisible(is_chat_tab)" in workspace_text
    assert "thought_panel.hide()" in workspace_text
    assert "workspace_tabs.currentIndex() != 0" in main_layout_text
    assert "setTabsClosable(False)" in workspace_text
    assert "workspaceTabCloseButton" in workspace_text
    assert "workspaceTabPage" in workspace_text
    assert "workspaceAppsButton" in workspace_text
    assert "setCornerWidget" in workspace_text
    assert "def _build_workspace_apps_menu" in workspace_text
    assert 'tabs.addTab(chat_widget, "Chat")' in workspace_text


def test_workspace_apps_button_opens_key_tabbed_tools():
    workspace_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "workspace_tabs.py"
    ).read_text(encoding="utf-8-sig")
    styles_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "styles.py").read_text(
        encoding="utf-8-sig"
    )

    for handler_name in (
        "open_astro_lookup_dialog",
        "open_astro_targets_dialog",
        "open_astro_forecast_dialog",
        "open_sun_now_dialog",
        "open_solar_system_map",
        "open_nina_control",
        "open_document_knowledge_library",
        "open_persistent_memory_library",
        "open_dev_workbench",
        "open_llm_benchmark_dashboard",
        "open_help_cheat_sheet",
        "open_diagnostics_window",
    ):
        assert handler_name in workspace_text

    assert "_run_workspace_app" in workspace_text
    assert "QMenu(self)" in workspace_text
    assert "QPushButton#workspaceAppsButton" in styles_text


def test_major_tool_helpers_open_as_workspace_tabs():
    tabbed_files = {
        "lookup": PROJECT_ROOT / "fzastro_ai" / "ui" / "astro_lookup_dialog.py",
        "seeing": PROJECT_ROOT / "fzastro_ai" / "ui" / "seeing_dialog.py",
        "sun": PROJECT_ROOT / "fzastro_ai" / "ui" / "sun_now_dialog.py",
        "solar": PROJECT_ROOT / "fzastro_ai" / "ui" / "solar_map_dialog.py",
        "targets": PROJECT_ROOT / "fzastro_ai" / "ui" / "targets_dialog.py",
        "nina": PROJECT_ROOT / "fzastro_ai" / "ui" / "nina_control_dialog.py",
        "dev": PROJECT_ROOT / "fzastro_ai" / "ui" / "dev_workbench_dialog.py",
        "bench": PROJECT_ROOT / "fzastro_ai" / "ui" / "llm_benchmark_dialog.py",
    }

    for name, path in tabbed_files.items():
        text = path.read_text(encoding="utf-8-sig")
        assert "open_workspace_tab" in text, name


def test_workspace_tabs_remove_redundant_dialog_buttons():
    workspace_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "workspace_tabs.py"
    ).read_text(encoding="utf-8-sig")

    assert "QDialogButtonBox" in workspace_text
    assert "def _hide_redundant_dialog_buttons_for_tab" in workspace_text
    assert "save" in workspace_text
    assert "button_box.hide()" in workspace_text
    assert 'widget.setProperty("fzastro_workspace_tab", True)' in workspace_text


def test_targets_tab_prioritizes_sky_preview_and_metadata():
    targets_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "targets_dialog.py"
    ).read_text(encoding="utf-8-sig")
    styles_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "styles.py").read_text(
        encoding="utf-8-sig"
    )

    assert "root.addWidget(self._build_header())" not in targets_text
    assert "self.details_browser.setVisible(False)" in targets_text
    assert "self.inline_lookup_browser.setVisible(False)" in targets_text
    assert "side.addWidget(self.details_browser" not in targets_text
    assert "side.addWidget(self.inline_lookup_browser" not in targets_text
    assert "side.addLayout(lookup_header)" not in targets_text
    assert "self.inline_lookup_image_label.setMinimumSize(320, 260)" in targets_text
    assert "self.inline_lookup_image_label.setMaximumHeight(170)" not in targets_text
    assert "image_panel.setMaximumHeight(220)" not in targets_text
    assert "self.inline_lookup_meta_label" in targets_text
    assert "def _lookup_distance_from_text" in targets_text
    assert "targetPreviewMetaLabel" in styles_text


def test_management_panels_cleanup_when_opened_as_tabs():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(
        encoding="utf-8-sig"
    )
    memory_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "memory_dialog.py"
    ).read_text(encoding="utf-8-sig")
    calibration_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "calibration_dialog.py"
    ).read_text(encoding="utf-8-sig")

    assert '"settings.documents"' in app_text
    assert "on_close=_clear_references" in app_text
    assert '"settings.memory"' in memory_text
    assert "on_close=_clear_references" in memory_text
    assert '"settings.system_prompt"' in calibration_text
    assert "on_close=_clear_references" in calibration_text

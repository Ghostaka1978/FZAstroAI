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

    assert "WorkspaceTabsMixin" in app_text
    assert "self.create_workspace_tabs(chat_surface)" in app_text
    assert "class WorkspaceTabsMixin" in workspace_text
    assert "def open_workspace_tab" in workspace_text
    assert "def close_workspace_tab" in workspace_text
    assert 'tabs.addTab(chat_widget, "Chat")' in workspace_text


def test_major_tool_helpers_open_as_workspace_tabs():
    tabbed_files = {
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

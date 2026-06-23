from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8-sig")


def test_sidebar_exposes_screensaver_enable_and_timeout_controls():
    app_text = read("fzastro_ai/app.py")
    state_text = read("fzastro_ai/controllers/app_state_controller.py")
    overlay_text = read("fzastro_ai/ui/idle_stars_overlay.py")

    assert '"screensaver_enabled": True' in state_text
    assert '"screensaver_timeout_seconds": 45' in state_text
    assert (
        'self.screensaver_enabled_checkbox = QCheckBox("Enable idle screensaver")'
        in app_text
    )
    assert "self.screensaver_timeout_spinbox = QSpinBox()" in app_text
    assert "self.screensaver_timeout_spinbox.setRange(10, 3600)" in app_text
    assert "def on_screensaver_enabled_changed" in app_text
    assert "def on_screensaver_timeout_changed" in app_text
    assert "def set_enabled(self, enabled: bool)" in overlay_text
    assert "def set_idle_timeout_ms(self, idle_ms: int)" in overlay_text
    assert "if not self._enabled:" in overlay_text


def test_space_live_dialog_includes_verified_iss_and_added_space_earth_sources():
    dialog_text = read("fzastro_ai/ui/iss_live_dialog.py")

    assert "class IssLiveDialog(QDialog)" in dialog_text
    assert "show_iss_live_dialog" in dialog_text
    assert "show_space_live_dialog = show_iss_live_dialog" in dialog_text
    assert 'SPACE_LIVE_TITLE = "SPACE LIVE"' in dialog_text
    assert "QWebEngineView" in dialog_text
    assert 'NASA_ISS_HD_VIDEO_ID = "MuHIx2q0Wjs"' in dialog_text
    assert "youtube-nocookie.com/embed/{NASA_ISS_HD_VIDEO_ID}" in dialog_text
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in dialog_text
    assert "origin=https%3A%2F%2Fwww.nasa.gov" in dialog_text
    assert "PlaybackRequiresUserGesture" in dialog_text
    assert "https://www.nasa.gov/live/" in dialog_text
    assert "Browser playback unavailable" in dialog_text
    assert "open_workspace_tab" in dialog_text

    # Expanded SPACE LIVE sources. The two NASA entries that user testing
    # showed as broken remain external links only, not selectable sources.
    assert 'key="nasa_iss_hd_views"' in dialog_text
    assert 'key="sen_spacetv1_4k"' in dialog_text
    assert 'key="sen_youtube_live"' in dialog_text
    assert 'key="nasa_live_events"' in dialog_text
    assert 'key="esa_web_tv"' in dialog_text
    assert 'key="esa_youtube_live"' in dialog_text
    assert 'key="noaa_goes_earth_now"' in dialog_text
    assert 'key="nasa_iss_live_video"' not in dialog_text
    assert 'key="nasa_youtube_live_channel"' not in dialog_text
    assert "External only" in dialog_text
    assert "https://www.youtube.com/watch?v=uwXgcTc8oY8" in dialog_text
    assert "https://www.youtube.com/nasa/live" in dialog_text
    assert "https://www.sen.com/" in dialog_text
    assert "https://www.youtube.com/@Sen/live" in dialog_text
    assert "https://watch.esa.int/" in dialog_text
    assert "https://www.youtube.com/esa/live" in dialog_text
    assert "https://www.goes.noaa.gov/" in dialog_text


def test_space_live_is_wired_into_astro_toolbar_skill_menu_and_workspace_menu():
    app_text = read("fzastro_ai/app.py")
    actions_text = read("fzastro_ai/actions/astro_actions.py")
    skills_text = read("fzastro_ai/skill_registry.py")
    workspace_text = read("fzastro_ai/ui/workspace_tabs.py")
    voice_text = read("fzastro_ai/voice/command_router.py")

    assert 'self.astro_iss_live_button = QPushButton("SPACE LIVE")' in app_text
    assert (
        "self.astro_iss_live_button.clicked.connect(self.open_iss_live_dialog)"
        in app_text
    )
    assert "astro_bar_layout.addWidget(self.astro_iss_live_button)" in app_text
    assert "from ..ui.iss_live_dialog import show_iss_live_dialog" in actions_text
    assert "def open_iss_live_dialog(self):" in actions_text
    assert '"astro.space_live"' in skills_text
    assert '"SPACE LIVE"' in skills_text
    assert '"open_iss_live_dialog"' in workspace_text
    assert '"iss live": "open_iss_live_dialog"' in voice_text
    assert '"space live": "open_iss_live_dialog"' in voice_text


def test_fzastro_live_dialog_is_single_site_embedded_viewer():
    dialog_text = read("fzastro_ai/ui/fzastro_live_dialog.py")

    assert 'FZASTRO_LIVE_TITLE = "FZASTRO LIVE"' in dialog_text
    assert 'FZASTRO_LIVE_URL = "https://www.fzastro.com/"' in dialog_text
    assert "class FZAstroLiveDialog(QDialog)" in dialog_text
    assert "show_fzastro_live_dialog" in dialog_text
    assert "QWebEngineView" in dialog_text
    assert "QDialogButtonBox" in dialog_text
    assert "QDialogButtonBox.Close" in dialog_text
    assert "view.load(QUrl(FZASTRO_LIVE_URL))" in dialog_text
    assert "open_workspace_tab" in dialog_text
    assert '"astro.fzastro_live"' in dialog_text
    assert "Browser playback unavailable" in dialog_text
    assert "This app intentionally loads only one site." in dialog_text


def test_fzastro_live_is_wired_into_toolbar_skill_workspace_voice_and_manifest():
    app_text = read("fzastro_ai/app.py")
    actions_text = read("fzastro_ai/actions/astro_actions.py")
    skills_text = read("fzastro_ai/skill_registry.py")
    workspace_text = read("fzastro_ai/ui/workspace_tabs.py")
    voice_text = read("fzastro_ai/voice/command_router.py")
    manifest_text = read("fzastro_ai/tool_manifest.py")

    assert 'self.astro_fzastro_live_button = QPushButton("FZASTRO LIVE")' in app_text
    assert (
        "self.astro_fzastro_live_button.clicked.connect(self.open_fzastro_live_dialog)"
        in app_text
    )
    assert "astro_bar_layout.addWidget(self.astro_fzastro_live_button)" in app_text
    assert (
        "from ..ui.fzastro_live_dialog import show_fzastro_live_dialog" in actions_text
    )
    assert "def open_fzastro_live_dialog(self):" in actions_text
    assert "show_fzastro_live_dialog(self)" in actions_text
    assert '"astro.fzastro_live"' in skills_text
    assert '"FZASTRO LIVE"' in skills_text
    assert '"open_fzastro_live_dialog"' in workspace_text
    assert '"fzastro live": "open_fzastro_live_dialog"' in voice_text
    assert '"astro.fzastro_live"' in manifest_text

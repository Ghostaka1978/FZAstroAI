from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUN_WORKER = PROJECT_ROOT / "fzastro_ai" / "workers" / "sun_now_worker.py"
SUN_DIALOG = PROJECT_ROOT / "fzastro_ai" / "ui" / "sun_now_dialog.py"
LOOKUP_DIALOG = PROJECT_ROOT / "fzastro_ai" / "ui" / "astro_lookup_dialog.py"


def test_sun_now_worker_has_sdo_daily_movie_and_feed_sources():
    source = SUN_WORKER.read_text(encoding="utf-8-sig")

    assert "SDO_DASHBOARD_URL" in source
    assert "SDO_FEEDS_PAGE_URL" in source
    assert "SDO_MISSION_BLOG_RSS_URL" in source
    assert "SWPC_RSS_URL" in source
    assert "def movie_feed_url" in source
    assert "def latest_movie_url" in source
    assert "SDO_LATEST_MOVIE_BASE_URL" in source
    assert "dailymov_" in source
    assert "load_sun_now_movie" in source
    assert "load_solar_news" in source


def test_sun_now_dialog_can_switch_between_image_and_looping_movie_mode():
    source = SUN_DIALOG.read_text(encoding="utf-8-sig")

    assert "Recent movie loop" in source
    assert "QMediaPlayer" in source
    assert "setLoops" in source or "EndOfMedia" in source
    assert "Alerts / news" in source
    assert "QSplitter(Qt.Horizontal)" in source


def test_lookup_setup_panel_is_collapsible_from_compact_top_row():
    source = LOOKUP_DIALOG.read_text(encoding="utf-8-sig")

    assert "self.lookup_bar_card" in source
    assert "self.setup_toggle_button" in source
    assert "self.settings_card = settings_card" in source
    assert "self.set_setup_panel_visible(False)" in source
    assert "Collapse setup" in source


def test_sun_now_prefers_recent_mpeg_before_stale_rss_fallback():
    source = SUN_WORKER.read_text(encoding="utf-8-sig")

    assert "latest_movie_url" in source
    assert "Fresh NASA/SDO recent MPEG movie loaded" in source
    assert "RSS daily movie fallback" in source
    assert source.find("latest_movie_url") < source.find("_fetch_rss_items(feed_url")


def test_lookup_has_survey_and_narrowband_options():
    source = LOOKUP_DIALOG.read_text(encoding="utf-8-sig")

    assert "Sky survey / narrowband" in source
    assert "survey_combo" in source
    assert "Finkbeiner H-alpha composite" in source
    assert "survey" in source

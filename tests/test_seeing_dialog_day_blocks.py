from __future__ import annotations

from datetime import datetime
import os

import pytest


def _row(local_iso: str, score: int = 50, astro_dark: bool = False) -> dict:
    return {
        "local_iso": local_iso,
        "local_label": local_iso[:16].replace("T", " "),
        "score": score,
        "score_label": "OK",
        "cloud_mid_pct": 30,
        "cloud_text": "19–31%",
        "astro_dark": astro_dark,
        "astro_dark_text": "Astro dark" if astro_dark else "Day/twilight",
        "moon_up": False,
        "moon_text": "Moon down",
        "moon_pct": 20,
        "moon_phase": "Waxing",
        "seeing_code": 3,
        "seeing_text": "Very good",
        "transparency_code": 3,
        "transparency_text": "Very good",
        "wind_speed_text": "Light",
        "temp2m_c": 12,
        "precip_text": "None",
    }


def test_seeing_dialog_day_blocks_do_not_mix_local_calendar_dates(monkeypatch):
    monkeypatch.setenv(
        "QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen")
    )
    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtCore")

    from fzastro_ai.ui.seeing_dialog import SeeingDialog

    monkeypatch.setattr(SeeingDialog, "refresh_forecast", lambda self: None)
    monkeypatch.setattr(SeeingDialog, "_ensure_auto_sky_quality", lambda self: None)

    application = qt_widgets.QApplication.instance() or qt_widgets.QApplication([])
    dialog = SeeingDialog(location={"lat": 37.98, "lon": 23.72, "name": "Test site"})

    try:
        rows = [
            _row("2026-06-16T21:00:00+03:00", score=55, astro_dark=True),
            _row("2026-06-17T00:00:00+03:00", score=65, astro_dark=True),
            _row("2026-06-17T03:00:00+03:00", score=70, astro_dark=True),
            _row("2026-06-17T21:00:00+03:00", score=60, astro_dark=True),
            _row("2026-06-18T00:00:00+03:00", score=58, astro_dark=True),
        ]

        blocks = dialog._build_24h_blocks(rows)

        assert [
            datetime.fromisoformat(block["start_iso"]).date().isoformat()
            for block in blocks
        ] == [
            "2026-06-16",
            "2026-06-17",
            "2026-06-18",
        ]
        assert [len(block["rows"]) for block in blocks] == [1, 3, 1]
        for block in blocks:
            selected_day = datetime.fromisoformat(block["start_iso"]).date()
            row_dates = {
                datetime.fromisoformat(row["local_iso"]).date() for row in block["rows"]
            }
            assert row_dates == {selected_day}
    finally:
        dialog.deleteLater()
        application.processEvents()


def test_seeing_dialog_selected_day_table_is_chronological(monkeypatch):
    monkeypatch.setenv(
        "QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen")
    )
    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtCore")

    from fzastro_ai.ui.seeing_dialog import SeeingDialog

    monkeypatch.setattr(SeeingDialog, "refresh_forecast", lambda self: None)
    monkeypatch.setattr(SeeingDialog, "_ensure_auto_sky_quality", lambda self: None)

    application = qt_widgets.QApplication.instance() or qt_widgets.QApplication([])
    dialog = SeeingDialog(location={"lat": 37.98, "lon": 23.72, "name": "Test site"})

    try:
        rows = [
            _row("2026-06-18T05:00:00+03:00", score=55, astro_dark=False),
            _row("2026-06-18T23:00:00+03:00", score=85, astro_dark=True),
            _row("2026-06-18T11:00:00+03:00", score=55, astro_dark=False),
            _row("2026-06-18T14:00:00+03:00", score=55, astro_dark=False),
            _row("2026-06-18T20:00:00+03:00", score=25, astro_dark=True),
            _row("2026-06-18T17:00:00+03:00", score=25, astro_dark=False),
        ]

        dialog._populate_table(rows)

        labels = [
            dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())
        ]
        assert labels == [
            "2026-06-18 05:00",
            "2026-06-18 11:00",
            "2026-06-18 14:00",
            "2026-06-18 17:00",
            "2026-06-18 20:00",
            "2026-06-18 23:00",
        ]
    finally:
        dialog.deleteLater()
        application.processEvents()

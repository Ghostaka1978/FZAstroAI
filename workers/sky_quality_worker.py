from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal

from ..astro_tools.sky_quality_provider import fetch_lightpollutionmap_app_sky_quality


class SkyQualityFetchWorker(QThread):
    """Background SQM/Bortle fetcher for selected SITE coordinates."""

    finished_quality = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(self, location: dict[str, Any], *, timeout: float = 25.0, parent=None):
        super().__init__(parent)
        self.location = dict(location or {})
        self.timeout = float(timeout)

    def run(self):  # noqa: D401 - Qt worker entry point
        import time

        started = time.perf_counter()
        try:
            lat = float(self.location.get("lat"))
            lon = float(self.location.get("lon"))
            result = fetch_lightpollutionmap_app_sky_quality(
                lat, lon, timeout=self.timeout
            )
            self.finished_quality.emit(
                result.to_dict(), time.perf_counter() - started, True
            )
        except Exception as exc:
            self.error_received.emit(str(exc))
            self.finished_quality.emit({}, time.perf_counter() - started, False)

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..astro_tools.seeing_data import (
    fetch_7timer_astro_forecast,
    fetch_latest_geosatellite_image,
)
from ..logging_utils import log_exception


class SeeingSatelliteWorker(QThread):
    """Fetch latest geostationary satellite imagery away from the UI thread."""

    finished_satellite = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(self, area: str = "europe", image_type: str = "infrared"):
        super().__init__()
        self.area = str(area or "europe")
        self.image_type = str(image_type or "infrared")
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self) -> bool:
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        start = time.perf_counter()
        try:
            if self.should_stop():
                return
            result = fetch_latest_geosatellite_image(
                area=self.area, image_type=self.image_type
            )
            if self.should_stop():
                return
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_satellite.emit(result, elapsed, True)
        except Exception as error:
            if self.should_stop():
                return
            log_exception("SeeingSatelliteWorker.run", error)
            self.error_received.emit(str(error))


class SeeingWorker(QThread):
    """Fetch astronomy seeing/transparency data away from the UI thread."""

    finished_seeing = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(
        self,
        location: dict[str, Any],
        altitude_correction: Any = "auto",
        provider: Any = "7timer_hybrid",
    ):
        super().__init__()
        self.location = dict(location or {})
        self.altitude_correction = altitude_correction
        self.provider = provider
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self) -> bool:
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        start = time.perf_counter()
        try:
            if self.should_stop():
                return
            result = fetch_7timer_astro_forecast(
                lat=self.location.get("lat"),
                lon=self.location.get("lon"),
                elev=self.location.get("elev", 0.0),
                tz=self.location.get("tz", "UTC"),
                altitude_correction=self.altitude_correction,
                provider=self.provider,
            )
            if self.should_stop():
                return
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_seeing.emit(result, elapsed, True)
        except Exception as error:
            if self.should_stop():
                return
            log_exception("SeeingWorker.run", error)
            self.error_received.emit(str(error))

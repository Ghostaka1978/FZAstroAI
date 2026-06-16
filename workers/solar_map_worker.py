from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from ..astro_tools.solar_map_data import load_solar_map_snapshot
from ..logging_utils import log_exception


class SolarMapWorker(QThread):
    """Calculate native solar-map data away from the Qt UI thread."""

    finished_solar_map = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(self, dt_iso: str | None = None):
        super().__init__()
        self.dt_iso = str(dt_iso or "").strip()
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
            result = load_solar_map_snapshot(self.dt_iso)
            if self.should_stop():
                return
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_solar_map.emit(result, elapsed, True)
        except Exception as error:
            if self.should_stop():
                return
            log_exception("SolarMapWorker.run", error)
            self.error_received.emit(str(error))

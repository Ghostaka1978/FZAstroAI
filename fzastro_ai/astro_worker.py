from __future__ import annotations

import time
from typing import Any, Dict

from PySide6.QtCore import QThread, Signal

from .astro_tools import engine as astro_engine
from .logging_utils import log_exception, log_warning


class AstroWorker(QThread):
    """Run migrated FZASTRO astronomy tools away from the UI thread."""

    finished_astro = Signal(str, str, list, float, bool)
    stopped_astro = Signal(float)
    error_received = Signal(str)

    def __init__(self, mode: str, params: Dict[str, Any] | None = None):
        super().__init__()
        self.mode = str(mode or "").strip().lower()
        self.params = dict(params or {})
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self) -> bool:
        return bool(self.stop_requested or self.isInterruptionRequested())

    def _emit_stopped(self, start: float):
        elapsed = max(0.0, time.perf_counter() - start)
        self.stopped_astro.emit(elapsed)

    def run(self):
        start = time.perf_counter()

        try:
            if self.should_stop():
                self._emit_stopped(start)
                return

            with astro_engine.astro_cancel_context(self.should_stop):
                if self.mode == "lookup":
                    result = astro_engine.lookup_object(
                        self.params.get("query", ""),
                        with_image=bool(self.params.get("with_image", True)),
                        fov_deg=float(self.params.get("fov_deg", 2.337)),
                        width=int(self.params.get("width", 1536)),
                        height=int(self.params.get("height", 1024)),
                        rotation_angle=float(self.params.get("rotation_angle", 270.0)),
                        camera_name=self.params.get("camera_name"),
                        focal_mm=self.params.get("focal_mm"),
                        fov_y_deg=self.params.get("fov_y_deg"),
                    )
                elif self.mode == "image":
                    result = astro_engine.fetch_sky_image(
                        ra=float(self.params.get("ra")),
                        dec=float(self.params.get("dec")),
                        fov_deg=float(self.params.get("fov_deg", 2.337)),
                        width=int(self.params.get("width", 1536)),
                        height=int(self.params.get("height", 1024)),
                        survey=self.params.get("survey"),
                        rotation_angle=float(self.params.get("rotation_angle", 270.0)),
                    )
                elif self.mode in {"forecast", "see", "weather", "meteo"}:
                    result = astro_engine.observing_forecast(
                        lat=float(self.params.get("lat")),
                        lon=float(self.params.get("lon")),
                        elev=float(self.params.get("elev", 0.0)),
                        tz=self.params.get("tz"),
                        nights=int(self.params.get("nights", 4)),
                    )
                elif self.mode == "targets":
                    result = astro_engine.best_targets(
                        lat=float(self.params.get("lat")),
                        lon=float(self.params.get("lon")),
                        elev=float(self.params.get("elev", 0.0)),
                        date=self.params.get("date"),
                        limit=int(self.params.get("limit", 10)),
                        min_alt=float(self.params.get("min_alt", 45.0)),
                        tz=self.params.get("tz"),
                    )
                elif self.mode == "solar":
                    result = astro_engine.solar_system_map(
                        dt=self.params.get("dt"),
                        size=int(self.params.get("size", 2000)),
                        orbits=str(self.params.get("orbits", "yes")),
                        dist=str(self.params.get("dist", "no")),
                    )
                else:
                    raise ValueError(f"Unknown astro tool mode: {self.mode}")

            if self.should_stop():
                self._emit_stopped(start)
                return

            elapsed = max(0.0, time.perf_counter() - start)

            if not bool(result.success):
                log_warning(
                    "AstroWorker finished with failed result",
                    f"mode={self.mode}; elapsed={elapsed:.2f}s; text={str(result.text or '')[:4000]}",
                )

            self.finished_astro.emit(
                result.text,
                result.source,
                list(result.files or []),
                elapsed,
                bool(result.success),
            )
        except astro_engine.AstroToolCancelled:
            self._emit_stopped(start)
        except Exception as error:
            if self.should_stop():
                self._emit_stopped(start)
                return

            log_exception("AstroWorker.run", error)
            self.error_received.emit(str(error))

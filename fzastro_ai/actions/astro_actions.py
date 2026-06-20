from __future__ import annotations

import json
import re
import time
import uuid
from typing import Dict, Tuple, Union

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox

try:
    import shiboken6
except Exception:  # pragma: no cover - defensive for alternate PySide builds
    shiboken6 = None

from ..workers import AstroWorker
from ..config import APP_DIR
from ..json_store import atomic_write_json
from ..logging_utils import log_exception, log_warning, log_debug
from ..ui.astro_location_dialog import choose_astro_location
from ..ui.sun_now_dialog import show_sun_now_dialog
from ..ui.solar_map_dialog import show_solar_map_dialog
from ..ui.seeing_dialog import show_seeing_dialog
from ..ui.targets_dialog import show_targets_dialog
from ..ui.astro_lookup_dialog import (
    DEFAULT_ASTRO_IMAGING,
    astro_imaging_summary,
    choose_astro_imaging_settings,
    normalise_astro_imaging,
    show_astro_lookup_dialog,
)

# Keep the original FZASTRO web-app defaults from python/app.py.
DEFAULT_ASTRO_LOCATION = {
    "lat": 50.24590,
    "lon": 8.49230,
    "elev": 660.0,
    "tz": "Europe/Berlin",
}

ASTRO_LOCATION_FILE = APP_DIR / "astro_location.json"
ASTRO_IMAGING_FILE = APP_DIR / "astro_imaging.json"

# Astro outputs are often tall (lookup details + sky image, seeing tables,
# target tables, and solar maps). Do not force the main chat to the bottom
# for these tools; keep the user exactly where they were and let them scroll
# manually. Normal chat/news/python auto-scroll behavior is unchanged.
ASTRO_PRESERVE_CHAT_SCROLL_MODES = {
    "lookup",
    "forecast",
    "see",
    "weather",
    "meteo",
    "targets",
    "solar",
}


def prepare_content(text, files):
    from ..app import prepare_content as _prepare_content

    return _prepare_content(text, files)


class AstroActionsMixin:
    def _normalise_astro_location(self, value) -> Dict[str, Union[float, str]]:
        data = dict(value or {})
        lat = max(
            -90.0, min(90.0, float(data.get("lat", DEFAULT_ASTRO_LOCATION["lat"])))
        )
        lon = max(
            -180.0, min(180.0, float(data.get("lon", DEFAULT_ASTRO_LOCATION["lon"])))
        )
        elev = max(
            -500.0, min(9000.0, float(data.get("elev", DEFAULT_ASTRO_LOCATION["elev"])))
        )
        tz = (
            str(data.get("tz") or DEFAULT_ASTRO_LOCATION.get("tz") or "UTC").strip()
            or "UTC"
        )
        location: Dict[str, Union[float, str]] = {
            "lat": lat,
            "lon": lon,
            "elev": elev,
            "tz": tz,
        }
        source_text = str(data.get("sky_quality_source") or "")
        discard_stale_auto_sky = "auto estimate" in source_text.lower()
        sqm_keys = (
            "sqm",
            "sqm_mag",
            "sqm_mag_arcsec2",
            "mag_arcsec2",
            "sky_quality",
            "sky_quality_mag",
        )
        bortle_keys = ("bortle", "bortle_class", "bortleClass")
        if not discard_stale_auto_sky:
            for key in sqm_keys:
                try:
                    value = data.get(key)
                    if value is None or str(value).strip() == "":
                        continue
                    sqm = float(value)
                    if 0.0 < sqm <= 23.5:
                        location["sqm"] = round(sqm, 2)
                        break
                except Exception:
                    continue
            for key in bortle_keys:
                try:
                    value = data.get(key)
                    if value is None or str(value).strip() == "":
                        continue
                    bortle = int(round(float(value)))
                    if 1 <= bortle <= 9:
                        location["bortle"] = float(bortle)
                        break
                except Exception:
                    continue
        if not discard_stale_auto_sky:
            for key in (
                "bortle_precise",
                "sky_quality_fetched_at",
                "sky_quality_source_url",
            ):
                value = data.get(key)
                if value is not None and str(value).strip() != "":
                    location[key] = value
        if source_text and ("sqm" in location or "bortle" in location):
            location["sky_quality_source"] = source_text
        return location

    def get_current_astro_location(self) -> Dict[str, Union[float, str]]:
        cached = getattr(self, "astro_location", None)

        if cached is not None:
            return self._normalise_astro_location(cached)

        location = dict(DEFAULT_ASTRO_LOCATION)

        try:
            if ASTRO_LOCATION_FILE.exists():
                with ASTRO_LOCATION_FILE.open("r", encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict):
                    location.update(stored)
        except Exception as exc:
            log_warning("AstroActions.get_current_astro_location load failed", exc)

        self.astro_location = self._normalise_astro_location(location)
        return dict(self.astro_location)

    def save_current_astro_location(self):
        try:
            atomic_write_json(ASTRO_LOCATION_FILE, self.get_current_astro_location())
        except Exception as exc:
            log_warning("AstroActions.save_current_astro_location failed", exc)

    def set_current_astro_location(self, location):
        self.astro_location = self._normalise_astro_location(location)
        self.save_current_astro_location()
        self.refresh_astro_location_label()

    def astro_location_summary(self) -> str:
        loc = self.get_current_astro_location()
        return f"{float(loc['lat']):.5f}, {float(loc['lon']):.5f} · {float(loc['elev']):.0f} m"

    def refresh_astro_location_label(self):
        label = getattr(self, "astro_location_label", None)
        if label is None:
            return

        if shiboken6 is not None:
            try:
                if not shiboken6.isValid(label):
                    self.astro_location_label = None
                    return
            except Exception:
                pass

        try:
            label.setText(self.astro_location_summary())
            label.setToolTip("Current observing site used by SEEING and TARGETS")
        except RuntimeError as exc:
            # QLabel was already destroyed by Qt. Clear the Python reference
            # silently; logging this every refresh made normal shutdown look like
            # an error and could lead to repeated access to a dead C++ object.
            try:
                self.astro_location_label = None
            except Exception:
                pass
            if "already deleted" not in str(exc).lower():
                log_warning("AstroActions.refresh_astro_location_label failed", exc)

    def get_current_astro_imaging(self) -> Dict[str, Union[float, str]]:
        cached = getattr(self, "astro_imaging", None)
        if cached is not None:
            return normalise_astro_imaging(cached)

        imaging = dict(DEFAULT_ASTRO_IMAGING)
        try:
            if ASTRO_IMAGING_FILE.exists():
                with ASTRO_IMAGING_FILE.open("r", encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict):
                    imaging.update(stored)
        except Exception as exc:
            log_warning("AstroActions.get_current_astro_imaging load failed", exc)

        self.astro_imaging = normalise_astro_imaging(imaging)
        return dict(self.astro_imaging)

    def save_current_astro_imaging(self):
        try:
            atomic_write_json(ASTRO_IMAGING_FILE, self.get_current_astro_imaging())
        except Exception as exc:
            log_warning("AstroActions.save_current_astro_imaging failed", exc)

    def set_current_astro_imaging(self, imaging):
        self.astro_imaging = normalise_astro_imaging(imaging)
        self.save_current_astro_imaging()
        self.refresh_astro_imaging_label()

    def astro_imaging_summary(self) -> str:
        return astro_imaging_summary(self.get_current_astro_imaging())

    def refresh_astro_imaging_label(self):
        label = getattr(self, "astro_imaging_label", None)
        if label is not None:
            try:
                label.setText(self.astro_imaging_summary())
                label.setToolTip(
                    "Current camera preset, focal length, FOV, and rotation used by LOOKUP"
                )
            except RuntimeError as exc:
                log_warning("AstroActions.refresh_astro_imaging_label stale label", exc)
                try:
                    self.astro_imaging_label = None
                except Exception:
                    pass

    def _astro_preserve_main_chat_scroll(self, mode: str) -> bool:
        return str(mode or "").strip().lower() in ASTRO_PRESERVE_CHAT_SCROLL_MODES

    def _capture_main_chat_scroll_value(self):
        try:
            return int(self.chat_scroll.verticalScrollBar().value())
        except Exception:
            return None

    def _restore_main_chat_scroll_value(self, value):
        if value is None:
            return

        try:
            bar = self.chat_scroll.verticalScrollBar()
            target = max(bar.minimum(), min(int(value), bar.maximum()))
            bar.setValue(target)
        except Exception:
            pass

    def _queue_main_chat_scroll_restore(self, value):
        if value is None:
            return

        self._restore_main_chat_scroll_value(value)
        QTimer.singleShot(0, lambda v=value: self._restore_main_chat_scroll_value(v))
        QTimer.singleShot(40, lambda v=value: self._restore_main_chat_scroll_value(v))

    def open_astro_imaging_dialog(self):
        if self._astro_busy():
            return

        selected = choose_astro_imaging_settings(self, self.get_current_astro_imaging())
        if not selected:
            return

        self.set_current_astro_imaging(selected)
        self.stats_label.setText(f"Astro imaging set: {self.astro_imaging_summary()}")

    def _astro_lookup_params_from_imaging(
        self, query: str, imaging: dict | None = None
    ) -> Dict[str, object]:
        data = normalise_astro_imaging(imaging or self.get_current_astro_imaging())
        return {
            "query": str(query or "").strip(),
            "with_image": True,
            "fov_deg": float(data["fov_deg"]),
            "width": int(data["width"]),
            "height": int(data["height"]),
            "rotation_angle": float(data["rotation_angle"]),
            "camera_preset": str(data["preset"]),
            "camera_name": str(data["preset_name"]),
            "preset_label": str(data["preset_label"]),
            "focal_mm": float(data["focal_mm"]),
            "fov_y_deg": float(data["fov_y_deg"]),
        }

    def open_astro_location_dialog(self):
        if self._astro_busy():
            return

        selected = choose_astro_location(self, self.get_current_astro_location())

        if not selected:
            return

        self.set_current_astro_location(selected)
        self.stats_label.setText(f"Astro location set: {self.astro_location_summary()}")

    def _astro_busy(self):
        for attr_name in (
            "worker",
            "python_worker",
            "decision_worker",
            "web_worker",
            "astro_worker",
        ):
            worker = getattr(self, attr_name, None)

            if worker is not None and worker.isRunning():
                return True

        return False

    def _parse_location_text(self, text: str) -> Dict[str, Union[float, str]]:
        clean = str(text or "").strip()
        values = [part.strip() for part in re.split(r"[,;\s]+", clean) if part.strip()]

        if len(values) < 2:
            raise ValueError("Use: latitude, longitude, optional elevation")

        lat = float(values[0])
        lon = float(values[1])
        elev = float(values[2]) if len(values) >= 3 else DEFAULT_ASTRO_LOCATION["elev"]
        return {"lat": lat, "lon": lon, "elev": elev}

    def open_astro_lookup_dialog(self, query: str = "M31", *, auto_run: bool = False):
        if self._astro_busy():
            return

        if isinstance(query, bool):
            query = "M31"
        clean_query = str(query or "M31").strip() or "M31"
        result = show_astro_lookup_dialog(
            self,
            self.get_current_astro_imaging(),
            query=clean_query,
            auto_run=auto_run,
        )

        status = "opened" if hasattr(result, "setParent") else "closed"
        self.stats_label.setText(
            f"LOOKUP {status}: {clean_query} - {self.astro_imaging_summary()}"
        )

    def open_astro_targets_dialog(self):
        if self._astro_busy():
            return

        result = show_targets_dialog(self, self.get_current_astro_location())
        status = "opened" if hasattr(result, "setParent") else "closed"
        self.stats_label.setText(f"TARGETS {status}")

    def open_sun_now_dialog(self):
        if self._astro_busy():
            return

        result = show_sun_now_dialog(self)
        status = "opened" if hasattr(result, "setParent") else "closed"
        self.stats_label.setText(f"SUN NOW {status}")

    def open_astro_forecast_dialog(self):
        if self._astro_busy():
            return

        result = show_seeing_dialog(self, self.get_current_astro_location())
        status = "opened" if hasattr(result, "setParent") else "closed"
        self.stats_label.setText(f"SEEING {status}")

    def open_solar_system_map(self):
        if self._astro_busy():
            return

        result = show_solar_map_dialog(self)
        status = "opened" if hasattr(result, "setParent") else "closed"
        self.stats_label.setText(f"SOLAR MAP {status}")

    def is_astro_direct_request(self, text):
        clean = str(text or "").strip().casefold()
        return clean.startswith(
            (
                "/astro",
                "/astro-image",
                "/targets",
                "/darksky",
                "/see",
                "/weather",
                "/meteo",
                "/night-forecast",
                "/solar-map",
                "/solarmap",
            )
        )

    def parse_astro_direct_request(self, text) -> Tuple[str, Dict[str, object], str]:
        raw = str(text or "").strip()
        clean = raw.casefold()

        if clean.startswith("/targets"):
            params = self.get_current_astro_location()
            params.update({"limit": 10, "min_alt": 45.0})
            return (
                "targets",
                params,
                f"Best astrophotography targets tonight · {self.astro_location_summary()}",
            )

        if clean.startswith(
            ("/darksky", "/see", "/weather", "/meteo", "/night-forecast")
        ):
            params = self.get_current_astro_location()
            params.update({"nights": 4})
            return (
                "forecast",
                params,
                f"True astronomy seeing · {self.astro_location_summary()}",
            )

        if clean.startswith(("/solar-map", "/solarmap")):
            return (
                "solar",
                {"size": 2000, "orbits": "yes", "dist": "no"},
                "Solar-system map",
            )

        if clean.startswith("/astro-image"):
            rest = re.sub(r"^/astro-image\s*", "", raw, flags=re.IGNORECASE).strip()
            parts = [part for part in re.split(r"[,\s]+", rest) if part]

            if len(parts) < 2:
                raise ValueError("Use /astro-image RA DEC [FOV_DEG]")

            imaging = self.get_current_astro_imaging()
            params = {
                "ra": float(parts[0]),
                "dec": float(parts[1]),
                "fov_deg": (
                    float(parts[2]) if len(parts) >= 3 else float(imaging["fov_deg"])
                ),
                "width": int(imaging["width"]),
                "height": int(imaging["height"]),
                "rotation_angle": float(imaging["rotation_angle"]),
            }
            return (
                "image",
                params,
                f"Sky image: RA {params['ra']}, Dec {params['dec']} · {self.astro_imaging_summary()}",
            )

        rest = re.sub(r"^/astro\s*", "", raw, flags=re.IGNORECASE).strip()

        if not rest:
            raise ValueError(
                "Use /astro followed by an object name, for example /astro M31"
            )

        return (
            "lookup",
            self._astro_lookup_params_from_imaging(rest),
            f"Astro lookup: {rest} · {self.astro_imaging_summary()}",
        )

    def execute_astro_direct_request(self, text):
        try:
            mode, params, display_text = self.parse_astro_direct_request(text)
        except Exception as exc:
            log_warning("AstroActions.execute_astro_direct_request parse failed", exc)
            QMessageBox.warning(self, "Astro command", str(exc))
            return False

        if mode == "solar":
            self.open_solar_system_map()
            return True

        if mode == "targets":
            self.open_astro_targets_dialog()
            return True

        if mode in {"forecast", "see", "weather", "meteo"}:
            self.open_astro_forecast_dialog()
            return True

        self.start_astro_tool(mode, params, display_text)
        return True

    def start_astro_tool(self, mode, params, display_text):
        if self._astro_busy():
            return

        display_text = str(display_text or "Astro tool").strip()
        user_message_id = uuid.uuid4().hex
        preserve_chat_scroll = self._astro_preserve_main_chat_scroll(mode)
        start_scroll_value = (
            self._capture_main_chat_scroll_value() if preserve_chat_scroll else None
        )

        self.messages.append(
            {
                "id": user_message_id,
                "role": "user",
                "content": prepare_content(display_text, []),
                "files": [],
            }
        )
        self.add_message_widget(":ME:", display_text, [], message_id=user_message_id)

        if preserve_chat_scroll:
            self.chat_container.adjustSize()
            self.chat_container.updateGeometry()
            self._queue_main_chat_scroll_restore(start_scroll_value)

        self.request_start_time = time.perf_counter()
        self.generation_timer.start(100)
        self.set_busy_ui_state()
        self.stats_label.setText(f"Running astro tool: {display_text}... • 0.00s")

        worker = AstroWorker(mode, params)
        self.astro_worker = worker
        worker.finished_astro.connect(self.finish_astro_tool)
        worker.stopped_astro.connect(self.handle_astro_stopped)
        worker.error_received.connect(self.handle_astro_error)
        worker.finished.connect(self.handle_astro_worker_finished)
        worker.start()

    def stop_astro_tool(self):
        if self.stop_in_progress:
            return

        self.stop_in_progress = True
        self.set_action_button_mode("stopping")
        self.stats_label.setText("Stopping astro tool...")

        astro_worker = getattr(self, "astro_worker", None)

        if astro_worker is not None and astro_worker.isRunning():
            try:
                astro_worker.stop()
            except Exception as exc:
                log_exception("FZAstroAI.stop_astro_tool", exc)
                self.set_idle_ui_state("Astro tool stop failed")

    def handle_astro_stopped(self, elapsed):
        self.generation_timer.stop()
        # Do not clear self.astro_worker here. This slot is emitted from inside
        # AstroWorker.run() before the underlying QThread has fully finished.
        # Clearing the last Python reference too early can destroy a still-running
        # QThread and crash the app with 0xC0000409 on Windows.
        assistant_message_id = uuid.uuid4().hex
        text = "**Astro tool stopped**\n\nStopped by user."
        source_tags = ["app", "astro_api"]
        mode = getattr(getattr(self, "astro_worker", None), "mode", "")
        preserve_chat_scroll = self._astro_preserve_main_chat_scroll(mode)
        stop_scroll_value = (
            self._capture_main_chat_scroll_value() if preserve_chat_scroll else None
        )

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": text,
                "files": [],
                "news_sources": {},
                "response_time": float(elapsed),
                "source_tags": source_tags,
            }
        )

        self.add_message_widget(
            ":AI: ",
            text,
            files=[],
            message_id=assistant_message_id,
            response_time=float(elapsed),
            source_tags=source_tags,
        )

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        if preserve_chat_scroll:
            self._queue_main_chat_scroll_restore(stop_scroll_value)
        else:
            self.force_scroll_to_bottom()
            QTimer.singleShot(0, self.force_scroll_to_bottom)
        self.set_idle_ui_state(f"Astro tool stopped • {float(elapsed):.2f}s")

    def finish_astro_tool(self, text, source, files, elapsed, success):
        self.generation_timer.stop()
        # Keep self.astro_worker alive until AstroWorker.finished fires.
        # finished_astro is a custom signal emitted before QThread teardown.
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""

        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "astro_api"]
        text = str(text or "").strip() or "Astro tool finished with no output."
        mode = getattr(getattr(self, "astro_worker", None), "mode", "")
        preserve_chat_scroll = self._astro_preserve_main_chat_scroll(mode)
        finish_scroll_value = (
            self._capture_main_chat_scroll_value() if preserve_chat_scroll else None
        )

        if not success:
            log_warning(
                "AstroActions.finish_astro_tool failed result", str(text)[:4000]
            )
            text = "**Astro tool problem**\n\n" + text

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": text,
                "files": list(files or []),
                "news_sources": {},
                "response_time": float(elapsed),
                "source_tags": source_tags,
            }
        )

        self.add_message_widget(
            ":AI: ",
            text,
            files=list(files or []),
            message_id=assistant_message_id,
            response_time=float(elapsed),
            source_tags=source_tags,
        )

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        if preserve_chat_scroll:
            self._queue_main_chat_scroll_restore(finish_scroll_value)
        else:
            self.force_scroll_to_bottom()
            QTimer.singleShot(0, self.force_scroll_to_bottom)
        self.set_idle_ui_state(f"Astro tool finished • {float(elapsed):.2f}s")

    def handle_astro_error(self, error):
        log_warning("AstroActions.handle_astro_error", error)
        self.generation_timer.stop()
        # Keep self.astro_worker alive until AstroWorker.finished fires.
        self.set_idle_ui_state("Astro tool failed")
        QMessageBox.warning(self, "Astro tool error", str(error))

    def handle_astro_worker_finished(self):
        """Release the AstroWorker only after QThread has really finished.

        This prevents the Windows 0xC0000409 crash caused by destroying a
        QThread while it is still unwinding after emitting a custom result/error
        signal.
        """
        worker = self.sender()

        if worker is getattr(self, "astro_worker", None):
            self.astro_worker = None

        if worker is not None:
            try:
                worker.deleteLater()
            except Exception as exc:
                log_debug(
                    "AstroActions.handle_astro_worker_finished deleteLater skipped", exc
                )

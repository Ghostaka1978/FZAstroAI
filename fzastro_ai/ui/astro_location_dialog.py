from __future__ import annotations

import json
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # WebEngine is optional in source/dev installs.
    QWebEngineView = None

from ..workers.sky_quality_worker import SkyQualityFetchWorker


_LOCATION_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map { height: 100%; width: 100%; margin: 0; padding: 0; background: #0b0d10; }
  .leaflet-control-attribution { font-size: 10px; }
</style>
</head>
<body>
<div id="map"></div>
<script>
  let selectedLat = __LAT__;
  let selectedLon = __LON__;
  let map = L.map('map', { zoomControl: true }).setView([selectedLat, selectedLon], 7);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap'
  }).addTo(map);
  let marker = L.marker([selectedLat, selectedLon], { draggable: true }).addTo(map);

  function setLocation(lat, lon, zoomTo) {
      selectedLat = Number(lat);
      selectedLon = Number(lon);
      marker.setLatLng([selectedLat, selectedLon]);
      if (zoomTo) { map.setView([selectedLat, selectedLon], map.getZoom()); }
  }

  map.on('click', function(e) {
      setLocation(e.latlng.lat, e.latlng.lng, false);
  });

  marker.on('dragend', function(e) {
      let pos = marker.getLatLng();
      selectedLat = pos.lat;
      selectedLon = pos.lng;
  });

  window.__setLocation = function(lat, lon) {
      setLocation(lat, lon, true);
      return true;
  };

  window.__getLocation = function() {
      return JSON.stringify({ lat: selectedLat, lon: selectedLon });
  };
</script>
</body>
</html>
"""


class AstroLocationDialog(QDialog):
    """Location selector for migrated FZASTRO tools.

    Uses a Leaflet/OpenStreetMap picker when Qt WebEngine is available and
    falls back to reliable native coordinate fields otherwise.
    """

    @staticmethod
    def _first_float(
        data: Dict[str, object], keys: tuple[str, ...], default: float = 0.0
    ) -> float:
        for key in keys:
            try:
                value = data.get(key)
                if value is None or value == "":
                    continue
                return float(value)
            except Exception:
                continue
        return float(default)

    def __init__(self, parent=None, current: Optional[Dict[str, object]] = None):
        super().__init__(parent)
        current = dict(current or {})
        self.selected_location: Optional[Dict[str, object]] = None
        self._web_view = None
        self.sky_quality_worker: SkyQualityFetchWorker | None = None
        self._last_sky_quality_lookup: Dict[str, object] = {}

        self.setWindowTitle("Astro Location")
        self.resize(980, 720)
        self.setMinimumSize(720, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("Select your observing location")
        title.setObjectName("header")
        root.addWidget(title)

        hint = QLabel(
            "Click the map or drag the marker. Use the external map buttons to read SQM/Bortle, then enter the values here."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.lat_spin = self._make_spin(
            -90.0, 90.0, float(current.get("lat", 50.24590)), 6
        )
        self.lon_spin = self._make_spin(
            -180.0, 180.0, float(current.get("lon", 8.49230)), 6
        )
        self.elev_spin = self._make_spin(
            -500.0,
            9000.0,
            self._first_float(
                current,
                ("elev", "elevation", "elevation_m", "altitude", "altitude_m"),
                660.0,
            ),
            1,
        )
        self.sqm_spin = self._make_spin(
            0.0,
            23.5,
            self._first_float(
                current,
                (
                    "sqm",
                    "sqm_mag",
                    "sqm_mag_arcsec2",
                    "mag_arcsec2",
                    "sky_quality",
                    "sky_quality_mag",
                ),
                0.0,
            ),
            2,
        )
        self.sqm_spin.setSpecialValueText("Not set")
        self.bortle_spin = self._make_spin(
            0.0,
            9.0,
            self._first_float(current, ("bortle", "bortle_class", "bortleClass"), 0.0),
            0,
        )
        self.bortle_spin.setSpecialValueText("Not set")
        current_source = str(current.get("sky_quality_source") or "Manual")
        if "auto estimate" in current_source.lower():
            self.sqm_spin.setValue(0.0)
            self.bortle_spin.setValue(0.0)
            current_source = "Manual"
        self.source_combo = QComboBox(self)
        self.source_combo.addItems(
            [
                "Manual",
                "LightPollutionMap.app auto",
                "LightPollutionMap",
                "DarkSiteFinder",
                "Measured SQM",
                "Other",
            ]
        )
        source_index = self.source_combo.findText(current_source)
        if source_index < 0:
            source_index = self.source_combo.findText("Other")
        self.source_combo.setCurrentIndex(max(0, source_index))
        self.tz_value = (
            str(current.get("tz") or "Europe/Berlin").strip() or "Europe/Berlin"
        )

        if QWebEngineView is not None:
            try:
                self._web_view = QWebEngineView(self)
                self._web_view.setMinimumHeight(390)
                self._web_view.setHtml(
                    _LOCATION_HTML.replace(
                        "__LAT__", f"{self.lat_spin.value():.8f}"
                    ).replace("__LON__", f"{self.lon_spin.value():.8f}")
                )
                root.addWidget(self._web_view, 1)
            except Exception:
                self._web_view = None

        if self._web_view is None:
            fallback = QLabel(
                "Map picker is not available in this build. Enter latitude, longitude and elevation manually."
            )
            fallback.setWordWrap(True)
            fallback.setStyleSheet(
                "color: #d9a441; padding: 10px; border: 1px solid #3d3320; border-radius: 8px;"
            )
            root.addWidget(fallback, 1)

        form_holder = QWidget(self)
        form = QFormLayout(form_holder)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addRow("Latitude (°)", self.lat_spin)
        form.addRow("Longitude (°)", self.lon_spin)
        form.addRow("Elevation (m)", self.elev_spin)
        form.addRow("SQM mag/arcsec²", self.sqm_spin)
        form.addRow("Bortle class", self.bortle_spin)
        form.addRow("SQM/Bortle source", self.source_combo)
        form.addRow("Timezone", QLabel(self.tz_value))
        root.addWidget(form_holder)

        self.sky_quality_status = QLabel(
            "SQM/Bortle can be fetched automatically from LightPollutionMap.app or entered manually."
        )
        self.sky_quality_status.setObjectName("subtitle")
        self.sky_quality_status.setWordWrap(True)
        root.addWidget(self.sky_quality_status)

        helper_row = QHBoxLayout()
        helper_row.setSpacing(8)
        self.center_map_button = QPushButton("Center Map on Fields")
        self.center_map_button.setCursor(Qt.PointingHandCursor)
        self.center_map_button.clicked.connect(self._center_map_on_fields)
        self.center_map_button.setEnabled(self._web_view is not None)
        helper_row.addWidget(self.center_map_button)

        self.auto_sky_button = QPushButton("Auto fetch SQM/Bortle")
        self.auto_sky_button.setCursor(Qt.PointingHandCursor)
        self.auto_sky_button.clicked.connect(self._auto_fetch_sky_quality)
        helper_row.addWidget(self.auto_sky_button)

        self.light_pollution_button = QPushButton("Open LightPollutionMap")
        self.light_pollution_button.setCursor(Qt.PointingHandCursor)
        self.light_pollution_button.clicked.connect(self._open_light_pollution_map)
        helper_row.addWidget(self.light_pollution_button)

        self.dark_site_button = QPushButton("Open DarkSiteFinder")
        self.dark_site_button.setCursor(Qt.PointingHandCursor)
        self.dark_site_button.clicked.connect(self._open_dark_site_finder)
        helper_row.addWidget(self.dark_site_button)

        self.copy_coords_button = QPushButton("Copy coordinates")
        self.copy_coords_button.setCursor(Qt.PointingHandCursor)
        self.copy_coords_button.clicked.connect(self._copy_coordinates)
        helper_row.addWidget(self.copy_coords_button)

        self.clear_sky_button = QPushButton("Clear SQM/Bortle")
        self.clear_sky_button.setCursor(Qt.PointingHandCursor)
        self.clear_sky_button.clicked.connect(self._clear_sky_quality)
        helper_row.addWidget(self.clear_sky_button)

        helper_row.addStretch(1)
        root.addLayout(helper_row)

        if (
            float(self.sqm_spin.value()) <= 0.0
            and float(self.bortle_spin.value()) <= 0.0
        ):
            QTimer.singleShot(650, self._auto_fetch_sky_quality_silent)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_button = QPushButton("Use Location")
        self.use_button.setCursor(Qt.PointingHandCursor)
        buttons.addButton(self.use_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.use_button.clicked.connect(self._accept_selected_location)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _make_spin(
        self, minimum: float, maximum: float, value: float, decimals: int
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(0.0001 if decimals >= 4 else 10.0)
        spin.setValue(value)
        spin.setMinimumHeight(34)
        return spin

    def _current_map_coordinates(self, callback):
        if self._web_view is None:
            callback(float(self.lat_spin.value()), float(self.lon_spin.value()))
            return

        def finish(value):
            lat = float(self.lat_spin.value())
            lon = float(self.lon_spin.value())
            try:
                data = json.loads(value or "{}") if isinstance(value, str) else {}
                lat = float(data.get("lat", lat))
                lon = float(data.get("lon", lon))
                self.lat_spin.setValue(lat)
                self.lon_spin.setValue(lon)
            except Exception:
                pass
            callback(lat, lon)

        try:
            self._web_view.page().runJavaScript(
                "window.__getLocation && window.__getLocation()",
                finish,
            )
        except Exception:
            callback(float(self.lat_spin.value()), float(self.lon_spin.value()))

    @staticmethod
    def _light_pollution_map_url(lat: float, lon: float) -> str:
        return (
            "https://www.lightpollutionmap.info/"
            f"#zoom=8.00&lat={float(lat):.6f}&lon={float(lon):.6f}"
            "&layers=B0FFFFFFFTFFFFFFFFFFF"
        )

    @staticmethod
    def _dark_site_finder_url(lat: float, lon: float) -> str:
        return (
            f"https://darksitefinder.com/map/?i=/%234/{float(lat):.5f}/{float(lon):.5f}"
        )

    def _open_external_url(self, url: str, source: str):
        self.source_combo.setCurrentText(source)
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as exc:
            QMessageBox.warning(
                self, "Astro location", f"Could not open external map:\n\n{exc}"
            )

    def _open_light_pollution_map(self):
        self._current_map_coordinates(
            lambda lat, lon: self._open_external_url(
                self._light_pollution_map_url(lat, lon), "LightPollutionMap"
            )
        )

    def _open_dark_site_finder(self):
        self._current_map_coordinates(
            lambda lat, lon: self._open_external_url(
                self._dark_site_finder_url(lat, lon), "DarkSiteFinder"
            )
        )

    def _copy_coordinates(self):
        def copy(lat: float, lon: float):
            text = f"{lat:.6f}, {lon:.6f}"
            try:
                QApplication.clipboard().setText(text)
                QMessageBox.information(
                    self, "Astro location", f"Copied coordinates:\n\n{text}"
                )
            except Exception as exc:
                QMessageBox.warning(
                    self, "Astro location", f"Could not copy coordinates:\n\n{exc}"
                )

        self._current_map_coordinates(copy)

    def _clear_sky_quality(self):
        self.sqm_spin.setValue(0.0)
        self.bortle_spin.setValue(0.0)
        self.source_combo.setCurrentText("Manual")
        self._last_sky_quality_lookup = {}
        self.sky_quality_status.setText(
            "SQM/Bortle cleared. Use auto fetch or enter measured/map values manually."
        )

    def _set_sky_fetch_enabled(self, enabled: bool):
        for button in (
            self.auto_sky_button,
            self.light_pollution_button,
            self.dark_site_button,
            self.copy_coords_button,
            self.clear_sky_button,
            self.use_button,
        ):
            try:
                button.setEnabled(bool(enabled))
            except Exception:
                pass

    def _auto_fetch_sky_quality_silent(self):
        if float(self.sqm_spin.value()) > 0.0 or float(self.bortle_spin.value()) > 0.0:
            return
        self._auto_fetch_sky_quality(show_errors=False)

    def _auto_fetch_sky_quality(self, show_errors: bool = True):
        if self.sky_quality_worker is not None and self.sky_quality_worker.isRunning():
            return

        def start(lat: float, lon: float):
            location = {
                "lat": float(lat),
                "lon": float(lon),
                "elev": float(self.elev_spin.value()),
                "tz": self.tz_value,
            }
            self.sky_quality_status.setText(
                "Fetching SQM/Bortle from LightPollutionMap.app…"
            )
            self._set_sky_fetch_enabled(False)
            worker = SkyQualityFetchWorker(location, timeout=28.0, parent=self)
            worker._show_errors = bool(show_errors)  # type: ignore[attr-defined]
            self.sky_quality_worker = worker
            worker.finished_quality.connect(self._handle_sky_quality_finished)
            worker.error_received.connect(self._handle_sky_quality_error)
            worker.finished.connect(self._handle_sky_quality_worker_finished)
            worker.start()

        self._current_map_coordinates(start)

    def _handle_sky_quality_finished(
        self, result: Dict[str, object], elapsed: float, success: bool
    ):
        if (
            success
            and isinstance(result, dict)
            and (result.get("sqm") or result.get("bortle"))
        ):
            try:
                if result.get("sqm") is not None:
                    self.sqm_spin.setValue(float(result.get("sqm")))
                if result.get("bortle") is not None:
                    self.bortle_spin.setValue(float(result.get("bortle")))
                source = str(
                    result.get("sky_quality_source")
                    or result.get("source")
                    or "LightPollutionMap.app auto"
                )
                if self.source_combo.findText(source) < 0:
                    self.source_combo.addItem(source)
                self.source_combo.setCurrentText(source)
                self._last_sky_quality_lookup = dict(result)
                self.sky_quality_status.setText(
                    f"Auto-fetched SQM/Bortle in {float(elapsed):.1f}s from LightPollutionMap.app. Save the location to keep these values."
                )
            except Exception as exc:
                self.sky_quality_status.setText(
                    f"Auto SQM/Bortle fetch returned data but could not apply it: {exc}"
                )
        elif self.sky_quality_worker is not None:
            self.sky_quality_status.setText(
                "Auto SQM/Bortle fetch did not return values. You can still enter values manually."
            )
        self._set_sky_fetch_enabled(True)

    def _handle_sky_quality_error(self, error: str):
        show_errors = (
            bool(getattr(self.sky_quality_worker, "_show_errors", True))
            if self.sky_quality_worker is not None
            else True
        )
        message = f"Auto SQM/Bortle fetch failed: {error}"
        self.sky_quality_status.setText(message)
        if show_errors:
            QMessageBox.warning(self, "Astro location", message)

    def _handle_sky_quality_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "sky_quality_worker", None):
            self.sky_quality_worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_sky_fetch_enabled(True)

    def _manual_location(self) -> Dict[str, object]:
        location: Dict[str, object] = {
            "lat": float(self.lat_spin.value()),
            "lon": float(self.lon_spin.value()),
            "elev": float(self.elev_spin.value()),
            "tz": self.tz_value,
        }
        if float(self.sqm_spin.value()) > 0.0:
            location["sqm"] = round(float(self.sqm_spin.value()), 2)
        if float(self.bortle_spin.value()) > 0.0:
            location["bortle"] = int(round(float(self.bortle_spin.value())))
        if location.get("sqm") or location.get("bortle"):
            source = (
                str(self.source_combo.currentText() or "Manual").strip() or "Manual"
            )
            location["sky_quality_source"] = source
            lookup = dict(self._last_sky_quality_lookup or {})
            if lookup:
                for key in (
                    "bortle_precise",
                    "sky_quality_fetched_at",
                    "sky_quality_source_url",
                ):
                    if lookup.get(key) is not None:
                        location[key] = lookup.get(key)
        return location

    def _center_map_on_fields(self):
        if self._web_view is None:
            return
        js = f"window.__setLocation({self.lat_spin.value():.8f}, {self.lon_spin.value():.8f})"
        try:
            self._web_view.page().runJavaScript(js)
        except Exception as exc:
            QMessageBox.warning(
                self, "Astro location", f"Could not update the map marker:\n\n{exc}"
            )

    def _accept_selected_location(self):
        if self._web_view is None:
            self.selected_location = self._manual_location()
            self.accept()
            return

        try:
            self._web_view.page().runJavaScript(
                "window.__getLocation && window.__getLocation()",
                self._finish_js_location,
            )
        except Exception:
            self.selected_location = self._manual_location()
            self.accept()

    def _finish_js_location(self, value):
        try:
            data = json.loads(value or "{}") if isinstance(value, str) else {}
            lat = float(data.get("lat", self.lat_spin.value()))
            lon = float(data.get("lon", self.lon_spin.value()))
            self.lat_spin.setValue(lat)
            self.lon_spin.setValue(lon)
        except Exception:
            pass

        self.selected_location = self._manual_location()
        self.accept()

    def reject(self):
        worker = getattr(self, "sky_quality_worker", None)
        if worker is not None and worker.isRunning():
            self.sky_quality_status.setText("Waiting for SQM/Bortle fetch to finish…")
            self._set_sky_fetch_enabled(False)
            return
        super().reject()

    def closeEvent(self, event):  # noqa: N802 - Qt override
        worker = getattr(self, "sky_quality_worker", None)
        if worker is not None and worker.isRunning():
            self.sky_quality_status.setText("Waiting for SQM/Bortle fetch to finish…")
            self._set_sky_fetch_enabled(False)
            event.ignore()
            return
        super().closeEvent(event)


def choose_astro_location(
    parent=None, current: Optional[Dict[str, object]] = None
) -> Optional[Dict[str, object]]:
    dialog = AstroLocationDialog(parent, current=current)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_location or {}
    return None

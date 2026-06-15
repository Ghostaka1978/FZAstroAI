from __future__ import annotations

import json
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

    def __init__(self, parent=None, current: Optional[Dict[str, object]] = None):
        super().__init__(parent)
        current = dict(current or {})
        self.selected_location: Optional[Dict[str, object]] = None
        self._web_view = None

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
            "Click the map or drag the marker. If the map engine is unavailable, use the coordinate fields below."
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
            -500.0, 9000.0, float(current.get("elev", 660.0)), 1
        )
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
        form.addRow("Timezone", QLabel(self.tz_value))
        root.addWidget(form_holder)

        helper_row = QHBoxLayout()
        helper_row.setSpacing(8)
        self.center_map_button = QPushButton("Center Map on Fields")
        self.center_map_button.setCursor(Qt.PointingHandCursor)
        self.center_map_button.clicked.connect(self._center_map_on_fields)
        self.center_map_button.setEnabled(self._web_view is not None)
        helper_row.addWidget(self.center_map_button)
        helper_row.addStretch(1)
        root.addLayout(helper_row)

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

    def _manual_location(self) -> Dict[str, object]:
        return {
            "lat": float(self.lat_spin.value()),
            "lon": float(self.lon_spin.value()),
            "elev": float(self.elev_spin.value()),
            "tz": self.tz_value,
        }

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


def choose_astro_location(
    parent=None, current: Optional[Dict[str, object]] = None
) -> Optional[Dict[str, object]]:
    dialog = AstroLocationDialog(parent, current=current)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_location or {}
    return None

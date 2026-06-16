from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import QDateTime, Qt, QTimer, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from ..workers.solar_map_worker import SolarMapWorker
from .window_utils import apply_window_defaults


AU_TO_SCENE = 44.0
MODE_LIMITS_AU = {
    "inner": 2.2,
    "outer": 32.0,
    "full": 32.0,
}
MODE_LABELS = {
    "inner": "Inner system",
    "outer": "Outer system",
    "full": "Full system",
}
INNER_BODIES = {"Mercury", "Venus", "Earth", "Mars"}
OUTER_BODIES = {"Jupiter", "Saturn", "Uranus", "Neptune"}


class SolarMapGraphicsView(QGraphicsView):
    """Zoomable/pannable 2D solar-map viewport."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("solarMapView")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = 1.18 if delta > 0 else 1 / 1.18
        self.scale(factor, factor)
        event.accept()

    def fit_map(self):
        scene = self.scene()
        if scene is None:
            return
        rect = scene.itemsBoundingRect().adjusted(-80, -80, 80, 80)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.fitInView(rect, Qt.KeepAspectRatio)


class SolarPlanetItem(QGraphicsEllipseItem):
    """Clickable planet marker."""

    def __init__(self, body: dict[str, Any], rect: QRectF, on_selected):
        super().__init__(rect)
        self.body = dict(body)
        self._on_selected = on_selected
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setToolTip(_body_tooltip(self.body))

    def mousePressEvent(self, event):
        if callable(self._on_selected):
            self._on_selected(str(self.body.get("name") or ""))
        super().mousePressEvent(event)


class SolarMapDialog(QDialog):
    """Self-contained native 2D solar-system map."""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_window_defaults(self)
        self.solar_worker: SolarMapWorker | None = None
        self._snapshot: dict[str, Any] = {}
        self._planet_items: dict[str, SolarPlanetItem] = {}
        self._label_items: list[QGraphicsTextItem] = []
        self._close_after_worker = False
        self._last_elapsed = 0.0

        self.setObjectName("solarMapDialog")
        self.setWindowTitle("SOLAR MAP")
        self.resize(1260, 780)
        self.setMinimumSize(980, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(9)

        header_card = QFrame()
        header_card.setObjectName("astroLookupHeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(2)
        title = QLabel("SOLAR MAP")
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Native 2D interactive solar-system map using live Skyfield planet positions."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        controls_card = QFrame()
        controls_card.setObjectName("astroLookupSettingsCard")
        controls = QGridLayout(controls_card)
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(6)

        mode_caption = QLabel("View")
        mode_caption.setObjectName("toolbarCaption")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("astroLookupCombo")
        self.mode_combo.addItem("Full system", "full")
        self.mode_combo.addItem("Inner system", "inner")
        self.mode_combo.addItem("Outer system", "outer")

        time_caption = QLabel("UTC time")
        time_caption.setObjectName("toolbarCaption")
        self.time_edit = QDateTimeEdit(QDateTime.currentDateTimeUtc())
        self.time_edit.setObjectName("astroLookupCombo")
        self.time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss 'UTC'")
        self.time_edit.setCalendarPopup(True)

        self.orbits_check = QCheckBox("Orbits")
        self.orbits_check.setChecked(True)
        self.labels_check = QCheckBox("Labels")
        self.labels_check.setChecked(True)
        self.grid_check = QCheckBox("AU grid")
        self.grid_check.setChecked(True)

        self.now_button = QPushButton("Now")
        self.now_button.clicked.connect(self.set_now_and_refresh)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryActionButton")
        self.refresh_button.clicked.connect(self.refresh_map)
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_map)

        controls.addWidget(mode_caption, 0, 0)
        controls.addWidget(time_caption, 0, 1)
        controls.addWidget(self.mode_combo, 1, 0)
        controls.addWidget(self.time_edit, 1, 1)
        controls.addWidget(self.orbits_check, 1, 2)
        controls.addWidget(self.labels_check, 1, 3)
        controls.addWidget(self.grid_check, 1, 4)
        controls.addWidget(self.now_button, 1, 5)
        controls.addWidget(self.refresh_button, 1, 6)
        controls.addWidget(self.fit_button, 1, 7)
        controls.setColumnStretch(1, 2)

        result_card = QFrame()
        result_card.setObjectName("astroLookupResultCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)

        result_header = QHBoxLayout()
        result_title = QLabel("Interactive map")
        result_title.setObjectName("astroLookupSectionTitle")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        result_header.addWidget(result_title)
        result_header.addStretch(1)
        result_header.addWidget(self.status_label)
        result_layout.addLayout(result_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("astroLookupProgress")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        result_layout.addWidget(self.progress_bar)

        split = QHBoxLayout()
        split.setSpacing(10)

        map_panel = QFrame()
        map_panel.setObjectName("astroLookupImagePanel")
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(9, 9, 9, 9)
        map_layout.setSpacing(6)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor("#05080d")))
        self.map_view = SolarMapGraphicsView()
        self.map_view.setScene(self.scene)
        self.map_view.setMinimumSize(650, 470)
        self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        hint = QLabel("Mouse wheel zoom · drag to pan · click a planet for details")
        hint.setObjectName("astroLookupStatusLabel")
        map_layout.addWidget(self.map_view, 1)
        map_layout.addWidget(hint)
        split.addWidget(map_panel, 4)

        side_panel = QFrame()
        side_panel.setObjectName("astroLookupImagePanel")
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(9, 9, 9, 9)
        side_layout.setSpacing(6)
        info_title = QLabel("Planet data")
        info_title.setObjectName("astroLookupSectionTitle")
        self.info_browser = QTextBrowser()
        self.info_browser.setObjectName("astroLookupResultBrowser")
        self.info_browser.setMinimumWidth(325)
        self.info_browser.setMaximumHeight(190)
        self.info_browser.setHtml(self._summary_html({}))

        self.body_table = QTableWidget(0, 5)
        self.body_table.setObjectName("solarMapBodyTable")
        self.body_table.setHorizontalHeaderLabels(
            ["Body", "Sun AU", "Earth AU", "Lon°", "Z AU"]
        )
        self.body_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.body_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.body_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.body_table.verticalHeader().setVisible(False)
        self.body_table.horizontalHeader().setStretchLastSection(True)
        self.body_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            self.body_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.body_table.itemSelectionChanged.connect(self.handle_table_selection)

        side_layout.addWidget(info_title)
        side_layout.addWidget(self.info_browser)
        side_layout.addWidget(self.body_table, 1)
        split.addWidget(side_panel, 2)
        result_layout.addLayout(split, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.Close)
        button_row.rejected.connect(self.reject)

        root.addWidget(header_card)
        root.addWidget(controls_card)
        root.addWidget(result_card, 1)
        root.addWidget(button_row)

        self.mode_combo.currentIndexChanged.connect(self.redraw_scene)
        self.orbits_check.toggled.connect(self.redraw_scene)
        self.labels_check.toggled.connect(self.redraw_scene)
        self.grid_check.toggled.connect(self.redraw_scene)
        QTimer.singleShot(80, self.refresh_map)

    def selected_mode(self) -> str:
        mode = str(self.mode_combo.currentData() or "full").strip().lower()
        return mode if mode in MODE_LIMITS_AU else "full"

    def selected_dt_iso(self) -> str:
        qdt = self.time_edit.dateTime().toUTC()
        text = qdt.toString(Qt.ISODate)
        if text.endswith("Z"):
            return text
        if "+" in text:
            return text
        return f"{text}Z"

    def set_now_and_refresh(self):
        self.time_edit.setDateTime(QDateTime.currentDateTimeUtc())
        self.refresh_map()

    def refresh_map(self):
        if self.solar_worker is not None and self.solar_worker.isRunning():
            return
        self.status_label.setText("Calculating…")
        self.progress_bar.show()
        self._set_controls_enabled(False)
        self.info_browser.setHtml(
            self._summary_html({"status_note": "Calculating live planet positions…"})
        )

        worker = SolarMapWorker(self.selected_dt_iso())
        self.solar_worker = worker
        worker.finished_solar_map.connect(self.handle_solar_map_finished)
        worker.error_received.connect(self.handle_solar_map_error)
        worker.finished.connect(self.handle_solar_worker_finished)
        worker.start()

    def handle_solar_map_finished(self, snapshot: dict, elapsed: float, success: bool):
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self._snapshot = dict(snapshot or {})
        self._last_elapsed = float(elapsed)
        self.status_label.setText(f"Loaded • {float(elapsed):.2f}s")
        self.populate_table()
        self.redraw_scene()
        self.info_browser.setHtml(self._summary_html(self._snapshot))

    def handle_solar_map_error(self, error: str):
        if self._close_after_worker:
            self.progress_bar.hide()
            self.status_label.setText("Closed")
            return
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self.status_label.setText("Failed")
        self.info_browser.setHtml(
            self._summary_html(
                {"status_note": f"Solar Map calculation failed: {error}"}
            )
        )
        QMessageBox.warning(self, "SOLAR MAP", str(error))

    def filtered_bodies(self) -> list[dict[str, Any]]:
        bodies = [
            dict(body)
            for body in self._snapshot.get("bodies", [])
            if isinstance(body, dict)
        ]
        mode = self.selected_mode()
        if mode == "inner":
            return [body for body in bodies if body.get("name") in INNER_BODIES]
        if mode == "outer":
            return [body for body in bodies if body.get("name") in OUTER_BODIES]
        return bodies

    def populate_table(self):
        bodies = self.filtered_bodies()
        self.body_table.blockSignals(True)
        self.body_table.setRowCount(0)
        for body in bodies:
            row = self.body_table.rowCount()
            self.body_table.insertRow(row)
            values = [
                str(body.get("name") or ""),
                _fmt_float(body.get("sun_distance_au"), 3),
                _fmt_float(body.get("earth_distance_au"), 3),
                _fmt_float(body.get("ecliptic_lon_deg"), 1),
                _fmt_float(body.get("z_au"), 3),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.body_table.setItem(row, column, item)
        self.body_table.blockSignals(False)
        if bodies:
            self.body_table.selectRow(0)
            self.select_body(str(bodies[0].get("name") or ""), update_table=False)

    def redraw_scene(self):
        if not self._snapshot:
            return
        self.scene.clear()
        self._planet_items = {}
        self._label_items = []
        mode = self.selected_mode()
        limit = MODE_LIMITS_AU[mode]
        scene_limit = limit * AU_TO_SCENE
        self.scene.setSceneRect(
            -scene_limit, -scene_limit, scene_limit * 2, scene_limit * 2
        )

        if self.grid_check.isChecked():
            self._draw_grid(limit)
        if self.orbits_check.isChecked():
            self._draw_orbits()
        self._draw_sun()
        self._draw_bodies()
        QTimer.singleShot(0, self.map_view.fit_map)
        self.populate_table()

    def _draw_grid(self, limit_au: float):
        if limit_au <= 3.0:
            rings = [0.5, 1.0, 1.5, 2.0]
        else:
            rings = [5.0, 10.0, 20.0, 30.0]
        pen = QPen(QColor(95, 122, 150, 65))
        pen.setWidthF(1.0)
        text_pen = QColor(126, 148, 172, 170)
        for ring in rings:
            radius = ring * AU_TO_SCENE
            self.scene.addEllipse(-radius, -radius, radius * 2, radius * 2, pen)
            label = self.scene.addText(f"{ring:g} AU")
            label.setDefaultTextColor(text_pen)
            label.setScale(0.72)
            label.setPos(radius + 5, -12)
        axis_pen = QPen(QColor(120, 145, 170, 55))
        axis_pen.setWidthF(1.0)
        extent = limit_au * AU_TO_SCENE
        self.scene.addLine(-extent, 0, extent, 0, axis_pen)
        self.scene.addLine(0, -extent, 0, extent, axis_pen)

    def _draw_orbits(self):
        visible_names = {str(body.get("name") or "") for body in self.filtered_bodies()}
        orbits = self._snapshot.get("orbits", {})
        if not isinstance(orbits, dict):
            return
        pen = QPen(QColor(255, 255, 255, 70))
        pen.setWidthF(1.15)
        for name in visible_names:
            points = orbits.get(name) or []
            if not points:
                continue
            path = QPainterPath()
            first = True
            for point in points:
                try:
                    x = float(point[0]) * AU_TO_SCENE
                    y = -float(point[1]) * AU_TO_SCENE
                except Exception:
                    continue
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(1)
            self.scene.addItem(item)

    def _draw_sun(self):
        radius = 16.0
        pen = QPen(QColor("#fff3b0"))
        pen.setWidthF(1.4)
        item = self.scene.addEllipse(
            -radius, -radius, radius * 2, radius * 2, pen, QBrush(QColor("#ffd34d"))
        )
        item.setToolTip("Sun · heliocentric map center")
        item.setZValue(5)
        if self.labels_check.isChecked():
            label = self.scene.addText("Sun")
            label.setDefaultTextColor(QColor("#fff3b0"))
            label.setScale(0.86)
            label.setPos(radius + 7, -radius - 4)
            label.setZValue(7)
            self._label_items.append(label)

    def _draw_bodies(self):
        for body in self.filtered_bodies():
            try:
                x = float(body.get("x_au", 0.0)) * AU_TO_SCENE
                y = -float(body.get("y_au", 0.0)) * AU_TO_SCENE
                radius = max(4.8, float(body.get("marker_radius", 6.0)))
            except Exception:
                continue
            color = QColor(str(body.get("color") or "#dce7f4"))
            pen = QPen(QColor("#ffffff"))
            pen.setWidthF(1.2)
            item = SolarPlanetItem(
                body,
                QRectF(x - radius, y - radius, radius * 2, radius * 2),
                self.select_body,
            )
            item.setPen(pen)
            item.setBrush(QBrush(color))
            item.setZValue(6)
            self.scene.addItem(item)
            name = str(body.get("name") or "")
            self._planet_items[name] = item
            if self.labels_check.isChecked():
                label = self.scene.addText(name)
                label.setDefaultTextColor(QColor("#eef5ff"))
                label.setScale(0.78)
                label.setPos(x + radius + 6, y - radius - 4)
                label.setZValue(7)
                self._label_items.append(label)

    def select_body(self, name: str, update_table: bool = True):
        if not name:
            return
        for item_name, item in self._planet_items.items():
            pen = QPen(QColor("#ffffff"))
            pen.setWidthF(2.8 if item_name == name else 1.2)
            if item_name == name:
                pen.setColor(QColor("#9bd2ff"))
                item.setZValue(8)
            else:
                item.setZValue(6)
            item.setPen(pen)
        if update_table:
            for row in range(self.body_table.rowCount()):
                item = self.body_table.item(row, 0)
                if item and item.text() == name:
                    self.body_table.blockSignals(True)
                    self.body_table.selectRow(row)
                    self.body_table.blockSignals(False)
                    break
        body = self._body_by_name(name)
        if body:
            self.info_browser.setHtml(
                self._summary_html(self._snapshot, selected_body=body)
            )

    def _body_by_name(self, name: str) -> dict[str, Any]:
        for body in self._snapshot.get("bodies", []):
            if isinstance(body, dict) and body.get("name") == name:
                return dict(body)
        return {}

    def handle_table_selection(self):
        selected = self.body_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        item = self.body_table.item(row, 0)
        if item:
            self.select_body(item.text(), update_table=False)

    def fit_map(self):
        self.map_view.fit_map()

    def _summary_html(
        self, snapshot: dict[str, Any], selected_body: dict[str, Any] | None = None
    ) -> str:
        status = html.escape(str(snapshot.get("status_note") or "Ready."))
        timestamp = html.escape(str(snapshot.get("timestamp_utc") or "—"))
        generated = html.escape(str(snapshot.get("generated_at_utc") or "—"))
        source = html.escape(str(snapshot.get("source") or "Skyfield ephemerides"))
        mode = html.escape(MODE_LABELS.get(self.selected_mode(), "Full system"))
        elapsed = html.escape(
            f"{self._last_elapsed:.2f}s" if self._last_elapsed else "—"
        )

        if selected_body:
            body_html = f"""
            <h2>{html.escape(str(selected_body.get('name') or 'Selected body'))}</h2>
            <p><span class="k">Sun distance:</span> <span class="v">{html.escape(_fmt_float(selected_body.get('sun_distance_au'), 4))} AU</span></p>
            <p><span class="k">Earth distance:</span> <span class="v">{html.escape(_fmt_float(selected_body.get('earth_distance_au'), 4))} AU</span></p>
            <p><span class="k">Light time:</span> <span class="v">{html.escape(_fmt_float(selected_body.get('earth_light_minutes'), 1))} minutes</span></p>
            <p><span class="k">Ecliptic lon/lat:</span> <span class="v">{html.escape(_fmt_float(selected_body.get('ecliptic_lon_deg'), 2))}° / {html.escape(_fmt_float(selected_body.get('ecliptic_lat_deg'), 2))}°</span></p>
            <p><span class="k">X/Y/Z:</span> <span class="v">{html.escape(_fmt_float(selected_body.get('x_au'), 4))}, {html.escape(_fmt_float(selected_body.get('y_au'), 4))}, {html.escape(_fmt_float(selected_body.get('z_au'), 4))} AU</span></p>
            """
        else:
            body_html = f'<p class="note">{status}</p>'

        return f"""
        <html>
        <head>
            <style>
                body {{ background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; line-height:1.28; margin:0; }}
                h1 {{ color:#ffffff; font-size:16px; margin:0 0 6px 0; }}
                h2 {{ color:#eef3f8; font-size:12px; margin:8px 0 4px 0; }}
                p {{ margin:3px 0; }}
                .pill {{ display:inline-block; color:#cfe4ff; background:#111a23; border:1px solid #2a3948; border-radius:8px; padding:3px 6px; font-weight:800; margin:0 0 6px 0; }}
                .k {{ color:#93a8bd; font-size:10px; font-weight:850; }}
                .v {{ color:#f3f7fc; font-weight:650; }}
                .note {{ color:#aeb9c5; }}
            </style>
        </head>
        <body>
            <h1>Native Solar Map</h1>
            <div class="pill">{mode}</div>
            {body_html}
            <h2>Snapshot</h2>
            <p><span class="k">UTC time:</span> <span class="v">{timestamp}</span></p>
            <p><span class="k">Generated:</span> <span class="v">{generated}</span></p>
            <p><span class="k">Source:</span> <span class="v">{source}</span></p>
            <p><span class="k">Load time:</span> <span class="v">{elapsed}</span></p>
        </body>
        </html>
        """

    def _set_controls_enabled(self, enabled: bool):
        for widget in (
            self.mode_combo,
            self.time_edit,
            self.orbits_check,
            self.labels_check,
            self.grid_check,
            self.now_button,
            self.refresh_button,
            self.fit_button,
        ):
            widget.setEnabled(bool(enabled))

    def handle_solar_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "solar_worker", None):
            self.solar_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_after_worker:
            QTimer.singleShot(0, self.reject)

    def _stop_worker(self) -> bool:
        worker = getattr(self, "solar_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.stop()
            except Exception:
                pass
            return True
        return False

    def reject(self):
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self._set_controls_enabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self._set_controls_enabled(False)
            event.ignore()
            return
        super().closeEvent(event)


def _fmt_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{int(digits)}f}"
    except Exception:
        return "—"


def _body_tooltip(body: dict[str, Any]) -> str:
    name = str(body.get("name") or "Planet")
    return (
        f"{name}\n"
        f"Sun distance: {_fmt_float(body.get('sun_distance_au'), 4)} AU\n"
        f"Earth distance: {_fmt_float(body.get('earth_distance_au'), 4)} AU\n"
        f"Ecliptic longitude: {_fmt_float(body.get('ecliptic_lon_deg'), 2)}°"
    )


def show_solar_map_dialog(parent=None):
    dialog = SolarMapDialog(parent)
    return dialog.exec()

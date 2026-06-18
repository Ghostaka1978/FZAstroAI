from __future__ import annotations

import csv
import html
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from ..astro_tools.target_catalog import (
    catalog_stats,
    import_openngc_csv,
    object_type_choices,
)
from ..logging_utils import log_exception, log_warning
from ..nina.imaging_plan import calculate_framing_details
from ..workers.astro_worker import AstroWorker
from ..workers.targets_worker import TargetsWorker
from .astro_location_dialog import choose_astro_location
from .astro_lookup_dialog import (
    CAMERA_PRESETS,
    AstroLookupDialog,
    FloatingSkyPreviewDialog,
    _legacy_lookup_to_html,
    _looks_like_html,
    _lookup_params_from_dialog_data,
    _markdown_to_html,
    normalise_astro_imaging,
)
from .window_utils import apply_window_defaults


class TargetsDialog(QDialog):
    """Native TARGETS planner window."""

    COLUMNS = [
        "Grade",
        "Name",
        "Type",
        "Const",
        "Mag",
        "Size",
        "Max Alt",
        "Airmass",
        "Visible",
        "Best Local",
    ]

    def __init__(self, parent=None, location: dict[str, Any] | None = None):
        super().__init__(parent)
        apply_window_defaults(self)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.location = dict(location or {})
        self.targets_worker: TargetsWorker | None = None
        self.inline_lookup_worker: AstroWorker | None = None
        self._close_after_worker = False
        self._inline_lookup_serial = 0
        self._inline_lookup_pixmap: QPixmap | None = None
        self._inline_lookup_image_path: Path | None = None
        self._inline_lookup_html: str = ""
        self._floating_preview_dialog: FloatingSkyPreviewDialog | None = None
        self._last_result: dict[str, Any] = {}
        self._last_picks: list[dict[str, Any]] = []

        self.setObjectName("targetsDialog")
        self.setWindowTitle("TARGETS")
        self.resize(1220, 760)
        self.setMinimumSize(980, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        root.addWidget(self._build_controls())
        root.addWidget(self._build_results(), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.refresh_catalog_status()
        QTimer.singleShot(80, self.run_planner)

    def _build_header(self) -> QFrame:
        card = QFrame()
        card.setObjectName("astroLookupHeaderCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)

        title = QLabel("TARGETS")
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Best astrophotography targets for the selected night, scored by "
            "altitude, airmass, visibility, timing, and object size."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return card

    def _build_controls(self) -> QFrame:
        card = QFrame()
        card.setObjectName("astroLookupSettingsCard")
        layout = QGridLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        self.site_label = QLabel(self._site_summary())
        self.site_label.setObjectName("toolbarCaption")
        self.site_label.setToolTip("Current observing site")
        self.change_site_button = QPushButton("Change site")
        self.change_site_button.clicked.connect(self.change_site)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setObjectName("astroLookupCombo")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        self.min_alt_spin = QDoubleSpinBox()
        self.min_alt_spin.setObjectName("astroLookupCombo")
        self.min_alt_spin.setRange(5.0, 85.0)
        self.min_alt_spin.setDecimals(0)
        self.min_alt_spin.setSingleStep(5.0)
        self.min_alt_spin.setSuffix("°")
        self.min_alt_spin.setValue(45.0)

        self.limit_spin = QSpinBox()
        self.limit_spin.setObjectName("astroLookupCombo")
        self.limit_spin.setRange(5, 200)
        self.limit_spin.setSingleStep(5)
        self.limit_spin.setValue(25)

        self.catalog_combo = QComboBox()
        self.catalog_combo.setObjectName("astroLookupCombo")
        self.catalog_combo.addItem("Auto local catalog", "auto")
        self.catalog_combo.addItem("Curated built-in only", "builtin")
        self.catalog_combo.addItem("OpenNGC only", "openngc")

        self.type_combo = QComboBox()
        self.type_combo.setObjectName("astroLookupCombo")
        for choice in object_type_choices():
            self.type_combo.addItem(choice, choice)

        self.min_size_spin = QDoubleSpinBox()
        self.min_size_spin.setObjectName("astroLookupCombo")
        self.min_size_spin.setRange(0.0, 240.0)
        self.min_size_spin.setDecimals(1)
        self.min_size_spin.setSingleStep(1.0)
        self.min_size_spin.setSuffix("′")
        self.min_size_spin.setValue(0.0)

        self.use_mag_check = QCheckBox("Max mag")
        self.max_mag_spin = QDoubleSpinBox()
        self.max_mag_spin.setObjectName("astroLookupCombo")
        self.max_mag_spin.setRange(-5.0, 20.0)
        self.max_mag_spin.setDecimals(1)
        self.max_mag_spin.setSingleStep(0.5)
        self.max_mag_spin.setValue(13.0)
        self.max_mag_spin.setEnabled(False)
        self.use_mag_check.toggled.connect(self.max_mag_spin.setEnabled)
        self.use_mag_check.setChecked(True)

        self.run_button = QPushButton("Run Planner")
        self.run_button.setObjectName("primaryActionButton")
        self.run_button.clicked.connect(self.run_planner)

        self.import_button = QPushButton("Import OpenNGC CSV")
        self.import_button.clicked.connect(self.import_openngc)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        self.export_button.setEnabled(False)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(1)
        title = QLabel("TARGETS")
        title.setObjectName("astroLookupSectionTitle")
        subtitle = QLabel("Best targets for the selected night.")
        subtitle.setObjectName("toolbarCaption")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        def add_field(row: int, column: int, caption: str, widget, span: int = 1):
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            label = QLabel(caption)
            label.setObjectName("toolbarCaption")
            cell.addWidget(label)
            cell.addWidget(widget)
            layout.addLayout(cell, row, column, 1, span)

        def add_button(row: int, column: int, widget, span: int = 1):
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            spacer = QLabel("")
            spacer.setObjectName("toolbarCaption")
            cell.addWidget(spacer)
            cell.addWidget(widget)
            layout.addLayout(cell, row, column, 1, span)

        layout.addLayout(title_box, 0, 0, 1, 2)
        add_field(0, 2, "Site", self.site_label, 3)
        add_button(0, 5, self.change_site_button)
        add_field(0, 6, "Date", self.date_edit)
        add_field(0, 7, "Min alt", self.min_alt_spin)
        add_field(0, 8, "Limit", self.limit_spin)
        add_button(0, 9, self.run_button)

        add_field(1, 0, "Catalog", self.catalog_combo, 3)
        add_field(1, 3, "Type", self.type_combo, 2)
        add_field(1, 5, "Min size", self.min_size_spin)

        mag_cell = QVBoxLayout()
        mag_cell.setContentsMargins(0, 0, 0, 0)
        mag_cell.setSpacing(2)
        self.use_mag_check.setObjectName("toolbarCaption")
        mag_cell.addWidget(self.use_mag_check)
        mag_cell.addWidget(self.max_mag_spin)
        layout.addLayout(mag_cell, 1, 6)

        add_button(1, 7, self.import_button, 2)
        add_button(1, 9, self.export_button)

        layout.setColumnStretch(2, 2)
        layout.setColumnStretch(3, 2)
        layout.setColumnStretch(4, 2)
        return card

    def _build_results(self) -> QFrame:
        card = QFrame()
        card.setObjectName("astroLookupResultCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Planner results")
        title.setObjectName("astroLookupSectionTitle")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("astroLookupProgress")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        split = QHBoxLayout()
        split.setSpacing(10)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("astroLookupTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.update_details_from_selection)
        split.addWidget(self.table, 3)

        side = QVBoxLayout()
        side.setSpacing(6)
        self.summary_label = QLabel("Catalog loading…")
        self.summary_label.setObjectName("toolbarCaption")
        self.summary_label.setWordWrap(True)
        side.addWidget(self.summary_label)

        self.details_browser = QTextBrowser(card)
        self.details_browser.setObjectName("astroLookupResultBrowser")
        self.details_browser.setOpenExternalLinks(False)
        self.details_browser.setVisible(False)
        self.details_browser.setMaximumHeight(0)
        self.details_browser.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.details_browser.setHtml(
            self._status_html("Run the planner", "Targets will appear here.")
        )

        self.inline_lookup_status_label = QLabel("Idle", card)
        self.inline_lookup_status_label.setObjectName("astroLookupStatusLabel")
        self.inline_lookup_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.inline_lookup_status_label.setVisible(False)

        self.inline_lookup_browser = QTextBrowser(card)
        self.inline_lookup_browser.setObjectName("astroLookupResultBrowser")
        self.inline_lookup_browser.setOpenExternalLinks(True)
        self.inline_lookup_browser.setVisible(False)
        self.inline_lookup_browser.setMaximumHeight(0)
        self.inline_lookup_browser.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Ignored
        )
        self.inline_lookup_browser.setHtml(
            self._status_html(
                "Select a target",
                "LOOKUP details and sky preview will load here.",
            )
        )

        image_panel = QFrame()
        image_panel.setObjectName("astroLookupImagePanel")
        image_panel.setMinimumHeight(300)
        image_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(8, 8, 8, 8)
        image_layout.setSpacing(6)
        image_header = QHBoxLayout()
        image_header.setContentsMargins(0, 0, 0, 0)
        image_title = QLabel("Sky preview")
        image_title.setObjectName("astroLookupSectionTitle")
        self.open_image_button = QPushButton("Open image")
        self.open_image_button.setEnabled(False)
        self.open_image_button.clicked.connect(self.open_inline_lookup_image)
        image_header.addWidget(image_title)
        image_header.addStretch(1)
        image_header.addWidget(self.open_image_button)
        self.inline_lookup_image_label = QLabel("Select a target to load image.")
        self.inline_lookup_image_label.setObjectName("astroLookupImagePreview")
        self.inline_lookup_image_label.setAlignment(Qt.AlignCenter)
        self.inline_lookup_image_label.setWordWrap(True)
        self.inline_lookup_image_label.setMinimumSize(320, 260)
        self.inline_lookup_image_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.inline_lookup_meta_label = QLabel("Type: -- | Distance: --")
        self.inline_lookup_meta_label.setObjectName("targetPreviewMetaLabel")
        self.inline_lookup_meta_label.setWordWrap(True)
        image_layout.addLayout(image_header)
        image_layout.addWidget(self.inline_lookup_image_label, 1)
        image_layout.addWidget(self.inline_lookup_meta_label)
        side.addWidget(image_panel, 4)

        framing_panel = QFrame()
        framing_panel.setObjectName("astroLookupSettingsCard")
        framing_layout = QGridLayout(framing_panel)
        framing_layout.setContentsMargins(8, 8, 8, 8)
        framing_layout.setHorizontalSpacing(6)
        framing_layout.setVerticalSpacing(6)
        framing_title = QLabel("FRAMING / CAPTURE TO SEND")
        framing_title.setObjectName("astroLookupSectionTitle")
        framing_layout.addWidget(framing_title, 0, 0, 1, 4)

        self.imaging_camera_combo = QComboBox()
        self.imaging_camera_combo.setObjectName("astroLookupCombo")
        for preset_key, preset in CAMERA_PRESETS.items():
            self.imaging_camera_combo.addItem(
                str(preset.get("label") or preset.get("name") or preset_key),
                str(preset_key),
            )
        self.imaging_focal_spin = QDoubleSpinBox()
        self.imaging_focal_spin.setObjectName("astroLookupCombo")
        self.imaging_focal_spin.setRange(50.0, 6000.0)
        self.imaging_focal_spin.setDecimals(1)
        self.imaging_focal_spin.setSuffix(" mm")
        self.imaging_focal_spin.setValue(700.0)
        self.imaging_exposure_spin = QSpinBox()
        self.imaging_exposure_spin.setObjectName("astroLookupCombo")
        self.imaging_exposure_spin.setRange(1, 86400)
        self.imaging_exposure_spin.setSuffix(" s")
        self.imaging_exposure_spin.setValue(60)
        self.imaging_gain_spin = QSpinBox()
        self.imaging_gain_spin.setObjectName("astroLookupCombo")
        self.imaging_gain_spin.setRange(0, 10000)
        self.imaging_gain_spin.setValue(200)

        self.update_framing_preview_button = QPushButton("UPDATE PREVIEW")
        self.update_framing_preview_button.clicked.connect(
            self.update_selected_framing_preview
        )
        self.framing_preview_label = QLabel(
            "Select a target; frames are auto-calculated later from the best SEEING window."
        )
        self.framing_preview_label.setObjectName("sidebarFooter")
        self.framing_preview_label.setWordWrap(True)

        fields = [
            ("Camera", self.imaging_camera_combo),
            ("Focal", self.imaging_focal_spin),
            ("Exposure", self.imaging_exposure_spin),
            ("Gain", self.imaging_gain_spin),
        ]
        for index, (caption, widget) in enumerate(fields):
            row = 1 + index // 2
            col = (index % 2) * 2
            label = QLabel(caption)
            label.setObjectName("toolbarCaption")
            framing_layout.addWidget(label, row, col)
            framing_layout.addWidget(widget, row, col + 1)
        framing_layout.addWidget(self.update_framing_preview_button, 3, 0, 1, 2)
        framing_layout.addWidget(self.framing_preview_label, 3, 2, 1, 2)
        side.addWidget(framing_panel, 0)

        self._load_parent_imaging_into_targets_controls()
        self.imaging_camera_combo.currentIndexChanged.connect(
            self.handle_targets_framing_changed
        )
        for widget in (
            self.imaging_focal_spin,
            self.imaging_exposure_spin,
            self.imaging_gain_spin,
        ):
            widget.valueChanged.connect(self.handle_targets_framing_changed)

        action_row = QHBoxLayout()
        self.lookup_button = QPushButton("Open in LOOKUP")
        self.lookup_button.clicked.connect(self.open_selected_in_lookup)
        self.lookup_button.setEnabled(False)
        self.copy_button = QPushButton("Copy name")
        self.copy_button.clicked.connect(self.copy_selected_name)
        self.copy_button.setEnabled(False)
        self.send_to_imaging_button = QPushButton("SEND TO FZASTRO IMAGING")
        self.send_to_imaging_button.setObjectName("primaryActionButton")
        self.send_to_imaging_button.clicked.connect(
            self.send_selected_to_imaging_control
        )
        self.send_to_imaging_button.setEnabled(False)
        action_row.addWidget(self.lookup_button)
        action_row.addWidget(self.copy_button)
        action_row.addWidget(self.send_to_imaging_button)
        side.addLayout(action_row)
        split.addLayout(side, 2)

        layout.addLayout(split, 1)
        return card

    def _site_summary(self) -> str:
        try:
            return (
                f"{float(self.location.get('lat', 0.0)):.5f}, "
                f"{float(self.location.get('lon', 0.0)):.5f} · "
                f"{float(self.location.get('elev', 0.0)):.0f} m · "
                f"{self.location.get('tz', 'UTC')}"
            )
        except Exception:
            return "Site not set"

    def _app_parent(self):
        return getattr(self, "_workspace_host", None) or self.parent()

    def _status_html(self, title: str, body: str = "") -> str:
        safe_title = html.escape(str(title))
        safe_body = html.escape(str(body))
        return f"""
        <html><body style="background:#0f1318;color:#e8edf2;
        font-family:'Segoe UI',sans-serif;font-size:10px;">
        <div style="border:1px solid #303b47;border-radius:12px;
        padding:9px;background:#111820;">
          <div style="font-size:12px;font-weight:800;color:#f0f4f8;
          margin-bottom:4px;">{safe_title}</div>
          <div style="color:#aab5c1;">{safe_body}</div>
        </div>
        </body></html>
        """

    def refresh_catalog_status(self):
        try:
            stats = catalog_stats()
            sources = ", ".join(
                f"{name}: {count}" for name, count in stats.get("sources", {}).items()
            )
            self.summary_label.setText(
                f"Catalog: {stats.get('total', 0)} objects · "
                f"{sources or 'empty'} · {stats.get('path', '')}"
            )
        except Exception as exc:
            log_warning("TargetsDialog.refresh_catalog_status failed", exc)
            self.summary_label.setText("Catalog status unavailable")

    def planner_options(self) -> dict[str, Any]:
        max_mag = (
            float(self.max_mag_spin.value()) if self.use_mag_check.isChecked() else None
        )
        return {
            "date_iso": self.date_edit.date().toString("yyyy-MM-dd"),
            "limit": int(self.limit_spin.value()),
            "min_alt": float(self.min_alt_spin.value()),
            "step_min": 3,
            "catalog_source": str(self.catalog_combo.currentData() or "auto"),
            "object_type": str(self.type_combo.currentData() or "All"),
            "min_size_arcmin": float(self.min_size_spin.value()),
            "max_mag": max_mag,
        }

    def change_site(self):
        parent = self._app_parent()
        selected = choose_astro_location(self, self.location)
        if not selected:
            return
        self.location = dict(selected)
        if parent is not None and hasattr(parent, "set_current_astro_location"):
            try:
                parent.set_current_astro_location(selected)
            except Exception as exc:
                log_warning("TargetsDialog.change_site parent update failed", exc)
        self.site_label.setText(self._site_summary())
        self.run_planner()

    def run_planner(self):
        if self.targets_worker is not None and self.targets_worker.isRunning():
            if self._stop_worker():
                self.status_label.setText("Stopping…")
                self.run_button.setText("Stopping…")
                self.run_button.setEnabled(False)
            return
        self.table.setRowCount(0)
        self._last_picks = []
        self._inline_lookup_serial += 1
        self._stop_inline_lookup_worker()
        self.lookup_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.send_to_imaging_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self._clear_inline_lookup_panel(
            "Select a target",
            "LOOKUP details and sky preview will load here after the planner finishes.",
        )
        self.details_browser.setHtml(
            self._status_html(
                "Calculating targets",
                "Evaluating the catalog against the selected astronomical night.",
            )
        )
        self.status_label.setText("Running…")
        self.progress_bar.show()
        self._set_controls_enabled(False)
        self.run_button.setText("Stop")
        self.run_button.setEnabled(True)

        self.targets_worker = TargetsWorker(self.location, self.planner_options())
        self.targets_worker.finished_targets.connect(self.handle_targets_finished)
        self.targets_worker.error_received.connect(self.handle_targets_error)
        self.targets_worker.finished.connect(self.handle_targets_worker_finished)
        self.targets_worker.start()

    def handle_targets_finished(
        self, result: dict[str, Any], elapsed: float, success: bool
    ):
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self._last_result = dict(result or {})
        if not success or not result.get("ok", True):
            message = str(result.get("error") or "No targets found for these settings.")
            self.status_label.setText("No result")
            self.details_browser.setHtml(
                self._status_html("No matching targets", message)
            )
            return

        picks = [dict(row) for row in result.get("picks", [])]
        self._last_picks = picks
        self.populate_table(picks)
        self.refresh_result_summary(result, elapsed)
        self.status_label.setText(f"{len(picks)} targets · {elapsed:.1f}s")
        self.export_button.setEnabled(bool(picks))
        if picks:
            self.table.selectRow(0)
        else:
            self.details_browser.setHtml(
                self._status_html(
                    "No matching targets",
                    "Try a lower minimum altitude, a different object type, "
                    "or the full local catalog.",
                )
            )

    def populate_table(self, picks: list[dict[str, Any]]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(picks))
        for row_index, pick in enumerate(picks):
            values = [
                pick.get("grade"),
                pick.get("name"),
                pick.get("type"),
                pick.get("const"),
                self._fmt_float(pick.get("mag"), 1),
                self._size_label(pick),
                self._fmt_float(pick.get("max_alt"), 1, "°"),
                self._fmt_float(pick.get("airmass_min"), 2),
                self._fmt_minutes(pick.get("visible_minutes")),
                self._fmt_local_time(pick.get("best_time_local")),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value if value is not None else "—"))
                if column in {0, 4, 6, 7, 8}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setData(Qt.UserRole, pick)
                self.table.setItem(row_index, column, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def refresh_result_summary(self, result: dict[str, Any], elapsed: float):
        dark_start = self._fmt_window_time(result.get("dark_start"))
        dark_end = self._fmt_window_time(result.get("dark_end"))
        duration = self._fmt_minutes(result.get("duration_minutes"))
        moon = result.get("moon") or {}
        self.summary_label.setText(
            f"Astro darkness: {dark_start} → {dark_end} ({duration}) · "
            f"Moon: {moon.get('illumination_pct', '—')}% {moon.get('phase', '')} · "
            f"Evaluated: {result.get('evaluated', 0)} · "
            f"Rejected: {result.get('rejected', 0)} · {elapsed:.1f}s"
        )

    def selected_pick(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return dict(data) if isinstance(data, dict) else None

    def update_details_from_selection(self):
        pick = self.selected_pick()
        enabled = bool(pick)
        self.lookup_button.setEnabled(enabled)
        self.copy_button.setEnabled(enabled)
        self.send_to_imaging_button.setEnabled(enabled)
        if not pick:
            return
        self.details_browser.setHtml(self._details_html(pick))
        self._update_inline_lookup_meta(pick)
        self.refresh_targets_framing_summary(pick)
        self.queue_inline_lookup(pick)

    def _details_html(self, pick: dict[str, Any]) -> str:
        name = html.escape(str(pick.get("name") or "Target"))
        rows = [
            ("Grade", pick.get("grade")),
            ("Type", pick.get("type")),
            ("Constellation", pick.get("const")),
            ("RA", pick.get("ra")),
            ("Dec", pick.get("dec")),
            ("Magnitude", self._fmt_float(pick.get("mag"), 1)),
            ("Size", self._size_label(pick)),
            ("Max altitude", self._fmt_float(pick.get("max_alt"), 1, "°")),
            ("Best airmass", self._fmt_float(pick.get("airmass_min"), 2)),
            ("Visible", self._fmt_minutes(pick.get("visible_minutes"))),
            ("Best local time", self._fmt_local_time(pick.get("best_time_local"))),
        ]
        row_html = "".join(
            "<tr>"
            f"<th>{html.escape(str(label))}</th>"
            f"<td>{html.escape(str(value if value not in (None, '') else '—'))}</td>"
            "</tr>"
            for label, value in rows
        )
        return f"""
        <html><body style="background:#0f1318;color:#e8edf2;
        font-family:'Segoe UI',sans-serif;font-size:10px;">
        <h1 style="font-size:16px;margin:0 0 8px 0;color:#f4f8fc;">{name}</h1>
        <table style="border-collapse:collapse;width:100%;">
        {row_html}
        </table>
        <p style="color:#9ca8b4;margin-top:8px;">Score: airmass, visibility
        duration, best-time placement, and apparent size.</p>
        </body></html>
        """

    def _update_inline_lookup_meta(
        self, pick: dict[str, Any] | None = None, lookup_text: str = ""
    ):
        if not hasattr(self, "inline_lookup_meta_label"):
            return
        data = dict(pick or self.selected_pick() or {})
        if not data:
            self.inline_lookup_meta_label.setText("Type: -- | Distance: --")
            return
        object_type = (
            str(data.get("type") or data.get("object_type") or "Object").strip() or "--"
        )
        distance = self._target_distance_text(data, lookup_text=lookup_text)
        self.inline_lookup_meta_label.setText(
            f"Type: {object_type} | Distance: {distance}"
        )

    def _target_distance_text(self, pick: dict[str, Any], lookup_text: str = "") -> str:
        for key in ("distance_text", "distance_label", "distance", "dist"):
            value = pick.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        for key, unit in (
            ("distance_ly", "ly"),
            ("distance_light_years", "ly"),
            ("distance_pc", "pc"),
            ("distance_kpc", "kpc"),
            ("distance_mpc", "Mpc"),
        ):
            value = pick.get(key)
            if value is not None and str(value).strip():
                return self._fmt_distance_value(value, unit)

        lookup_distance = self._lookup_distance_from_text(lookup_text)
        return lookup_distance or "--"

    @staticmethod
    def _fmt_distance_value(value: Any, unit: str) -> str:
        try:
            number = float(value)
        except Exception:
            return str(value).strip() or "--"

        clean_unit = str(unit or "").strip()
        if clean_unit == "ly":
            if abs(number) >= 1_000_000_000:
                return f"{number / 1_000_000_000:.2f} Gly"
            if abs(number) >= 1_000_000:
                return f"{number / 1_000_000:.2f} Mly"
            if abs(number) >= 1_000:
                return f"{number / 1_000:.2f} kly"
            return f"{number:.0f} ly"
        if clean_unit == "pc" and abs(number) >= 1_000:
            return f"{number / 1_000:.2f} kpc"
        return f"{number:.2f} {clean_unit}".strip()

    @staticmethod
    def _lookup_distance_from_text(text: str) -> str:
        body = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            return ""
        lower_body = body.casefold()
        marker = lower_body.find("distance")
        if marker < 0:
            return ""
        segment = body[marker : marker + 220]
        if "not available" in segment.casefold():
            return ""
        match = re.search(
            r"\b([0-9][0-9,.\s]*(?:k|M|G)?\s*(?:ly|light years?|pc|kpc|Mpc|Gpc))\b",
            segment,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()

    def _clear_inline_lookup_panel(self, title: str, body: str = ""):
        self._inline_lookup_pixmap = None
        self._inline_lookup_image_path = None
        self._inline_lookup_html = ""
        self.inline_lookup_status_label.setText("Idle")
        self.inline_lookup_browser.setHtml(self._status_html(title, body))
        self.inline_lookup_image_label.setPixmap(QPixmap())
        self.inline_lookup_image_label.setText("No image loaded.")
        self.inline_lookup_image_label.setToolTip("")
        self._update_inline_lookup_meta({})
        self.open_image_button.setEnabled(False)

    def queue_inline_lookup(self, pick: dict[str, Any]):
        query = str(pick.get("name") or "").strip()
        if not query:
            self._clear_inline_lookup_panel(
                "No LOOKUP query", "Selected target has no object name."
            )
            return

        self._inline_lookup_serial += 1
        serial = self._inline_lookup_serial
        self._stop_inline_lookup_worker()
        self._inline_lookup_pixmap = None
        self._update_inline_lookup_meta(pick)
        self.inline_lookup_status_label.setText("Queued")
        self.inline_lookup_browser.setHtml(
            self._status_html(
                f"Loading {query}",
                "Resolving LOOKUP details and compact sky preview.",
            )
        )
        self.inline_lookup_image_label.setPixmap(QPixmap())
        self.inline_lookup_image_label.setText("Loading sky preview…")
        self.inline_lookup_image_label.setToolTip("")
        self.open_image_button.setEnabled(False)
        QTimer.singleShot(
            180,
            lambda expected_query=query, expected_serial=serial: self.run_inline_lookup(
                expected_query,
                expected_serial,
            ),
        )

    def run_inline_lookup(self, query: str, serial: int):
        if serial != self._inline_lookup_serial:
            return
        selected = self.selected_pick()
        if str((selected or {}).get("name") or "").strip() != str(query).strip():
            return

        params_data = self._selected_targets_imaging()
        params_data["query"] = str(query).strip()
        params = _lookup_params_from_dialog_data(params_data)
        width = max(1, int(params.get("width", 900)))
        height = max(1, int(params.get("height", 600)))
        scale = min(1.0, 760.0 / float(width), 500.0 / float(height))
        params["width"] = max(320, int(width * scale))
        params["height"] = max(220, int(height * scale))

        worker = AstroWorker("lookup", params)
        worker.setProperty("target_lookup_serial", serial)
        self.inline_lookup_worker = worker
        worker.finished_astro.connect(self.handle_inline_lookup_finished)
        worker.stopped_astro.connect(self.handle_inline_lookup_stopped)
        worker.error_received.connect(self.handle_inline_lookup_error)
        worker.finished.connect(self.handle_inline_lookup_worker_finished)
        self.inline_lookup_status_label.setText("Running…")
        worker.start()

    def handle_inline_lookup_finished(
        self,
        text: str,
        _source: str,
        files: list,
        elapsed: float,
        success: bool,
    ):
        if not self._inline_lookup_signal_is_current():
            return
        clean_text = str(text or "").strip()
        if success:
            self.inline_lookup_status_label.setText(f"Finished • {float(elapsed):.2f}s")
            self._inline_lookup_html = self._lookup_result_html(clean_text)
            self.inline_lookup_browser.setHtml(self._inline_lookup_html)
        else:
            self.inline_lookup_status_label.setText(f"Problem • {float(elapsed):.2f}s")
            self.inline_lookup_browser.setHtml(
                self._status_html("LOOKUP problem", clean_text or "No output returned.")
            )
        self._update_inline_lookup_meta(self.selected_pick(), clean_text)
        self._show_inline_lookup_image([str(path) for path in list(files or [])])

    def handle_inline_lookup_stopped(self, _elapsed: float):
        if not self._inline_lookup_signal_is_current():
            return
        self.inline_lookup_status_label.setText("Stopped")

    def handle_inline_lookup_error(self, error: str):
        if not self._inline_lookup_signal_is_current():
            return
        self.inline_lookup_status_label.setText("Failed")
        self.inline_lookup_browser.setHtml(
            self._status_html("LOOKUP failed", str(error))
        )
        self.inline_lookup_image_label.setPixmap(QPixmap())
        self.inline_lookup_image_label.setText("No image loaded.")
        self._update_inline_lookup_meta(self.selected_pick())

    def handle_inline_lookup_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "inline_lookup_worker", None):
            self.inline_lookup_worker = None
        if worker is not None:
            worker.deleteLater()

    def _inline_lookup_signal_is_current(self) -> bool:
        worker = self.sender()
        if worker is None:
            return True
        try:
            serial = int(worker.property("target_lookup_serial") or 0)
        except Exception:
            serial = 0
        return serial == int(self._inline_lookup_serial)

    def _lookup_result_html(self, text: str) -> str:
        body = str(text or "").strip()
        if not body:
            return self._status_html("No LOOKUP data returned")
        if _looks_like_html(body):
            content = body
        else:
            content = _legacy_lookup_to_html(body) or _markdown_to_html(body)
        return f"""
        <html><body style="background:#0f1318;color:#e8edf2;
        font-family:'Segoe UI',sans-serif;font-size:10px;line-height:1.18;">
        {content}
        </body></html>
        """

    def _show_inline_lookup_image(self, files: list[str]):
        image_path = None
        for candidate in files:
            path = Path(str(candidate))
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
            }:
                image_path = path
                break

        if image_path is None:
            self._inline_lookup_pixmap = None
            self._inline_lookup_image_path = None
            self.inline_lookup_image_label.setPixmap(QPixmap())
            self.inline_lookup_image_label.setText("No sky image returned.")
            self.inline_lookup_image_label.setToolTip("")
            return

        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._inline_lookup_pixmap = None
            self._inline_lookup_image_path = None
            self.inline_lookup_image_label.setPixmap(QPixmap())
            self.inline_lookup_image_label.setText(
                "Image returned, but Qt could not load it."
            )
            self.inline_lookup_image_label.setToolTip("")
            self.open_image_button.setEnabled(False)
            return

        self._inline_lookup_pixmap = pixmap
        self._inline_lookup_image_path = image_path
        self.inline_lookup_image_label.setText("")
        self.inline_lookup_image_label.setToolTip(str(image_path))
        self.open_image_button.setEnabled(True)
        self._rescale_inline_lookup_pixmap()
        self._update_open_inline_lookup_image()

    def open_inline_lookup_image(self):
        if self._inline_lookup_pixmap is None or self._inline_lookup_pixmap.isNull():
            return
        pick = self.selected_pick() or {}
        name = str(pick.get("name") or "TARGETS").strip()
        title = f"Sky preview - {name}"
        if self._floating_preview_dialog is None:
            dialog = FloatingSkyPreviewDialog(
                self, title=title, pixmap=self._inline_lookup_pixmap
            )
            dialog.destroyed.connect(
                lambda *_: setattr(self, "_floating_preview_dialog", None)
            )
            self._floating_preview_dialog = dialog
        else:
            self._floating_preview_dialog.set_pixmap(
                self._inline_lookup_pixmap, title=title
            )
        self._floating_preview_dialog.show()
        self._floating_preview_dialog.raise_()
        self._floating_preview_dialog.activateWindow()

    def _update_open_inline_lookup_image(self):
        dialog = self._floating_preview_dialog
        if dialog is None or not dialog.isVisible():
            return
        if self._inline_lookup_pixmap is None or self._inline_lookup_pixmap.isNull():
            return
        pick = self.selected_pick() or {}
        name = str(pick.get("name") or "TARGETS").strip()
        dialog.set_pixmap(self._inline_lookup_pixmap, title=f"Sky preview - {name}")

    def _rescale_inline_lookup_pixmap(self):
        if self._inline_lookup_pixmap is None or self._inline_lookup_pixmap.isNull():
            return
        target = self.inline_lookup_image_label.size()
        if target.width() <= 4 or target.height() <= 4:
            return
        self.inline_lookup_image_label.setPixmap(
            self._inline_lookup_pixmap.scaled(
                target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def _stop_inline_lookup_worker(self) -> bool:
        worker = getattr(self, "inline_lookup_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.stop()
            except Exception:
                pass
            return True
        return False

    def open_selected_in_lookup(self):
        pick = self.selected_pick()
        if not pick:
            return
        parent = self._app_parent()
        query = str(pick.get("name") or "").strip()
        if parent is not None and hasattr(parent, "open_astro_lookup_dialog"):
            parent.open_astro_lookup_dialog(query, auto_run=True)
            return
        imaging = None
        if parent is not None and hasattr(parent, "get_current_astro_imaging"):
            try:
                imaging = parent.get_current_astro_imaging()
            except Exception:
                imaging = None
        dialog = AstroLookupDialog(
            self, imaging=imaging, query=query, include_query=True
        )
        dialog.exec()
        if parent is not None and hasattr(parent, "set_current_astro_imaging"):
            try:
                parent.set_current_astro_imaging(
                    dialog.result_data(include_query=False)
                )
            except Exception as exc:
                log_warning(
                    "TargetsDialog.open_selected_in_lookup imaging update failed", exc
                )

    def copy_selected_name(self):
        pick = self.selected_pick()
        if not pick:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(str(pick.get("name") or ""))
        self.status_label.setText("Copied target name")

    def send_selected_to_imaging_control(self):
        pick = self.selected_pick()
        if not pick:
            QMessageBox.information(self, "FZASTRO IMAGING", "Select a target first.")
            return
        parent = self._app_parent()
        setter = (
            getattr(parent, "set_pending_imaging_target_from_targets", None)
            if parent is not None
            else None
        )
        opener = (
            getattr(parent, "open_nina_control", None) if parent is not None else None
        )
        if setter is None or opener is None:
            QMessageBox.information(
                self,
                "FZASTRO IMAGING",
                "Open TARGETS from the main FZAstro AI window to send a selected target into Imaging Control.",
            )
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(20)
        self.progress_bar.show()
        self.status_label.setText("Sending selected target to FZASTRO IMAGING…")
        setter(
            pick,
            planner_options=self.planner_options(),
            planner_result=self._last_result,
            imaging=self._selected_targets_imaging(),
            capture={
                "exposure_seconds": int(self.imaging_exposure_spin.value()),
                "gain": int(self.imaging_gain_spin.value()),
            },
            lookup_html=self._inline_lookup_html,
            preview_image_path=str(self._inline_lookup_image_path or ""),
            framing_preview=self._current_framing_details(),
        )
        self.progress_bar.setValue(70)
        self.status_label.setText(
            f"Sent {pick.get('name') or 'target'} to FZASTRO IMAGING"
        )
        opener()
        self.progress_bar.setValue(100)
        # The target selection step is complete. Close TARGETS so the user lands
        # in Imaging Control for final framing/capture review and confirmation.
        QTimer.singleShot(180, self.accept)

    def _load_parent_imaging_into_targets_controls(self):
        parent = self._app_parent()
        imaging = None
        if parent is not None and hasattr(parent, "get_current_astro_imaging"):
            try:
                imaging = parent.get_current_astro_imaging()
            except Exception:
                imaging = None
        data = normalise_astro_imaging(imaging or {})
        index = self.imaging_camera_combo.findData(str(data.get("preset") or "585"))
        if index >= 0:
            self.imaging_camera_combo.setCurrentIndex(index)
        self.imaging_focal_spin.setValue(float(data.get("focal_mm") or 700.0))

    def _selected_targets_imaging(self) -> dict[str, Any]:
        preset = str(self.imaging_camera_combo.currentData() or "585")
        return normalise_astro_imaging(
            {"preset": preset, "focal_mm": float(self.imaging_focal_spin.value())}
        )

    def _current_framing_details(self) -> dict[str, Any]:
        pick = self.selected_pick() or {}
        try:
            return calculate_framing_details(
                target_size=pick.get("size") or self._size_label(pick),
                imaging=self._selected_targets_imaging(),
                exposure_seconds=int(self.imaging_exposure_spin.value()),
                gain=int(self.imaging_gain_spin.value()),
                frames=1,
            )
        except Exception:
            return {}

    def refresh_targets_framing_summary(self, pick: dict[str, Any] | None = None):
        pick = dict(pick or self.selected_pick() or {})
        if not pick:
            self.framing_preview_label.setText(
                "Select a target; frames are auto-calculated later from the best SEEING window."
            )
            return
        imaging = self._selected_targets_imaging()
        framing = self._current_framing_details()
        if framing:
            self.framing_preview_label.setText(
                f"{imaging.get('preset_name') or 'Camera'} · "
                f"{float(imaging.get('focal_mm') or 0):.0f} mm · "
                f"FOV {framing.get('fov_width_deg') or '—'}° × {framing.get('fov_height_deg') or '—'}° · "
                f"scale {framing.get('image_scale_arcsec_px') or '—'} arcsec/px · "
                f"fit {framing.get('target_fit') or '—'} · frames auto from SEEING"
            )
        else:
            self.framing_preview_label.setText(
                f"{imaging.get('preset_name') or 'Camera'} · {float(imaging.get('focal_mm') or 0):.0f} mm · frames auto from SEEING"
            )

    def handle_targets_framing_changed(self):
        self.refresh_targets_framing_summary()
        if self.selected_pick():
            self.inline_lookup_status_label.setText("Preview changed")
            self.inline_lookup_image_label.setText(
                "Click UPDATE PREVIEW to regenerate the frame with this camera/focal length."
            )
            self.open_image_button.setEnabled(False)

    def update_selected_framing_preview(self):
        pick = self.selected_pick()
        if not pick:
            QMessageBox.information(self, "TARGETS framing", "Select a target first.")
            return
        self.refresh_targets_framing_summary(pick)
        self.queue_inline_lookup(pick)

    def import_openngc(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import OpenNGC CSV",
            str(Path.home()),
            "CSV files (*.csv);;All files (*)",
        )
        if not filename:
            return
        try:
            count = import_openngc_csv(filename)
        except Exception as exc:
            log_exception("TargetsDialog.import_openngc", exc)
            QMessageBox.warning(self, "Import OpenNGC", str(exc))
            return
        QMessageBox.information(
            self,
            "Import OpenNGC",
            f"Imported {count} OpenNGC objects into the local TARGETS catalog.",
        )
        self.refresh_catalog_status()
        self.catalog_combo.setCurrentIndex(max(0, self.catalog_combo.findData("auto")))
        self.run_planner()

    def export_csv(self):
        if not self._last_picks:
            return
        default_name = f"fzastro_targets_{date.today().isoformat()}.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export TARGETS CSV",
            str(Path.home() / default_name),
            "CSV files (*.csv);;All files (*)",
        )
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8", newline="") as handle:
                fieldnames = [
                    "grade",
                    "name",
                    "type",
                    "const",
                    "ra",
                    "dec",
                    "mag",
                    "width_deg",
                    "height_deg",
                    "max_alt",
                    "airmass_min",
                    "visible_minutes",
                    "best_time_local",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for pick in self._last_picks:
                    writer.writerow({key: pick.get(key) for key in fieldnames})
            self.status_label.setText("CSV exported")
        except Exception as exc:
            log_exception("TargetsDialog.export_csv", exc)
            QMessageBox.warning(self, "Export CSV", str(exc))

    def handle_targets_error(self, error: str):
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self.run_button.setText("Run Planner")
        self.status_label.setText("Error")
        self.details_browser.setHtml(self._status_html("TARGETS failed", str(error)))

    def handle_targets_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "targets_worker", None):
            self.targets_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_after_worker:
            QTimer.singleShot(0, self.reject)
            return

        # Always return the action button to its idle label when the worker is
        # fully done. Normal successful runs hide the progress bar in
        # handle_targets_finished(), so the old code skipped the reset and left
        # the button saying "Stop" even though clicking it would start a new run.
        self.run_button.setText("Run Planner")
        self.run_button.setEnabled(True)

        if self.progress_bar.isVisible():
            self.progress_bar.hide()
            self._set_controls_enabled(True)
            self.status_label.setText("Stopped")
            self.details_browser.setHtml(
                self._status_html(
                    "Calculation stopped",
                    "The TARGETS planner was stopped before it finished.",
                )
            )

    def _set_controls_enabled(self, enabled: bool):
        for widget in (
            self.change_site_button,
            self.date_edit,
            self.min_alt_spin,
            self.limit_spin,
            self.catalog_combo,
            self.type_combo,
            self.min_size_spin,
            self.use_mag_check,
            self.max_mag_spin,
            self.import_button,
            self.export_button,
        ):
            widget.setEnabled(bool(enabled))
        if enabled:
            self.max_mag_spin.setEnabled(self.use_mag_check.isChecked())
            self.export_button.setEnabled(bool(self._last_picks))

    def _stop_worker(self) -> bool:
        worker = getattr(self, "targets_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.stop()
            except Exception:
                pass
            return True
        return False

    def reject(self):
        self._stop_inline_lookup_worker()
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self.run_button.setText("Stopping…")
            self.run_button.setEnabled(False)
            self._set_controls_enabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        self._stop_inline_lookup_worker()
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self.run_button.setText("Stopping…")
            self.run_button.setEnabled(False)
            self._set_controls_enabled(False)
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rescale_inline_lookup_pixmap)

    @staticmethod
    def _fmt_float(value: Any, digits: int = 1, suffix: str = "") -> str:
        try:
            return f"{float(value):.{int(digits)}f}{suffix}"
        except Exception:
            return "—"

    @staticmethod
    def _fmt_minutes(value: Any) -> str:
        try:
            minutes = int(value)
        except Exception:
            return "—"
        hours, mins = divmod(minutes, 60)
        if hours <= 0:
            return f"{mins}m"
        return f"{hours}h {mins:02d}m"

    @staticmethod
    def _fmt_local_time(value: Any) -> str:
        try:
            return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "—"

    @staticmethod
    def _fmt_window_time(value: Any) -> str:
        try:
            return datetime.fromisoformat(str(value)).strftime("%a %H:%M")
        except Exception:
            return "—"

    @staticmethod
    def _size_label(pick: dict[str, Any]) -> str:
        size = str(pick.get("size") or "").strip()
        if size:
            return size
        width = pick.get("width_deg")
        height = pick.get("height_deg")
        try:
            return f"{float(width):.3f}°×{float(height):.3f}°"
        except Exception:
            return "—"


def show_targets_dialog(parent=None, location: dict[str, Any] | None = None):
    if parent is not None and hasattr(parent, "open_workspace_tab"):

        def _clear_reference(_widget=None):
            try:
                if getattr(parent, "astro_targets_dialog", None) is _widget:
                    setattr(parent, "astro_targets_dialog", None)
            except Exception:
                pass

        def _create_targets_tab():
            dialog = TargetsDialog(parent, location=location)
            setattr(parent, "astro_targets_dialog", dialog)
            try:
                dialog.destroyed.connect(lambda *_args: _clear_reference(dialog))
            except Exception:
                pass
            return dialog

        return parent.open_workspace_tab(
            "astro.targets",
            "TARGETS",
            _create_targets_tab,
            tooltip="Best astrophotography targets for the selected site",
            on_close=_clear_reference,
        )

    existing = (
        getattr(parent, "astro_targets_dialog", None) if parent is not None else None
    )
    if existing is not None:
        try:
            if existing.isVisible():
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return QDialog.Accepted
        except RuntimeError:
            existing = None

    dialog = TargetsDialog(parent, location=location)
    if parent is not None:
        setattr(parent, "astro_targets_dialog", dialog)

        def _clear_reference():
            try:
                if getattr(parent, "astro_targets_dialog", None) is dialog:
                    setattr(parent, "astro_targets_dialog", None)
            except Exception:
                pass

        dialog.destroyed.connect(_clear_reference)
    try:
        return dialog.exec()
    finally:
        if (
            parent is not None
            and getattr(parent, "astro_targets_dialog", None) is dialog
        ):
            setattr(parent, "astro_targets_dialog", None)

from __future__ import annotations

import csv
import html
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer
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
from ..workers.targets_worker import TargetsWorker
from .astro_location_dialog import choose_astro_location
from .astro_lookup_dialog import AstroLookupDialog


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
        self.location = dict(location or {})
        self.targets_worker: TargetsWorker | None = None
        self._close_after_worker = False
        self._last_result: dict[str, Any] = {}
        self._last_picks: list[dict[str, Any]] = []

        self.setObjectName("targetsDialog")
        self.setWindowTitle("TARGETS")
        self.resize(1220, 760)
        self.setMinimumSize(980, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(9)

        root.addWidget(self._build_header())
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

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

        self.run_button = QPushButton("Run Planner")
        self.run_button.setObjectName("primaryActionButton")
        self.run_button.clicked.connect(self.run_planner)

        self.import_button = QPushButton("Import OpenNGC CSV")
        self.import_button.clicked.connect(self.import_openngc)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        self.export_button.setEnabled(False)

        captions = [
            ("Site", 0, 0),
            ("Date", 0, 2),
            ("Min altitude", 0, 3),
            ("Limit", 0, 4),
            ("Catalog", 2, 0),
            ("Type", 2, 1),
            ("Min size", 2, 2),
        ]
        for text, row, column in captions:
            label = QLabel(text)
            label.setObjectName("toolbarCaption")
            layout.addWidget(label, row, column)

        layout.addWidget(self.site_label, 1, 0, 1, 1)
        layout.addWidget(self.change_site_button, 1, 1)
        layout.addWidget(self.date_edit, 1, 2)
        layout.addWidget(self.min_alt_spin, 1, 3)
        layout.addWidget(self.limit_spin, 1, 4)
        layout.addWidget(self.run_button, 1, 5)

        layout.addWidget(self.catalog_combo, 3, 0)
        layout.addWidget(self.type_combo, 3, 1)
        layout.addWidget(self.min_size_spin, 3, 2)
        layout.addWidget(self.use_mag_check, 2, 3)
        layout.addWidget(self.max_mag_spin, 3, 3)
        layout.addWidget(self.import_button, 3, 4)
        layout.addWidget(self.export_button, 3, 5)

        layout.setColumnStretch(0, 2)
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
        self.summary_label = QLabel("Catalog loading…")
        self.summary_label.setObjectName("toolbarCaption")
        self.summary_label.setWordWrap(True)
        side.addWidget(self.summary_label)

        self.details_browser = QTextBrowser()
        self.details_browser.setObjectName("astroLookupResultBrowser")
        self.details_browser.setOpenExternalLinks(False)
        self.details_browser.setHtml(
            self._status_html("Run the planner", "Targets will appear here.")
        )
        side.addWidget(self.details_browser, 1)

        action_row = QHBoxLayout()
        self.lookup_button = QPushButton("Open in LOOKUP")
        self.lookup_button.clicked.connect(self.open_selected_in_lookup)
        self.lookup_button.setEnabled(False)
        self.copy_button = QPushButton("Copy name")
        self.copy_button.clicked.connect(self.copy_selected_name)
        self.copy_button.setEnabled(False)
        action_row.addWidget(self.lookup_button)
        action_row.addWidget(self.copy_button)
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
        parent = self.parent()
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
            return
        self.table.setRowCount(0)
        self._last_picks = []
        self.lookup_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.details_browser.setHtml(
            self._status_html(
                "Calculating targets",
                "Evaluating the catalog against the selected astronomical night.",
            )
        )
        self.status_label.setText("Running…")
        self.progress_bar.show()
        self._set_controls_enabled(False)

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
        if not pick:
            return
        self.details_browser.setHtml(self._details_html(pick))

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

    def open_selected_in_lookup(self):
        pick = self.selected_pick()
        if not pick:
            return
        parent = self.parent()
        query = str(pick.get("name") or "").strip()
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
            self.run_button,
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
    dialog = TargetsDialog(parent, location=location)
    return dialog.exec()

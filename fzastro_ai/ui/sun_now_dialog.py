from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
)

from ..workers.sun_now_worker import (
    SUN_NOW_CHANNELS,
    SUN_NOW_RESOLUTIONS,
    SunNowWorker,
    normalise_sun_channel,
    normalise_sun_resolution,
)
from .window_utils import apply_window_defaults


def _format_bytes(value: Any) -> str:
    try:
        size = int(value)
    except Exception:
        size = 0
    if size <= 0:
        return "—"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.0f} KB"


class SunNowDialog(QDialog):
    """Self-contained SUN NOW viewer for latest NASA/SDO solar images."""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_window_defaults(self)
        self.sun_worker: SunNowWorker | None = None
        self._preview_pixmap: QPixmap | None = None
        self._last_result: dict[str, Any] = {}
        self._close_after_worker = False

        self.setObjectName("sunNowDialog")
        self.setWindowTitle("SUN NOW")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)

        header_card = QFrame()
        header_card.setObjectName("astroLookupHeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(2)

        title = QLabel("SUN NOW")
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Latest NASA/SDO solar imagery with Helioviewer metadata and cached fallback."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        controls_card = QFrame()
        controls_card.setObjectName("astroLookupSettingsCard")
        controls_layout = QGridLayout(controls_card)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.setVerticalSpacing(6)
        controls_layout.setColumnStretch(1, 3)
        controls_layout.setColumnStretch(3, 1)

        source_caption = QLabel("Source")
        source_caption.setObjectName("toolbarCaption")
        self.source_label = QLabel("NASA/SDO latest + Helioviewer metadata")
        self.source_label.setObjectName("astroLookupPill")
        self.source_label.setToolTip(
            "Direct SDO latest image feed with Helioviewer closest-image metadata."
        )

        channel_caption = QLabel("Channel")
        channel_caption.setObjectName("toolbarCaption")
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("astroLookupCombo")
        for channel in SUN_NOW_CHANNELS:
            self.channel_combo.addItem(channel.label, channel.key)

        resolution_caption = QLabel("Image size")
        resolution_caption.setObjectName("toolbarCaption")
        self.resolution_combo = QComboBox()
        self.resolution_combo.setObjectName("astroLookupCombo")
        for resolution in SUN_NOW_RESOLUTIONS:
            self.resolution_combo.addItem(f"{resolution} px", resolution)
        self.resolution_combo.setCurrentIndex(0)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryActionButton")
        self.refresh_button.clicked.connect(self.refresh_image)

        self.open_source_button = QPushButton("Open source")
        self.open_source_button.clicked.connect(self.open_source)
        self.open_source_button.setEnabled(False)

        controls_layout.addWidget(source_caption, 0, 0)
        controls_layout.addWidget(channel_caption, 0, 1)
        controls_layout.addWidget(resolution_caption, 0, 2)
        controls_layout.addWidget(self.source_label, 1, 0)
        controls_layout.addWidget(self.channel_combo, 1, 1)
        controls_layout.addWidget(self.resolution_combo, 1, 2)
        controls_layout.addWidget(self.refresh_button, 1, 3)
        controls_layout.addWidget(self.open_source_button, 1, 4)

        result_card = QFrame()
        result_card.setObjectName("astroLookupResultCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)

        result_header = QHBoxLayout()
        result_header.setContentsMargins(0, 0, 0, 0)
        result_title = QLabel("Latest solar image")
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

        split_row = QHBoxLayout()
        split_row.setContentsMargins(0, 0, 0, 0)
        split_row.setSpacing(10)

        image_panel = QFrame()
        image_panel.setObjectName("astroLookupImagePanel")
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(9, 9, 9, 9)
        image_layout.setSpacing(6)

        image_title = QLabel("NASA/SDO preview")
        image_title.setObjectName("astroLookupSectionTitle")
        self.image_label = QLabel("Choose a channel and press Refresh.")
        self.image_label.setObjectName("astroLookupImagePreview")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMinimumSize(650, 470)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        image_layout.addWidget(image_title)
        image_layout.addWidget(self.image_label, 1)
        split_row.addWidget(image_panel, 4)

        info_panel = QFrame()
        info_panel.setObjectName("astroLookupImagePanel")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(9, 9, 9, 9)
        info_layout.setSpacing(6)
        info_title = QLabel("Metadata")
        info_title.setObjectName("astroLookupSectionTitle")
        self.info_browser = QTextBrowser()
        self.info_browser.setObjectName("astroLookupResultBrowser")
        self.info_browser.setOpenExternalLinks(True)
        self.info_browser.setMinimumWidth(280)
        self.info_browser.setHtml(self._metadata_html({}))
        info_layout.addWidget(info_title)
        info_layout.addWidget(self.info_browser, 1)
        split_row.addWidget(info_panel, 1)

        result_layout.addLayout(split_row, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.Close)
        button_row.rejected.connect(self.reject)

        layout.addWidget(header_card)
        layout.addWidget(controls_card)
        layout.addWidget(result_card, 1)
        layout.addWidget(button_row)

        self.channel_combo.currentIndexChanged.connect(self.refresh_image)
        self.resolution_combo.currentIndexChanged.connect(self.refresh_image)
        QTimer.singleShot(80, self.refresh_image)

    def selected_channel_key(self) -> str:
        return str(self.channel_combo.currentData() or SUN_NOW_CHANNELS[0].key)

    def selected_resolution(self) -> int:
        return normalise_sun_resolution(self.resolution_combo.currentData())

    def refresh_image(self):
        if self.sun_worker is not None and self.sun_worker.isRunning():
            return

        channel = normalise_sun_channel(self.selected_channel_key())
        resolution = self.selected_resolution()
        self._preview_pixmap = None
        self._last_result = {}
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(f"Loading {channel.label}…")
        self.info_browser.setHtml(
            self._metadata_html(
                {
                    "label": channel.label,
                    "description": channel.description,
                    "interpretation": channel.interpretation,
                    "resolution": resolution,
                    "status_note": "Loading latest NASA/SDO image…",
                }
            )
        )
        self.status_label.setText("Loading…")
        self.progress_bar.show()
        self.open_source_button.setEnabled(False)
        self._set_controls_enabled(False)

        worker = SunNowWorker(channel.key, resolution)
        self.sun_worker = worker
        worker.finished_sun_now.connect(self.handle_sun_now_finished)
        worker.error_received.connect(self.handle_sun_now_error)
        worker.finished.connect(self.handle_sun_worker_finished)
        worker.start()

    def handle_sun_now_finished(self, result: dict, elapsed: float, success: bool):
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self._last_result = dict(result or {})
        cache_text = "cached" if result.get("cache_used") else "fresh"
        self.status_label.setText(f"Loaded {cache_text} • {float(elapsed):.2f}s")
        self.info_browser.setHtml(self._metadata_html(result))
        self.open_source_button.setEnabled(bool(result.get("source_url")))
        self._show_image_path(str(result.get("image_path") or ""))

    def handle_sun_now_error(self, error: str):
        if self._close_after_worker:
            self.progress_bar.hide()
            self.status_label.setText("Closed")
            return
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self.status_label.setText("Failed")
        self.open_source_button.setEnabled(False)
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("SUN NOW image could not be loaded.")
        self.info_browser.setHtml(
            self._metadata_html(
                {
                    "status_note": f"NASA/SDO image load failed: {error}",
                    "label": normalise_sun_channel(self.selected_channel_key()).label,
                    "resolution": self.selected_resolution(),
                }
            )
        )
        QMessageBox.warning(self, "SUN NOW", str(error))

    def _show_image_path(self, image_path: str):
        path = Path(str(image_path or ""))
        if not path.exists():
            self._preview_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("No image file was returned.")
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._preview_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                f"Image file exists but Qt could not load it:\n{path}"
            )
            return

        self._preview_pixmap = pixmap
        self.image_label.setText("")
        self.image_label.setToolTip(str(path))
        self._rescale_preview_pixmap()

    def _rescale_preview_pixmap(self):
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        target = self.image_label.size()
        if target.width() <= 4 or target.height() <= 4:
            return
        self.image_label.setPixmap(
            self._preview_pixmap.scaled(
                target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def _set_controls_enabled(self, enabled: bool):
        for widget in (
            self.channel_combo,
            self.resolution_combo,
            self.refresh_button,
            self.open_source_button,
        ):
            widget.setEnabled(bool(enabled))
        self.open_source_button.setEnabled(
            bool(enabled and self._last_result.get("source_url"))
        )

    def open_source(self):
        url = str(self._last_result.get("source_url") or "").strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _metadata_html(self, result: dict[str, Any]) -> str:
        label = html.escape(str(result.get("label") or "SUN NOW"))
        source = html.escape(str(result.get("source") or "NASA/SDO latest image"))
        resolution = html.escape(str(result.get("resolution") or "—"))
        last_modified = html.escape(str(result.get("last_modified") or "—"))
        helioviewer_date = html.escape(str(result.get("helioviewer_date") or "—"))
        helioviewer_id = html.escape(str(result.get("helioviewer_id") or "—"))
        description = html.escape(str(result.get("description") or ""))
        interpretation = html.escape(str(result.get("interpretation") or ""))
        status_note = html.escape(str(result.get("status_note") or "Ready."))
        cache_state = "Cached fallback" if result.get("cache_used") else "Live image"
        bytes_text = html.escape(_format_bytes(result.get("bytes")))
        source_url = html.escape(str(result.get("source_url") or ""))

        return f"""
        <html>
        <head>
            <style>
                body {{
                    background: #0f1318;
                    color: #e8edf2;
                    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
                    font-size: 11px;
                    line-height: 1.28;
                    margin: 0;
                }}
                h1 {{ color: #ffffff; font-size: 16px; margin: 0 0 6px 0; }}
                h2 {{ color: #eef3f8; font-size: 12px; margin: 9px 0 4px 0; }}
                p {{ margin: 3px 0; }}
                .pill {{
                    display: inline-block;
                    color: #cfe4ff;
                    background: #111a23;
                    border: 1px solid #2a3948;
                    border-radius: 8px;
                    padding: 3px 6px;
                    font-weight: 800;
                    margin: 0 0 6px 0;
                }}
                .k {{ color: #93a8bd; font-size: 10px; font-weight: 850; }}
                .v {{ color: #f3f7fc; font-weight: 650; }}
                .note {{ color: #aeb9c5; }}
                .url {{ color: #82baf0; word-break: break-all; }}
            </style>
        </head>
        <body>
            <h1>{label}</h1>
            <div class="pill">{html.escape(cache_state)}</div>
            <p class="note">{status_note}</p>
            <h2>What this shows</h2>
            <p>{description}</p>
            <p class="note">{interpretation}</p>
            <h2>Image</h2>
            <p><span class="k">Source:</span> <span class="v">{source}</span></p>
            <p><span class="k">Resolution:</span> <span class="v">{resolution} px</span></p>
            <p><span class="k">Downloaded:</span> <span class="v">{bytes_text}</span></p>
            <p><span class="k">HTTP time:</span> <span class="v">{last_modified}</span></p>
            <h2>Helioviewer metadata</h2>
            <p><span class="k">Closest image:</span> <span class="v">{helioviewer_date}</span></p>
            <p><span class="k">Image ID:</span> <span class="v">{helioviewer_id}</span></p>
            <h2>Source URL</h2>
            <p class="url">{source_url or '—'}</p>
        </body>
        </html>
        """

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rescale_preview_pixmap)

    def handle_sun_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "sun_worker", None):
            self.sun_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_after_worker:
            QTimer.singleShot(0, self.reject)

    def _stop_worker(self) -> bool:
        worker = getattr(self, "sun_worker", None)
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


def show_sun_now_dialog(parent=None):
    if parent is not None and hasattr(parent, "open_workspace_tab"):
        return parent.open_workspace_tab(
            "astro.sun_now",
            "SUN NOW",
            lambda: SunNowDialog(parent),
            tooltip="Latest NASA/SDO Sun images and Helioviewer metadata",
        )
    dialog = SunNowDialog(parent)
    return dialog.exec()

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
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)

from ..workers.sun_now_worker import (
    SDO_DASHBOARD_URL,
    SDO_FEEDS_PAGE_URL,
    SUN_NOW_CHANNELS,
    SUN_NOW_RESOLUTIONS,
    SunNowWorker,
    normalise_sun_channel,
    normalise_sun_mode,
    normalise_sun_resolution,
)
from .window_utils import apply_window_defaults

try:  # Optional at runtime on lean PySide6 installs.
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except Exception:  # pragma: no cover - depends on installed Qt feature set
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None


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
        self._media_player = None
        self._audio_output = None

        self.setObjectName("sunNowDialog")
        self.setWindowTitle("SUN NOW")
        self.resize(1320, 820)
        self.setMinimumSize(980, 650)

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
            "Latest NASA/SDO solar imagery, looping SDO daily movies, Helioviewer metadata, and solar alerts/news."
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
        controls_layout.setColumnStretch(4, 1)

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

        mode_caption = QLabel("Mode")
        mode_caption.setObjectName("toolbarCaption")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("astroLookupCombo")
        self.mode_combo.addItem("Latest image", "image")
        self.mode_combo.addItem("Recent movie loop", "movie")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryActionButton")
        self.refresh_button.clicked.connect(self.refresh_image)

        self.open_source_button = QPushButton("Open source")
        self.open_source_button.clicked.connect(self.open_source)
        self.open_source_button.setEnabled(False)

        controls_layout.addWidget(source_caption, 0, 0)
        controls_layout.addWidget(channel_caption, 0, 1)
        controls_layout.addWidget(resolution_caption, 0, 2)
        controls_layout.addWidget(mode_caption, 0, 3)
        controls_layout.addWidget(self.source_label, 1, 0)
        controls_layout.addWidget(self.channel_combo, 1, 1)
        controls_layout.addWidget(self.resolution_combo, 1, 2)
        controls_layout.addWidget(self.mode_combo, 1, 3)
        controls_layout.addWidget(self.refresh_button, 1, 4)
        controls_layout.addWidget(self.open_source_button, 1, 5)

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

        self.sun_splitter = QSplitter(Qt.Horizontal)
        self.sun_splitter.setObjectName("astroLookupResultSplitter")
        self.sun_splitter.setChildrenCollapsible(False)
        self.sun_splitter.setHandleWidth(8)

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
        self.image_label.setMinimumSize(720, 500)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget = None
        if QVideoWidget is not None:
            self.video_widget = QVideoWidget()
            self.video_widget.setObjectName("astroLookupImagePreview")
            self.video_widget.setMinimumSize(720, 500)
            self.video_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Expanding
            )
            self.video_widget.hide()
        image_layout.addWidget(image_title)
        image_layout.addWidget(self.image_label, 1)
        if self.video_widget is not None:
            image_layout.addWidget(self.video_widget, 1)
        self.sun_splitter.addWidget(image_panel)

        info_panel = QFrame()
        info_panel.setObjectName("astroLookupImagePanel")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(9, 9, 9, 9)
        info_layout.setSpacing(6)
        info_title = QLabel("Solar details")
        info_title.setObjectName("astroLookupSectionTitle")
        self.info_tabs = QTabWidget()
        self.info_tabs.setObjectName("astroLookupDetailsTabs")
        self.info_browser = QTextBrowser()
        self.info_browser.setObjectName("astroLookupResultBrowser")
        self.info_browser.setOpenExternalLinks(True)
        self.news_browser = QTextBrowser()
        self.news_browser.setObjectName("astroLookupResultBrowser")
        self.news_browser.setOpenExternalLinks(True)
        for browser in (self.info_browser, self.news_browser):
            browser.setMinimumWidth(310)
        self.info_browser.setHtml(self._metadata_html({}))
        self.news_browser.setHtml(self._news_html([]))
        self.info_tabs.addTab(self.info_browser, "Metadata")
        self.info_tabs.addTab(self.news_browser, "Alerts / news")
        info_layout.addWidget(info_title)
        info_layout.addWidget(self.info_tabs, 1)
        self.sun_splitter.addWidget(info_panel)
        self.sun_splitter.setStretchFactor(0, 5)
        self.sun_splitter.setStretchFactor(1, 2)
        self.sun_splitter.setSizes([900, 360])

        result_layout.addWidget(self.sun_splitter, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.Close)
        button_row.rejected.connect(self.reject)

        layout.addWidget(header_card)
        layout.addWidget(controls_card)
        layout.addWidget(result_card, 1)
        layout.addWidget(button_row)

        self.channel_combo.currentIndexChanged.connect(self.refresh_image)
        self.resolution_combo.currentIndexChanged.connect(self.refresh_image)
        self.mode_combo.currentIndexChanged.connect(self.refresh_image)
        QTimer.singleShot(80, self.refresh_image)

    def selected_channel_key(self) -> str:
        return str(self.channel_combo.currentData() or SUN_NOW_CHANNELS[0].key)

    def selected_resolution(self) -> int:
        return normalise_sun_resolution(self.resolution_combo.currentData())

    def selected_mode(self) -> str:
        return normalise_sun_mode(self.mode_combo.currentData())

    def refresh_image(self):
        if self.sun_worker is not None and self.sun_worker.isRunning():
            return

        channel = normalise_sun_channel(self.selected_channel_key())
        resolution = self.selected_resolution()
        mode = self.selected_mode()
        self._stop_media()
        self._preview_pixmap = None
        self._last_result = {}
        self.image_label.setPixmap(QPixmap())
        self.image_label.show()
        if self.video_widget is not None:
            self.video_widget.hide()
        self.image_label.setText(
            f"Loading {'recent movie for ' if mode == 'movie' else ''}{channel.label}…"
        )
        self.info_browser.setHtml(
            self._metadata_html(
                {
                    "label": channel.label,
                    "description": channel.description,
                    "interpretation": channel.interpretation,
                    "resolution": resolution if mode == "image" else "daily movie",
                    "mode": mode,
                    "status_note": (
                        "Loading NASA/SDO recent movie…"
                        if mode == "movie"
                        else "Loading latest NASA/SDO image…"
                    ),
                }
            )
        )
        self.status_label.setText("Loading…")
        self.progress_bar.show()
        self.open_source_button.setEnabled(False)
        self._set_controls_enabled(False)

        worker = SunNowWorker(channel.key, resolution, mode)
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
        self.news_browser.setHtml(self._news_html(result.get("news_items") or []))
        self.open_source_button.setEnabled(
            bool(result.get("source_url") or result.get("movie_url"))
        )
        self._show_result_media(result)

    def handle_sun_now_error(self, error: str):
        if self._close_after_worker:
            self.progress_bar.hide()
            self.status_label.setText("Closed")
            return
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self.status_label.setText("Failed")
        self.open_source_button.setEnabled(False)
        self._stop_media()
        self.image_label.show()
        if self.video_widget is not None:
            self.video_widget.hide()
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("SUN NOW image/movie could not be loaded.")
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

    def _show_result_media(self, result: dict[str, Any]):
        if str(result.get("mode") or "image") == "movie":
            self._show_media_path(
                str(result.get("media_path") or result.get("image_path") or ""), result
            )
        else:
            self._show_image_path(str(result.get("image_path") or ""))

    def _show_media_path(self, media_path: str, result: dict[str, Any]):
        path = Path(str(media_path or ""))
        if not path.exists():
            self._stop_media()
            self.image_label.show()
            if self.video_widget is not None:
                self.video_widget.hide()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                "No SDO movie file was returned. Use Open source to inspect the RSS feed."
            )
            return
        if QMediaPlayer is None or self.video_widget is None:
            self._stop_media()
            self.image_label.show()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                f"Recent SDO movie downloaded, but Qt Multimedia is unavailable.\n{path}"
            )
            self.image_label.setToolTip(str(path))
            return
        self.image_label.hide()
        self.video_widget.show()
        if self._media_player is None:
            self._media_player = QMediaPlayer(self)
            if QAudioOutput is not None:
                self._audio_output = QAudioOutput(self)
                self._audio_output.setMuted(True)
                self._media_player.setAudioOutput(self._audio_output)
            self._media_player.setVideoOutput(self.video_widget)
            try:
                self._media_player.mediaStatusChanged.connect(
                    self._handle_media_status_changed
                )
            except Exception:
                pass
        try:
            self._media_player.setSource(QUrl.fromLocalFile(str(path)))
        except Exception:
            self._media_player.setSource(QUrl(str(path)))
        try:
            self._media_player.setLoops(QMediaPlayer.Infinite)
        except Exception:
            pass
        self._media_player.play()
        self.video_widget.setToolTip(str(path))

    def _handle_media_status_changed(self, status):
        if QMediaPlayer is None or self._media_player is None:
            return
        try:
            if status == QMediaPlayer.EndOfMedia:
                self._media_player.setPosition(0)
                self._media_player.play()
        except Exception:
            pass

    def _stop_media(self):
        player = getattr(self, "_media_player", None)
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass

    def _show_image_path(self, image_path: str):
        self._stop_media()
        self.image_label.show()
        if self.video_widget is not None:
            self.video_widget.hide()
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
            self.mode_combo,
            self.refresh_button,
            self.open_source_button,
        ):
            widget.setEnabled(bool(enabled))
        self.open_source_button.setEnabled(
            bool(
                enabled
                and (
                    self._last_result.get("source_url")
                    or self._last_result.get("movie_url")
                )
            )
        )

    def open_source(self):
        url = str(
            self._last_result.get("source_url")
            or self._last_result.get("movie_url")
            or ""
        ).strip()
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
        mode = str(result.get("mode") or "image")
        cache_state = (
            "Cached fallback"
            if result.get("cache_used")
            else ("Live movie" if mode == "movie" else "Live image")
        )
        bytes_text = html.escape(_format_bytes(result.get("bytes")))
        source_url = html.escape(str(result.get("source_url") or ""))
        feed_url = html.escape(str(result.get("feed_url") or ""))
        movie_url = html.escape(str(result.get("movie_url") or ""))
        dashboard_url = html.escape(
            str(result.get("sdo_dashboard_url") or SDO_DASHBOARD_URL)
        )
        feeds_page_url = html.escape(
            str(result.get("sdo_feeds_page_url") or SDO_FEEDS_PAGE_URL)
        )

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
            <h2>Media</h2>
            <p><span class="k">Source:</span> <span class="v">{source}</span></p>
            <p><span class="k">Mode:</span> <span class="v">{html.escape(mode)}</span></p>
            <p><span class="k">Resolution:</span> <span class="v">{resolution} px</span></p>
            <p><span class="k">Downloaded:</span> <span class="v">{bytes_text}</span></p>
            <p><span class="k">HTTP time:</span> <span class="v">{last_modified}</span></p>
            <h2>Helioviewer metadata</h2>
            <p><span class="k">Closest image:</span> <span class="v">{helioviewer_date}</span></p>
            <p><span class="k">Image ID:</span> <span class="v">{helioviewer_id}</span></p>
            <h2>Source URLs</h2>
            <p><span class="k">Open:</span> <span class="url">{source_url or '—'}</span></p>
            <p><span class="k">Movie:</span> <span class="url">{movie_url or '—'}</span></p>
            <p><span class="k">Feed:</span> <span class="url">{feed_url or '—'}</span></p>
            <p><span class="k">Dashboard:</span> <span class="url">{dashboard_url}</span></p>
            <p><span class="k">Feeds page:</span> <span class="url">{feeds_page_url}</span></p>
        </body>
        </html>
        """

    def _news_html(self, items: Any) -> str:
        rows = []
        for item in list(items or [])[:10]:
            if not isinstance(item, dict):
                continue
            title = html.escape(str(item.get("title") or "Solar update"))
            source = html.escape(str(item.get("source") or "Feed"))
            published = html.escape(str(item.get("published") or ""))
            summary = html.escape(str(item.get("summary") or ""))
            link = html.escape(str(item.get("link") or item.get("media_url") or ""))
            link_html = f'<p><a href="{link}">Open source</a></p>' if link else ""
            rows.append(
                '<div class="item">'
                f'<div class="item-title">{title}</div>'
                f'<div class="item-meta">{source}{" · " if published else ""}{published}</div>'
                f'<div class="item-summary">{summary or "No summary returned."}</div>'
                f"{link_html}"
                "</div>"
            )
        if not rows:
            rows.append(
                '<div class="item"><div class="item-title">No solar alerts/news loaded yet.</div><div class="item-summary">Refresh SUN NOW to load SDO Mission Blog and NOAA SWPC feed items.</div></div>'
            )
        return f"""
        <html><head><style>
            body {{ background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; margin:0; }}
            a {{ color:#8fc7ff; }}
            .item {{ border:1px solid #26313d; border-radius:10px; background:#111820; padding:7px; margin:0 0 7px 0; }}
            .item-title {{ color:#f2f7fc; font-size:12px; font-weight:850; }}
            .item-meta {{ color:#91a8bf; font-size:10px; margin:2px 0 4px 0; }}
            .item-summary {{ color:#c3ced9; line-height:1.3; }}
        </style></head><body>{''.join(rows)}</body></html>
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
        self._stop_media()
        super().reject()

    def closeEvent(self, event):
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self._set_controls_enabled(False)
            event.ignore()
            return
        self._stop_media()
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

from __future__ import annotations

import html
from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)

from .window_utils import apply_window_defaults

try:  # Optional on lean PySide6 installs and some CI containers.
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - depends on optional QtWebEngine package
    QWebEngineView = None  # type: ignore[assignment]

try:  # Optional on lean PySide6 installs and some CI containers.
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
except Exception:  # pragma: no cover - depends on optional QtWebEngine package
    QWebEngineProfile = None  # type: ignore[assignment]
    QWebEngineSettings = None  # type: ignore[assignment]


@dataclass(frozen=True)
class IssLiveSource:
    key: str
    label: str
    source_name: str
    watch_url: str
    embed_url: str
    description: str
    note: str
    embed_kind: str = "youtube"


SPACE_LIVE_TITLE = "SPACE LIVE"
NASA_YOUTUBE_CHANNEL_ID = "UCLA_DiR1FfKNvjuUpBHmylQ"
NASA_ISS_HD_VIDEO_ID = "MuHIx2q0Wjs"
NASA_ISS_LIVE_VIDEO_ID = "uwXgcTc8oY8"
NASA_ISS_LIVE_WATCH_URL = "https://www.youtube.com/watch?v=uwXgcTc8oY8"
NASA_YOUTUBE_LIVE_URL = "https://www.youtube.com/nasa/live"
SEN_YOUTUBE_LIVE_URL = "https://www.youtube.com/@Sen/live"
SEN_SPACE_TV_URL = "https://www.sen.com/"
ESA_WEB_TV_URL = "https://watch.esa.int/"
ESA_YOUTUBE_LIVE_URL = "https://www.youtube.com/esa/live"
NOAA_GOES_URL = "https://www.goes.noaa.gov/"
NASA_LIVE_URL = "https://www.nasa.gov/live/"
YOUTUBE_REFERRER_ORIGIN = "https://www.nasa.gov/"
YOUTUBE_EMBED_ARGS = (
    "autoplay=1&mute=1&controls=1&rel=0&modestbranding=1"
    "&playsinline=1&enablejsapi=1&origin=https%3A%2F%2Fwww.nasa.gov"
)


ISS_LIVE_SOURCES: tuple[IssLiveSource, ...] = (
    IssLiveSource(
        key="nasa_iss_hd_views",
        label="NASA ISS HD Earth views",
        source_name="NASA official YouTube stream",
        watch_url=f"https://www.youtube.com/watch?v={NASA_ISS_HD_VIDEO_ID}",
        embed_url=f"https://www.youtube-nocookie.com/embed/{NASA_ISS_HD_VIDEO_ID}?{YOUTUBE_EMBED_ARGS}",
        description="Live high-definition exterior Earth views from the International Space Station when the official feed is active.",
        note="Verified working embedded source from user testing. During orbital night, Ku-band handovers, or operational interruptions it may still show black/blue screens or holding graphics.",
    ),
    IssLiveSource(
        key="sen_spacetv1_4k",
        label="Sen SpaceTV-1 4K Earth live",
        source_name="Sen SpaceTV-1 official web stream",
        watch_url=SEN_SPACE_TV_URL,
        embed_url=SEN_SPACE_TV_URL,
        description="Continuous 4K Earth-view livestream from Sen SpaceTV-1 cameras onboard the International Space Station, when station communications allow.",
        note="This loads the official Sen web player instead of a fixed YouTube video ID, so it is less likely to go stale. Use Open source if the embedded page blocks playback.",
        embed_kind="web",
    ),
    IssLiveSource(
        key="sen_youtube_live",
        label="Sen YouTube 4K live",
        source_name="Sen YouTube live channel",
        watch_url=SEN_YOUTUBE_LIVE_URL,
        embed_url=SEN_YOUTUBE_LIVE_URL,
        description="Sen's YouTube live entry point for its 4K Earth-from-space stream.",
        note="Kept as an external/links source because channel-live embeds can be unreliable inside Qt WebEngine.",
        embed_kind="links",
    ),
    IssLiveSource(
        key="nasa_live_events",
        label="NASA Live / NASA+ events",
        source_name="NASA Live",
        watch_url=NASA_LIVE_URL,
        embed_url=NASA_LIVE_URL,
        description="NASA live-event schedule, NASA+ programming, launches, briefings, landings, and Space Station live-view fallbacks.",
        note="Shown as a dark in-app links page rather than embedding the bright full NASA page inside the dark workspace.",
        embed_kind="links",
    ),
    IssLiveSource(
        key="esa_web_tv",
        label="ESA Web TV live events",
        source_name="ESA Web TV",
        watch_url=ESA_WEB_TV_URL,
        embed_url=ESA_WEB_TV_URL,
        description="ESA Web TV live transmissions, mission events, launches, and scheduled European space programming.",
        note="Loads ESA's official Web TV page directly. Use Open source if the embedded page blocks playback or sign-in/cookie handling.",
        embed_kind="web",
    ),
    IssLiveSource(
        key="esa_youtube_live",
        label="ESA YouTube live/events",
        source_name="ESA YouTube live channel",
        watch_url=ESA_YOUTUBE_LIVE_URL,
        embed_url=ESA_YOUTUBE_LIVE_URL,
        description="ESA YouTube live/events entry point for mission coverage and official broadcasts.",
        note="Kept as an external/links source because channel-live embeds can be unreliable inside Qt WebEngine.",
        embed_kind="links",
    ),
    IssLiveSource(
        key="noaa_goes_earth_now",
        label="NOAA GOES Earth imagery",
        source_name="NOAA / NESDIS / STAR GOES Imagery Viewer",
        watch_url=NOAA_GOES_URL,
        embed_url=NOAA_GOES_URL,
        description="Near-real-time GOES-East and GOES-West satellite imagery and animation products for Earth weather, storms, full-disk views, and sectors.",
        note="This is not an ISS video stream. It is a live/near-real-time Earth imagery viewer and is useful enough to keep in SPACE LIVE.",
        embed_kind="web",
    ),
)

ISS_SOURCE_BY_KEY = {source.key: source for source in ISS_LIVE_SOURCES}


def normalise_iss_source(value: str | None) -> IssLiveSource:
    key = str(value or "").strip()
    return ISS_SOURCE_BY_KEY.get(key, ISS_LIVE_SOURCES[0])


class IssLiveDialog(QDialog):
    """Space live viewer with ISS, Earth, NASA, ESA, and GOES sources."""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_window_defaults(self)
        self._web_view = None
        self._current_source = ISS_LIVE_SOURCES[0]

        self.setObjectName("issLiveDialog")
        self.setWindowTitle(SPACE_LIVE_TITLE)
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

        title = QLabel(SPACE_LIVE_TITLE)
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Live space and Earth sources: verified NASA ISS views, Sen SpaceTV-1, NASA/ESA event links, and NOAA GOES imagery."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        controls_card = QFrame()
        controls_card.setObjectName("astroLookupSettingsCard")
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(9)

        source_caption = QLabel("Source")
        source_caption.setObjectName("toolbarCaption")
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("astroLookupCombo")
        for source in ISS_LIVE_SOURCES:
            self.source_combo.addItem(source.label, source.key)
        self.source_combo.setMinimumWidth(420)
        self.source_combo.setToolTip(
            "Select a verified embedded video, official web source, or dark in-app official links page."
        )

        self.status_label = QLabel("Select a live space or Earth source")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.reload_button = QPushButton("Reload")
        self.reload_button.setObjectName("primaryActionButton")
        self.reload_button.clicked.connect(self.reload_source)

        self.open_source_button = QPushButton("Open source")
        self.open_source_button.setToolTip(
            "Open the selected official source in your normal browser if embedded playback is unavailable."
        )
        self.open_source_button.clicked.connect(self.open_source)

        controls_layout.addWidget(source_caption, 0, Qt.AlignVCenter)
        controls_layout.addWidget(self.source_combo, 1)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.status_label, 0, Qt.AlignVCenter)
        controls_layout.addWidget(self.reload_button)
        controls_layout.addWidget(self.open_source_button)

        result_card = QFrame()
        result_card.setObjectName("astroLookupResultCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("astroLookupResultSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)

        media_panel = QFrame()
        media_panel.setObjectName("astroLookupImagePanel")
        media_layout = QVBoxLayout(media_panel)
        media_layout.setContentsMargins(9, 9, 9, 9)
        media_layout.setSpacing(6)
        self.media_title = QLabel("Space live feed")
        self.media_title.setObjectName("astroLookupSectionTitle")
        media_layout.addWidget(self.media_title)

        if QWebEngineView is not None:
            try:
                self._web_view = QWebEngineView(media_panel)
                self._web_view.setObjectName("astroLookupImagePreview")
                self._configure_web_view(self._web_view)
                self._web_view.setSizePolicy(
                    QSizePolicy.Expanding, QSizePolicy.Expanding
                )
                self._web_view.setMinimumSize(720, 500)
                self._web_view.loadStarted.connect(
                    lambda: self.status_label.setText("Loading source...")
                )
                self._web_view.loadFinished.connect(self._handle_load_finished)
                media_layout.addWidget(self._web_view, 1)
            except Exception:
                self._web_view = None

        if self._web_view is None:
            self.fallback_browser = QTextBrowser()
            self.fallback_browser.setObjectName("astroLookupDetailsBrowser")
            self.fallback_browser.setOpenExternalLinks(True)
            self.fallback_browser.setMinimumSize(720, 500)
            media_layout.addWidget(self.fallback_browser, 1)
        else:
            self.fallback_browser = None

        self.splitter.addWidget(media_panel)

        details_panel = QFrame()
        details_panel.setObjectName("astroLookupImagePanel")
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(9, 9, 9, 9)
        details_layout.setSpacing(6)
        details_title = QLabel("Source details")
        details_title.setObjectName("astroLookupSectionTitle")
        self.details_tabs = QTabWidget()
        self.details_tabs.setObjectName("astroLookupDetailsTabs")
        self.info_browser = QTextBrowser()
        self.links_browser = QTextBrowser()
        for browser in (self.info_browser, self.links_browser):
            browser.setObjectName("astroLookupDetailsBrowser")
            browser.setOpenExternalLinks(True)
        self.details_tabs.addTab(self.info_browser, "Info")
        self.details_tabs.addTab(self.links_browser, "Links")
        details_layout.addWidget(details_title)
        details_layout.addWidget(self.details_tabs, 1)
        self.splitter.addWidget(details_panel)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([900, 360])
        result_layout.addWidget(self.splitter, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.Close)
        button_row.rejected.connect(self.reject)

        layout.addWidget(header_card)
        layout.addWidget(controls_card)
        layout.addWidget(result_card, 1)
        layout.addWidget(button_row)

        self.source_combo.currentIndexChanged.connect(self.reload_source)
        self.reload_source()

    def selected_source(self) -> IssLiveSource:
        return normalise_iss_source(self.source_combo.currentData())

    def reload_source(self):
        self._current_source = self.selected_source()
        source = self._current_source
        self.media_title.setText(f"{source.label} feed")
        if self._web_view is not None:
            if source.embed_kind == "youtube":
                self._web_view.setHtml(
                    self._youtube_embed_html(source), QUrl(YOUTUBE_REFERRER_ORIGIN)
                )
            elif source.embed_kind == "web":
                self._web_view.load(QUrl(source.embed_url))
            else:
                self._web_view.setHtml(
                    self._official_links_landing_html(source), QUrl(source.watch_url)
                )
        elif self.fallback_browser is not None:
            self.fallback_browser.setHtml(self._fallback_html(source))
        self.info_browser.setHtml(self._info_html(source))
        self.links_browser.setHtml(self._links_html(source))
        self.status_label.setText(
            "Loaded" if self._web_view is None else "Loading source..."
        )

    def _handle_load_finished(self, ok: bool):
        if not ok:
            self.status_label.setText("Source load failed - use Open source")
            return
        source = self._current_source or self.selected_source()
        if source.embed_kind == "youtube":
            self.status_label.setText(
                "Embedded player loaded - Open source if unavailable"
            )
        elif source.embed_kind == "web":
            self.status_label.setText("Official web source loaded")
        else:
            self.status_label.setText("Official links loaded")

    def open_source(self):
        source = self._current_source or self.selected_source()
        QDesktopServices.openUrl(QUrl(source.watch_url))

    def _configure_web_view(self, view):
        """Reduce common WebEngine failures for official video/web embeds."""
        try:
            if QWebEngineProfile is not None:
                view.page().profile().setHttpUserAgent(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
        except Exception:
            pass
        try:
            settings = view.settings()
            if QWebEngineSettings is not None:
                settings.setAttribute(
                    QWebEngineSettings.PlaybackRequiresUserGesture, False
                )
                settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
                settings.setAttribute(
                    QWebEngineSettings.LocalContentCanAccessRemoteUrls, True
                )
        except Exception:
            pass

    def _youtube_embed_html(self, source: IssLiveSource) -> str:
        """Load YouTube inside an origin/referrer-aware wrapper."""
        return f"""
        <!doctype html>
        <html><head>
            <meta charset="utf-8">
            <meta name="referrer" content="strict-origin-when-cross-origin">
            <style>
                html, body {{ background:#000; color:#e8edf2; height:100%; margin:0; overflow:hidden; }}
                .wrap {{ position:fixed; inset:0; background:#000; }}
                iframe {{ border:0; width:100%; height:100%; background:#000; }}
                .fallback {{ position:fixed; left:12px; bottom:12px; z-index:2; font:11px 'Segoe UI', sans-serif; color:#c8d6e2; background:rgba(8,12,18,.72); border:1px solid rgba(140,170,200,.35); border-radius:10px; padding:7px 9px; }}
                .fallback a {{ color:#8fc7ff; text-decoration:none; font-weight:800; }}
                .badge {{ position:fixed; right:12px; top:12px; z-index:2; font:11px 'Segoe UI', sans-serif; color:#cfe4ff; background:rgba(8,12,18,.72); border:1px solid rgba(140,170,200,.35); border-radius:10px; padding:7px 9px; }}
            </style>
        </head><body>
            <div class="wrap">
                <iframe
                    src="{html.escape(source.embed_url, quote=True)}"
                    title="{html.escape(source.label, quote=True)}"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
                    allowfullscreen
                    referrerpolicy="strict-origin-when-cross-origin"></iframe>
            </div>
            <div class="badge">SPACE LIVE video source</div>
            <div class="fallback">If the embedded player is unavailable, use <a href="{html.escape(source.watch_url, quote=True)}">Open source</a>.</div>
        </body></html>
        """

    def _official_links_landing_html(self, source: IssLiveSource) -> str:
        return f"""
        <html><head><style>{self._base_style()}</style></head><body>
            <div class="item">
                <h1>{html.escape(source.label)}</h1>
                <div class="pill">Official source links</div>
                <p>{html.escape(source.description)}</p>
                <p class="note">This source is kept as a clean in-app link panel because channel-live embeds can be unreliable inside Qt WebEngine.</p>
                <p><a href="{html.escape(source.watch_url)}">Open selected source</a></p>
            </div>
            {self._all_source_link_items()}
        </body></html>
        """

    def _base_style(self) -> str:
        return """
            body { background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; margin:0; line-height:1.35; }
            h1 { color:#ffffff; font-size:16px; margin:0 0 7px 0; }
            h2 { color:#eef3f8; font-size:12px; margin:10px 0 4px 0; }
            p { margin:4px 0; }
            a { color:#8fc7ff; }
            .pill { display:inline-block; color:#cfe4ff; background:#111a23; border:1px solid #2a3948; border-radius:8px; padding:3px 6px; font-weight:800; margin:0 0 6px 0; }
            .note { color:#aeb9c5; }
            .item { border:1px solid #26313d; border-radius:10px; background:#111820; padding:7px; margin:0 0 7px 0; }
        """

    def _fallback_html(self, source: IssLiveSource) -> str:
        return f"""
        <html><head><style>{self._base_style()}</style></head><body>
            <h1>{html.escape(source.label)}</h1>
            <div class="pill">Browser playback unavailable</div>
            <p>Qt WebEngine is not available in this build, so the source cannot be embedded here.</p>
            <p><a href="{html.escape(source.watch_url)}">Open official source</a></p>
            <p class="note">{html.escape(source.note)}</p>
        </body></html>
        """

    def _info_html(self, source: IssLiveSource) -> str:
        if self._web_view is None:
            webengine_state = "External-link fallback"
        elif source.embed_kind == "youtube":
            webengine_state = "Embedded video playback"
        elif source.embed_kind == "web":
            webengine_state = "Official web source"
        else:
            webengine_state = "Official links panel"
        return f"""
        <html><head><style>{self._base_style()}</style></head><body>
            <h1>{html.escape(source.label)}</h1>
            <div class="pill">{html.escape(webengine_state)}</div>
            <h2>Source</h2>
            <p>{html.escape(source.source_name)}</p>
            <h2>What this shows</h2>
            <p>{html.escape(source.description)}</p>
            <h2>Operational note</h2>
            <p class="note">{html.escape(source.note)}</p>
        </body></html>
        """

    def _source_item_html(self, source: IssLiveSource) -> str:
        kind = {
            "youtube": "embedded video",
            "web": "official web source",
            "links": "external/link source",
        }.get(source.embed_kind, source.embed_kind)
        return (
            f'<div class="item"><b>{html.escape(source.label)}</b><br>'
            f'<span class="note">{html.escape(kind)} - {html.escape(source.source_name)}</span><br>'
            f'<a href="{html.escape(source.watch_url)}">{html.escape(source.watch_url)}</a></div>'
        )

    def _all_source_link_items(self) -> str:
        extras = [
            (
                "NASA ISS live video",
                NASA_ISS_LIVE_WATCH_URL,
                "External only: user testing showed this source unavailable inside Qt WebEngine.",
            ),
            (
                "NASA YouTube live channel",
                NASA_YOUTUBE_LIVE_URL,
                "External only: channel-live embeds are unreliable inside Qt WebEngine.",
            ),
            (
                "Spot the Station",
                "https://www.nasa.gov/spot-the-station/",
                "NASA station visibility and pass information.",
            ),
            (
                "International Space Station",
                "https://www.nasa.gov/international-space-station/",
                "NASA ISS mission page.",
            ),
        ]
        source_items = "\n".join(
            self._source_item_html(source) for source in ISS_LIVE_SOURCES
        )
        extra_items = "\n".join(
            f'<div class="item"><b>{html.escape(label)}</b><br><span class="note">{html.escape(note)}</span><br><a href="{html.escape(url)}">{html.escape(url)}</a></div>'
            for label, url, note in extras
        )
        return source_items + "\n" + extra_items

    def _links_html(self, source: IssLiveSource) -> str:
        return f"""
        <html><head><style>{self._base_style()}</style></head><body>
            <h1>SPACE LIVE source links</h1>
            <div class="item"><b>{html.escape(source.label)}</b><br><a href="{html.escape(source.watch_url)}">Open selected source</a></div>
            {self._all_source_link_items()}
        </body></html>
        """


def show_iss_live_dialog(parent=None):
    if parent is not None and hasattr(parent, "open_workspace_tab"):
        return parent.open_workspace_tab(
            "astro.space_live",
            SPACE_LIVE_TITLE,
            lambda: IssLiveDialog(parent),
            tooltip="Live space and Earth streams, including ISS, Sen SpaceTV-1, NASA/ESA events, and NOAA GOES imagery",
        )
    dialog = IssLiveDialog(parent)
    return dialog.exec()


# New name for callers that do not need the legacy ISS-specific method name.
show_space_live_dialog = show_iss_live_dialog

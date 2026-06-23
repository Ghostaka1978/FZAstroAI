from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
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


FZASTRO_LIVE_TITLE = "FZASTRO LIVE"
FZASTRO_LIVE_URL = "https://www.fzastro.com/"


class FZAstroLiveDialog(QDialog):
    """Single-site live viewer for the user's FZAstro website."""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_window_defaults(self)
        self._web_view = None

        self.setObjectName("fzastroLiveDialog")
        self.setWindowTitle(FZASTRO_LIVE_TITLE)
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

        title = QLabel(FZASTRO_LIVE_TITLE)
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel("Embedded viewer for your live FZAstro website.")
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        controls_card = QFrame()
        controls_card.setObjectName("astroLookupSettingsCard")
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(9)

        source_caption = QLabel("Website")
        source_caption.setObjectName("toolbarCaption")
        self.url_label = QLabel(FZASTRO_LIVE_URL)
        self.url_label.setObjectName("astroLookupStatusLabel")
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.reload_button = QPushButton("Reload")
        self.reload_button.setObjectName("primaryActionButton")
        self.reload_button.clicked.connect(self.reload_site)

        self.open_source_button = QPushButton("Open website")
        self.open_source_button.setToolTip(
            "Open https://www.fzastro.com/ in your normal browser."
        )
        self.open_source_button.clicked.connect(self.open_website)

        controls_layout.addWidget(source_caption, 0, Qt.AlignVCenter)
        controls_layout.addWidget(self.url_label, 1, Qt.AlignVCenter)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.status_label, 0, Qt.AlignVCenter)
        controls_layout.addWidget(self.reload_button)
        controls_layout.addWidget(self.open_source_button)

        viewer_card = QFrame()
        viewer_card.setObjectName("astroLookupResultCard")
        viewer_layout = QVBoxLayout(viewer_card)
        viewer_layout.setContentsMargins(12, 12, 12, 12)
        viewer_layout.setSpacing(8)

        self.viewer_title = QLabel("FZAstro website")
        self.viewer_title.setObjectName("astroLookupSectionTitle")
        viewer_layout.addWidget(self.viewer_title)

        if QWebEngineView is not None:
            try:
                self._web_view = QWebEngineView(viewer_card)
                self._web_view.setObjectName("fzastroLiveWebView")
                self._web_view.setSizePolicy(
                    QSizePolicy.Expanding, QSizePolicy.Expanding
                )
                self._configure_web_view(self._web_view)
                self._web_view.loadFinished.connect(self._handle_load_finished)
                viewer_layout.addWidget(self._web_view, 1)
            except Exception:  # pragma: no cover - depends on local Qt WebEngine
                self._web_view = None

        if self._web_view is None:
            self.fallback_browser = QTextBrowser()
            self.fallback_browser.setObjectName("astroLookupResultBrowser")
            self.fallback_browser.setOpenExternalLinks(True)
            self.fallback_browser.setHtml(self._fallback_html())
            viewer_layout.addWidget(self.fallback_browser, 1)
        else:
            self.fallback_browser = None

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)

        layout.addWidget(header_card)
        layout.addWidget(controls_card)
        layout.addWidget(viewer_card, 1)
        layout.addWidget(button_box)

        self.reload_site()

    def reload_site(self):
        if self._web_view is not None:
            self.status_label.setText("Loading website...")
            self._web_view.load(QUrl(FZASTRO_LIVE_URL))
        elif self.fallback_browser is not None:
            self.status_label.setText("Browser fallback")
            self.fallback_browser.setHtml(self._fallback_html())

    def open_website(self):
        QDesktopServices.openUrl(QUrl(FZASTRO_LIVE_URL))

    def _handle_load_finished(self, ok: bool):
        self.status_label.setText(
            "Website loaded" if ok else "Website load failed - use Open website"
        )

    def _configure_web_view(self, view):
        """Apply the same resilient WebEngine settings used by live viewers."""
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

    def _base_style(self) -> str:
        return """
            body { background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; margin:0; line-height:1.35; }
            h1 { color:#ffffff; font-size:18px; margin:0 0 7px 0; }
            p { margin:5px 0; }
            a { color:#8fc7ff; }
            .pill { display:inline-block; color:#cfe4ff; background:#111a23; border:1px solid #2a3948; border-radius:8px; padding:3px 6px; font-weight:800; margin:0 0 6px 0; }
            .item { border:1px solid #26313d; border-radius:10px; background:#111820; padding:9px; margin:0 0 7px 0; }
            .note { color:#aeb9c5; }
        """

    def _fallback_html(self) -> str:
        return f"""
        <html><head><style>{self._base_style()}</style></head><body>
            <div class="item">
                <h1>{html.escape(FZASTRO_LIVE_TITLE)}</h1>
                <div class="pill">Browser playback unavailable</div>
                <p>Qt WebEngine is not available in this build, so the website cannot be embedded here.</p>
                <p><a href="{html.escape(FZASTRO_LIVE_URL)}">Open {html.escape(FZASTRO_LIVE_URL)}</a></p>
                <p class="note">This app intentionally loads only one site.</p>
            </div>
        </body></html>
        """


def show_fzastro_live_dialog(parent=None):
    if parent is not None and hasattr(parent, "open_workspace_tab"):
        return parent.open_workspace_tab(
            "astro.fzastro_live",
            FZASTRO_LIVE_TITLE,
            lambda: FZAstroLiveDialog(parent),
            tooltip="Embedded viewer for https://www.fzastro.com/",
        )
    dialog = FZAstroLiveDialog(parent)
    return dialog.exec()

"""Qt terminal host used by the embedded OpenClaude workspace.

The preferred frontend is a real browser-hosted terminal renderer (xterm.js)
connected to a Windows ConPTY/pywinpty backend.  When Qt WebEngine or local
xterm assets are unavailable, the widget falls back to a basic transcript view
so the application still starts and reports the missing frontend clearly.
"""

from __future__ import annotations

import importlib.resources as resources
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

try:  # Optional: PySide6 Addons / WebEngine may not be installed in all test envs.
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - exercised on machines without WebEngine.
    QWebChannel = None  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]


class _TerminalBridge(QObject):
    """Bridge used by the WebEngine terminal frontend."""

    input_received = Signal(str)
    resized = Signal(int, int)
    frontend_ready = Signal(str)

    @Slot(str)
    def sendInput(self, data: str) -> None:  # noqa: N802 - called from JavaScript
        self.input_received.emit(str(data or ""))

    @Slot(int, int)
    def resizeTerminal(self, cols: int, rows: int) -> None:  # noqa: N802
        self.resized.emit(int(cols), int(rows))

    @Slot(str)
    def frontendReady(self, mode: str) -> None:  # noqa: N802
        self.frontend_ready.emit(str(mode or "unknown"))


def _terminal_html_path() -> Path | None:
    try:
        resource = resources.files("fzastro_ai.resources.terminal").joinpath(
            "fzastro_terminal.html"
        )
        path = Path(str(resource))
        if path.exists():
            return path
    except Exception:
        pass
    fallback = (
        Path(__file__).resolve().parents[1]
        / "resources"
        / "terminal"
        / "fzastro_terminal.html"
    )
    return fallback if fallback.exists() else None


class OpenClaudeTerminalWidget(QWidget):
    """Terminal renderer with optional xterm.js frontend and text fallback."""

    input_received = Signal(str)
    resized = Signal(int, int)
    frontend_ready = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.frontend_name = "text-fallback"
        self._web_view: Any | None = None
        self._channel: Any | None = None
        self._bridge: _TerminalBridge | None = None
        self._text_view: QPlainTextEdit | None = None
        self._web_ready = False
        self._pending_output: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        html_path = _terminal_html_path()
        if (
            QWebEngineView is not None
            and QWebChannel is not None
            and html_path is not None
        ):
            self.frontend_name = "web-terminal"
            self._bridge = _TerminalBridge(self)
            self._bridge.input_received.connect(self.input_received)
            self._bridge.resized.connect(self.resized)
            self._bridge.frontend_ready.connect(self._on_frontend_ready)
            self._channel = QWebChannel(self)
            self._channel.registerObject("fzTerminalBridge", self._bridge)
            self._web_view = QWebEngineView(self)
            self._web_view.page().setWebChannel(self._channel)
            self._web_view.load(QUrl.fromLocalFile(str(html_path)))
            self._web_view.loadFinished.connect(self._on_load_finished)
            layout.addWidget(self._web_view)
        else:
            self._install_text_fallback(layout, html_path)

    def _install_text_fallback(
        self, layout: QVBoxLayout, html_path: Path | None
    ) -> None:
        self.frontend_name = "text-fallback"
        self._text_view = QPlainTextEdit(self)
        self._text_view.setReadOnly(True)
        self._text_view.setObjectName("embeddedClaudeTerminal")
        self._text_view.setFont(QFont("Cascadia Mono", 10))
        self._text_view.setPlaceholderText(
            "Qt WebEngine/xterm.js terminal frontend is unavailable. Output transcript appears here."
        )
        try:
            self._text_view.document().setMaximumBlockCount(5000)
        except Exception:
            pass
        layout.addWidget(self._text_view)
        reason = (
            "Qt WebEngine is unavailable"
            if QWebEngineView is None
            else "terminal html is missing"
        )
        self.append_output(f"[fzastro] real terminal frontend unavailable: {reason}.\n")
        if html_path is None:
            self.append_output(
                "[fzastro] missing fzastro_ai/resources/terminal/fzastro_terminal.html\n"
            )
        self.frontend_ready.emit(self.frontend_name)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self.frontend_name = "web-load-failed"
            self._web_ready = False
            self.frontend_ready.emit(self.frontend_name)

    def _on_frontend_ready(self, mode: str) -> None:
        self.frontend_name = str(mode or "web-terminal")
        self._web_ready = True
        self.frontend_ready.emit(self.frontend_name)
        pending = "".join(self._pending_output)
        self._pending_output.clear()
        if pending:
            self.append_output(pending)
        self.focus_terminal()

    def _run_js(self, expression: str) -> None:
        if self._web_view is None or not self._web_ready:
            return
        try:
            self._web_view.page().runJavaScript(expression)
        except Exception:
            pass

    def append_output(self, text: str) -> None:
        payload = str(text or "")
        if not payload:
            return
        if self._web_view is not None:
            if not self._web_ready:
                self._pending_output.append(payload)
                return
            self._run_js(f"window.fztermWrite({json.dumps(payload)});")
            return
        if self._text_view is not None:
            self._text_view.moveCursor(QTextCursor.End)
            self._text_view.insertPlainText(payload)
            self._text_view.moveCursor(QTextCursor.End)

    def clear(self) -> None:  # noqa: A003 - Qt-like widget method name
        self._pending_output.clear()
        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermClear();")
        if self._text_view is not None:
            self._text_view.clear()

    def focus_terminal(self) -> None:
        if self._web_view is not None:
            self._web_view.setFocus()
            if self._web_ready:
                self._run_js("window.fztermFocus();")
        elif self._text_view is not None:
            self._text_view.setFocus()

    def fit(self) -> None:
        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermFit();")

    def is_real_terminal(self) -> bool:
        return self.frontend_name == "xterm.js"

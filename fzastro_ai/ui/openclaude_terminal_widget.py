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

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QContextMenuEvent,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractSlider,
    QMenu,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

try:  # Optional: PySide6 Addons / WebEngine may not be installed in all test envs.
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - exercised on machines without WebEngine.
    QWebChannel = None  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]


class _TerminalFallbackEdit(QPlainTextEdit):
    """Plain-text terminal fallback with predictable copy/paste shortcuts.

    The WebEngine/xterm frontend is the real terminal path.  This fallback is
    still interactive enough for machines without WebEngine: selected text is
    copied with Ctrl+C/Ctrl+Shift+C, clipboard text is pasted into the PTY with
    Ctrl+V/Ctrl+Shift+V, and Ctrl+C with no selection remains a terminal
    interrupt.
    """

    input_received = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def _clipboard_text(self) -> str:
        clipboard = QGuiApplication.clipboard()
        return clipboard.text() if clipboard is not None else ""

    def _has_selection(self) -> bool:
        try:
            return bool(self.textCursor().hasSelection())
        except Exception:
            return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        key = event.key()
        modifiers = event.modifiers()
        ctrl_or_meta = bool(
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )

        if ctrl_or_meta and key in (Qt.Key.Key_C, Qt.Key.Key_Insert):
            if self._has_selection():
                self.copy()
            else:
                self.input_received.emit("\x03")
            event.accept()
            return

        if (ctrl_or_meta and key == Qt.Key.Key_V) or (
            bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            and key == Qt.Key.Key_Insert
        ):
            text = self._clipboard_text()
            if text:
                self.input_received.emit(text)
            event.accept()
            return

        terminal_sequences = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
            Qt.Key.Key_Escape: "\x1b",
        }
        sequence = terminal_sequences.get(key)
        if sequence is not None:
            self.input_received.emit(sequence)
            event.accept()
            return

        text = event.text()
        if text and not bool(modifiers & Qt.KeyboardModifier.AltModifier):
            self.input_received.emit(text)
            event.accept()
            return

        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self._has_selection())
        paste_action = menu.addAction("Paste")
        select_all_action = menu.addAction("Select All")
        action = menu.exec(event.globalPos())
        if action == copy_action:
            self.copy()
        elif action == paste_action:
            text = self._clipboard_text()
            if text:
                self.input_received.emit(text)
        elif action == select_all_action:
            self.selectAll()


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

    @Slot(result=str)
    def clipboardText(self) -> str:  # noqa: N802 - called from JavaScript
        clipboard = QGuiApplication.clipboard()
        return clipboard.text() if clipboard is not None else ""

    @Slot(str)
    def setClipboardText(
        self, text: str
    ) -> None:  # noqa: N802 - called from JavaScript
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text or ""))


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
        self._text_view = _TerminalFallbackEdit(self)
        self._text_view.input_received.connect(self.input_received)
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
            scroll_bar = self._text_view.verticalScrollBar()
            old_value = scroll_bar.value()
            follow = old_value >= max(0, scroll_bar.maximum() - 2)
            edit_cursor = QTextCursor(self._text_view.document())
            edit_cursor.movePosition(QTextCursor.End)
            edit_cursor.insertText(payload)
            if follow:
                self._text_view.moveCursor(QTextCursor.End)
            else:
                # Keep the user's scrollback position instead of forcing the
                # transcript back to the live tail on every PTY chunk.
                scroll_bar.setValue(old_value)

    def paste_text(self, text: str) -> None:
        """Paste clipboard text into the interactive terminal session."""

        payload = str(text or "")
        if not payload:
            return
        if self._web_view is not None and self._web_ready:
            self._run_js(f"window.fztermPasteText({json.dumps(payload)});")
            return
        self.input_received.emit(payload)

    def scroll_page_up(self) -> None:
        """Move the visible terminal scrollback up by one page."""

        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermScrollPageUp();")
            return
        if self._text_view is not None:
            self._text_view.verticalScrollBar().triggerAction(
                QAbstractSlider.SliderPageStepSub
            )

    def scroll_page_down(self) -> None:
        """Move the visible terminal scrollback down by one page."""

        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermScrollPageDown();")
            return
        if self._text_view is not None:
            self._text_view.verticalScrollBar().triggerAction(
                QAbstractSlider.SliderPageStepAdd
            )

    def scroll_to_top(self) -> None:
        """Jump to the oldest retained OpenClaude terminal scrollback."""

        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermScrollTop();")
            return
        if self._text_view is not None:
            self._text_view.verticalScrollBar().setValue(0)

    def scroll_to_bottom(self) -> None:
        """Resume live follow mode at the end of the terminal output."""

        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermScrollBottom();")
            return
        if self._text_view is not None:
            self._text_view.moveCursor(QTextCursor.End)

    def copy_selection(self) -> None:
        """Copy selected terminal text where the active frontend supports it."""

        if self._web_view is not None and self._web_ready:
            self._run_js("window.fztermCopySelection();")
            return
        if self._text_view is not None:
            self._text_view.copy()

    def save_screenshot(self, path: Path) -> bool:
        """Save a PNG capture of the visible terminal widget."""

        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        pixmap = self.grab()
        if pixmap.isNull():
            return False
        return bool(pixmap.save(str(target), "PNG"))

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

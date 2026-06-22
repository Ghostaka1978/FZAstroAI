from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QWidget


def center_window_on_screen(window: QWidget) -> None:
    """Move a top-level window to the center of its parent/current screen."""
    try:
        if window is None:
            return
        parent = window.parentWidget()
        screen = None
        try:
            if parent is not None and parent.screen() is not None:
                screen = parent.screen()
        except Exception:
            screen = None
        if screen is None:
            try:
                screen = window.screen()
            except Exception:
                screen = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        frame = window.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        window.move(frame.topLeft())
    except Exception:
        # Window positioning should never prevent a dialog from opening.
        return


def apply_fzastro_window_palette(window: QWidget) -> None:
    """Apply the shared dark desktop palette to app-owned top-level windows."""
    try:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#101318"))
        palette.setColor(QPalette.WindowText, QColor("#e8ebef"))
        palette.setColor(QPalette.Base, QColor("#0f1318"))
        palette.setColor(QPalette.AlternateBase, QColor("#15191f"))
        palette.setColor(QPalette.ToolTipBase, QColor("#1b2027"))
        palette.setColor(QPalette.ToolTipText, QColor("#eef1f4"))
        palette.setColor(QPalette.Text, QColor("#e8ebef"))
        palette.setColor(QPalette.Button, QColor("#1a1f26"))
        palette.setColor(QPalette.ButtonText, QColor("#e6e9ed"))
        palette.setColor(QPalette.Highlight, QColor("#3d5f86"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.PlaceholderText, QColor("#7f8996"))
        window.setPalette(palette)
    except Exception:
        return


def apply_fzastro_window_stylesheet(window: QWidget) -> None:
    """Ensure detached dialogs share the same stylesheet as the main window."""
    try:
        if str(window.styleSheet() or "").strip():
            return
        from .styles import get_main_stylesheet

        window.setStyleSheet(get_main_stylesheet())
    except Exception:
        return


def apply_interactive_cursors_later(window: QWidget | None) -> None:
    """Best-effort cursor polish for stable app-owned windows/dialogs."""

    if window is None:
        return
    try:
        from .cursors import apply_interactive_cursors

        apply_interactive_cursors(window)
    except Exception:
        return


def bring_window_to_front(window: QWidget) -> None:
    """Best-effort activation for newly opened utility windows."""
    try:
        window.raise_()
        window.activateWindow()
    except Exception:
        return


def apply_window_defaults(
    window: QWidget, *, center: bool = True, apply_style: bool = True
) -> None:
    """Give app windows normal desktop chrome and center them when shown.

    PySide QDialog windows can lose minimize/maximize buttons depending on the
    platform and creation flags. Applying this to every app-owned top-level
    window keeps behavior consistent across all FZAstro tools.
    """
    try:
        flags = (
            window.windowFlags()
            | Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        window.setWindowFlags(flags)
    except Exception:
        pass
    apply_fzastro_window_palette(window)
    if apply_style:
        apply_fzastro_window_stylesheet(window)
    if center:
        QTimer.singleShot(0, lambda: center_window_on_screen(window))
        QTimer.singleShot(80, lambda: center_window_on_screen(window))
    QTimer.singleShot(0, lambda: apply_interactive_cursors_later(window))
    QTimer.singleShot(120, lambda: apply_interactive_cursors_later(window))
    QTimer.singleShot(0, lambda: bring_window_to_front(window))
    QTimer.singleShot(120, lambda: bring_window_to_front(window))

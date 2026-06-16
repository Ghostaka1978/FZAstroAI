from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
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


def apply_window_defaults(window: QWidget, *, center: bool = True) -> None:
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
    if center:
        QTimer.singleShot(0, lambda: center_window_on_screen(window))
        QTimer.singleShot(80, lambda: center_window_on_screen(window))

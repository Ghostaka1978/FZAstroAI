"""Shared cursor polish for interactive FZAstro AI controls."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QMenu, QTabBar, QWidget

_INTERACTIVE_CURSOR_PROPERTY = "fzastroInteractiveCursorApplied"
_INTERACTIVE_WIDGET_NAMES = {
    "brandMark",
    "sidebarBrandMark",
    "helpButton",
    "diagnosticsButton",
    "workspaceAppsButton",
    "workspaceTabCloseButton",
}


def _is_interactive_widget(widget: QWidget) -> bool:
    """Return true for controls that should show a hand cursor on hover."""

    if isinstance(widget, (QAbstractButton, QComboBox, QMenu, QTabBar)):
        return True

    if widget.objectName() in _INTERACTIVE_WIDGET_NAMES:
        return True

    return bool(widget.property("fzastroInteractive"))


def _apply_cursor(widget: QWidget) -> None:
    if not _is_interactive_widget(widget):
        return

    if bool(widget.property(_INTERACTIVE_CURSOR_PROPERTY)):
        return

    widget.setCursor(Qt.PointingHandCursor)
    widget.setProperty(_INTERACTIVE_CURSOR_PROPERTY, True)


def apply_interactive_cursors(root: QWidget | None) -> None:
    """Apply pointing-hand cursors to buttons/menus under *root*.

    Qt stylesheets cannot set mouse cursors.  This helper gives all shared
    app buttons a consistent clickable cursor without duplicating setCursor()
    calls in every tool dialog.
    """

    if root is None:
        return

    try:
        _apply_cursor(root)
        for widget in root.findChildren(QWidget):
            _apply_cursor(widget)
    except RuntimeError:
        # The widget was deleted while a show/child event was being processed.
        return


class InteractiveCursorFilter(QObject):
    """Application-level event filter that keeps dynamic dialogs polished."""

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override name
        event_type = event.type()

        if event_type in {
            QEvent.Type.Show,
            QEvent.Type.Polish,
            QEvent.Type.ChildAdded,
        } and isinstance(watched, QWidget):
            apply_interactive_cursors(watched)

        return super().eventFilter(watched, event)


def install_interactive_cursor_filter(app) -> InteractiveCursorFilter:
    """Install the shared cursor filter once on the QApplication."""

    existing = getattr(app, "_fzastro_interactive_cursor_filter", None)

    if existing is not None:
        return existing

    cursor_filter = InteractiveCursorFilter(app)
    app.installEventFilter(cursor_filter)
    app._fzastro_interactive_cursor_filter = cursor_filter
    return cursor_filter


__all__ = [
    "InteractiveCursorFilter",
    "apply_interactive_cursors",
    "install_interactive_cursor_filter",
]

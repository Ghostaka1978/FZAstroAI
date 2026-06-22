"""Shared cursor polish for interactive FZAstro AI controls."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QTabBar, QWidget

try:
    from shiboken6 import isValid as _qt_is_valid
except Exception:  # pragma: no cover - depends on PySide install shape
    _qt_is_valid = None

_INTERACTIVE_CURSOR_PROPERTY = "fzastroInteractiveCursorApplied"
_INTERACTIVE_WIDGET_NAMES = {
    "brandMark",
    "sidebarBrandMark",
    "helpButton",
    "diagnosticsButton",
    "workspaceAppsButton",
    "workspaceTabCloseButton",
}


def _is_qt_object_valid(widget: QWidget | None) -> bool:
    """Return false when PySide is holding a wrapper for a deleted Qt object."""

    if widget is None:
        return False
    if _qt_is_valid is None:
        return True
    try:
        return bool(_qt_is_valid(widget))
    except Exception:
        return False


def _is_interactive_widget(widget: QWidget) -> bool:
    """Return true for controls that should show a hand cursor on hover."""

    if isinstance(widget, (QAbstractButton, QComboBox, QTabBar)):
        return True

    if widget.objectName() in _INTERACTIVE_WIDGET_NAMES:
        return True

    return bool(widget.property("fzastroInteractive"))


def _apply_cursor(widget: QWidget) -> None:
    if not _is_qt_object_valid(widget):
        return

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

    if not _is_qt_object_valid(root):
        return

    try:
        _apply_cursor(root)
        for widget in root.findChildren(QWidget):
            _apply_cursor(widget)
    except RuntimeError:
        # The widget was deleted while a show/child event was being processed.
        return


class InteractiveCursorFilter(QObject):
    """Application-level event filter for optional dynamic cursor polish.

    The main application applies cursors recursively at stable UI setup points.
    A global Qt event filter can touch widgets while native menus/dialogs are
    being created or destroyed on some PySide6 builds, which can surface as a
    native 0xC0000005 access violation. Keep this filter available for opt-in
    debugging, but do not install it by default.
    """

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override name
        try:
            if event is None:
                return False
            event_type = event.type()
            if event_type in {
                QEvent.Type.Show,
                QEvent.Type.Polish,
                QEvent.Type.ChildAdded,
            } and isinstance(watched, QWidget):
                apply_interactive_cursors(watched)
        except RuntimeError:
            return False
        except Exception:
            return False

        return False


def install_interactive_cursor_filter(app) -> InteractiveCursorFilter:
    """Prepare the shared cursor filter without enabling risky global scanning.

    Set ``FZASTRO_ENABLE_GLOBAL_CURSOR_FILTER=1`` to opt into the old
    application-wide event filter while debugging. Normal builds rely on
    explicit ``apply_interactive_cursors`` calls from the main window and
    app-owned dialogs.
    """

    existing = getattr(app, "_fzastro_interactive_cursor_filter", None)

    if existing is not None:
        return existing

    cursor_filter = InteractiveCursorFilter(app)
    if os.environ.get("FZASTRO_ENABLE_GLOBAL_CURSOR_FILTER") == "1":
        try:
            app.installEventFilter(cursor_filter)
            cursor_filter._fzastro_installed_on_app = True
        except Exception:
            cursor_filter._fzastro_installed_on_app = False
    else:
        cursor_filter._fzastro_installed_on_app = False
    app._fzastro_interactive_cursor_filter = cursor_filter
    return cursor_filter


__all__ = [
    "InteractiveCursorFilter",
    "apply_interactive_cursors",
    "install_interactive_cursor_filter",
]

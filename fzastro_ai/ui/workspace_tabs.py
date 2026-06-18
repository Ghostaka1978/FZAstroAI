from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QSizePolicy, QTabBar, QTabWidget, QWidget

from ..logging_utils import log_exception


class WorkspaceTabsMixin:
    """Host long-lived tool surfaces as tabs inside the main app workspace."""

    def create_workspace_tabs(self, chat_widget: QWidget) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("workspaceTabs")
        tabs.setDocumentMode(True)
        tabs.setMovable(True)
        tabs.setTabsClosable(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tabs.tabCloseRequested.connect(self.close_workspace_tab)

        self.workspace_tabs = tabs
        self._workspace_tab_keys: dict[str, QWidget] = {}
        self._workspace_tab_titles: dict[str, str] = {}
        self._workspace_tab_close_callbacks: dict[str, Callable[[QWidget], None]] = {}
        self._workspace_tab_closing: set[int] = set()
        self._workspace_chat_widget = chat_widget

        chat_index = tabs.addTab(chat_widget, "Chat")
        tabs.setTabToolTip(chat_index, "Main FZAstro AI chat")
        try:
            tabs.tabBar().setTabButton(
                chat_index, QTabBar.ButtonPosition.RightSide, None
            )
        except Exception:
            pass
        return tabs

    def open_workspace_tab(
        self,
        key: str,
        title: str,
        factory: Callable[[], QWidget],
        *,
        tooltip: str = "",
        on_close: Callable[[QWidget], None] | None = None,
    ) -> QWidget | None:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return factory()

        clean_key = str(key or title or "").strip()
        if not clean_key:
            clean_key = f"tab-{tabs.count()}"

        existing = self._workspace_tab_keys.get(clean_key)
        if existing is not None:
            try:
                index = tabs.indexOf(existing)
                if index >= 0:
                    tabs.setCurrentIndex(index)
                    existing.show()
                    existing.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                    return existing
            except RuntimeError:
                self._workspace_forget_tab(clean_key)

        try:
            widget = factory()
        except Exception as exc:
            log_exception("WorkspaceTabsMixin.open_workspace_tab", exc)
            raise
        if widget is None:
            return None

        self._prepare_workspace_tab_widget(widget)
        index = tabs.addTab(widget, title)
        tabs.setCurrentIndex(index)
        if tooltip:
            tabs.setTabToolTip(index, tooltip)
        self._workspace_tab_keys[clean_key] = widget
        self._workspace_tab_titles[clean_key] = title
        if on_close is not None:
            self._workspace_tab_close_callbacks[clean_key] = on_close

        try:
            widget.destroyed.connect(
                lambda *_args, tab_key=clean_key: self._workspace_forget_tab(tab_key)
            )
        except Exception:
            pass

        if isinstance(widget, QDialog):
            try:
                widget.finished.connect(
                    lambda *_args, tab_widget=widget: QTimer.singleShot(
                        0,
                        lambda: self._remove_workspace_tab_for_widget(
                            tab_widget, delete_widget=True
                        ),
                    )
                )
            except Exception:
                pass

        widget.show()
        return widget

    def focus_workspace_tab(self, key: str) -> bool:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return False
        widget = self._workspace_tab_keys.get(str(key or "").strip())
        if widget is None:
            return False
        index = tabs.indexOf(widget)
        if index < 0:
            return False
        tabs.setCurrentIndex(index)
        return True

    def close_workspace_tab(self, index: int):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None or index <= 0 or index >= tabs.count():
            return
        widget = tabs.widget(index)
        if widget is None:
            return
        widget_id = id(widget)
        if widget_id in self._workspace_tab_closing:
            return
        self._workspace_tab_closing.add(widget_id)

        try:
            if isinstance(widget, QDialog):
                widget.reject()
            else:
                widget.close()
        except Exception:
            log_exception("WorkspaceTabsMixin.close_workspace_tab")

        QTimer.singleShot(
            0, lambda tab_widget=widget: self._finish_workspace_tab_close(tab_widget)
        )

    def _prepare_workspace_tab_widget(self, widget: QWidget):
        widget.setParent(getattr(self, "workspace_tabs", None))
        widget.setWindowFlags(Qt.WindowType.Widget)
        widget.setWindowModality(Qt.WindowModality.NonModal)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def _finish_workspace_tab_close(self, widget: QWidget):
        self._workspace_tab_closing.discard(id(widget))
        try:
            if widget.isVisible():
                return
        except RuntimeError:
            return
        self._remove_workspace_tab_for_widget(widget, delete_widget=True)

    def _remove_workspace_tab_for_widget(
        self, widget: QWidget, *, delete_widget: bool = False
    ):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return
        try:
            index = tabs.indexOf(widget)
        except RuntimeError:
            return
        if index <= 0:
            return

        key = self._workspace_key_for_widget(widget)
        tabs.removeTab(index)
        if key:
            callback = self._workspace_tab_close_callbacks.pop(key, None)
            self._workspace_forget_tab(key)
            if callback is not None:
                try:
                    callback(widget)
                except Exception:
                    log_exception("WorkspaceTabsMixin tab close callback")

        if delete_widget:
            try:
                widget.deleteLater()
            except RuntimeError:
                pass

    def _workspace_key_for_widget(self, widget: QWidget) -> str:
        for key, candidate in list(self._workspace_tab_keys.items()):
            if candidate is widget:
                return key
        return ""

    def _workspace_forget_tab(self, key: str):
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        self._workspace_tab_keys.pop(clean_key, None)
        self._workspace_tab_titles.pop(clean_key, None)
        self._workspace_tab_close_callbacks.pop(clean_key, None)

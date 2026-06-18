from __future__ import annotations

from collections.abc import Callable
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..logging_utils import log_exception


def _make_workspace_tab_close_icon(color: str = "#aeb8c4") -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(
        QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(4, 4, 10, 10)
    painter.drawLine(10, 4, 4, 10)
    painter.end()
    return QIcon(pixmap)


class WorkspaceTabsMixin:
    """Host long-lived tool surfaces as tabs inside the main app workspace."""

    def create_workspace_tabs(self, chat_widget: QWidget) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("workspaceTabs")
        tabs.setDocumentMode(True)
        tabs.setMovable(True)
        tabs.setTabsClosable(False)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tabs.tabCloseRequested.connect(self.close_workspace_tab)
        tab_bar = tabs.tabBar()
        tab_bar.setObjectName("workspaceTabBar")
        tab_bar.setExpanding(False)
        tab_bar.setDrawBase(False)
        tab_bar.setUsesScrollButtons(True)

        self.workspace_tabs = tabs
        self._workspace_tab_keys: dict[str, QWidget] = {}
        self._workspace_tab_widgets: dict[str, QWidget] = {}
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
        self.workspace_apps_button = self._create_workspace_apps_button()
        tabs.setCornerWidget(self.workspace_apps_button, Qt.Corner.TopRightCorner)
        tabs.currentChanged.connect(self._handle_workspace_tab_changed)
        return tabs

    def _create_workspace_apps_button(self) -> QPushButton:
        button = QPushButton("Apps")
        button.setObjectName("workspaceAppsButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip("Open workspace apps as tabs")
        button.setMenu(self._build_workspace_apps_menu())
        button.setMinimumWidth(88)
        button.setFixedHeight(30)
        return button

    def _build_workspace_apps_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        self._add_workspace_menu_section(menu, "Astronomy")
        self._add_workspace_app_action(
            menu,
            "LOOKUP",
            "open_astro_lookup_dialog",
            "Object lookup with sky preview and distance details",
        )
        self._add_workspace_app_action(
            menu,
            "TARGETS",
            "open_astro_targets_dialog",
            "Best astrophotography targets for the selected night",
        )
        self._add_workspace_app_action(
            menu,
            "SEEING",
            "open_astro_forecast_dialog",
            "Cloud, darkness, Moon, seeing, and transparency planner",
        )
        self._add_workspace_app_action(
            menu,
            "SUN NOW",
            "open_sun_now_dialog",
            "Latest Sun imagery and metadata",
        )
        self._add_workspace_app_action(
            menu,
            "SOLAR MAP",
            "open_solar_system_map",
            "Interactive solar-system map",
        )
        self._add_workspace_app_action(
            menu,
            "N.I.N.A.",
            "open_nina_control",
            "FZAstro Imaging / N.I.N.A. workflow",
        )

        menu.addSeparator()
        self._add_workspace_menu_section(menu, "Workspace")
        self._add_workspace_app_action(
            menu,
            "DOCUMENTS",
            "open_document_knowledge_library",
            "Imported document knowledge library",
        )
        self._add_workspace_app_action(
            menu,
            "MEMORY",
            "open_persistent_memory_library",
            "Persistent memory library",
        )
        self._add_workspace_app_action(
            menu,
            "DEV",
            "open_dev_workbench",
            "AI Developer Workbench",
        )
        self._add_workspace_app_action(
            menu,
            "LLM BENCH",
            "open_llm_benchmark_dashboard",
            "Model latency, throughput, and comparison benchmark",
        )

        menu.addSeparator()
        self._add_workspace_menu_section(menu, "System")
        self._add_workspace_app_action(
            menu,
            "HELP",
            "open_help_cheat_sheet",
            "FZAstro AI help and command hints",
        )
        self._add_workspace_app_action(
            menu,
            "DIAGNOSTICS",
            "open_diagnostics_window",
            "Diagnostics, paths, and recent errors",
        )
        self._add_workspace_app_action(
            menu,
            "ABOUT",
            "open_about_window",
            "Version and release information",
        )
        return menu

    def _add_workspace_menu_section(self, menu: QMenu, title: str):
        action = QAction(str(title or "").upper(), self)
        action.setEnabled(False)
        menu.addAction(action)

    def _add_workspace_app_action(
        self, menu: QMenu, label: str, handler_name: str, tooltip: str = ""
    ):
        action = QAction(label, self)
        if tooltip:
            action.setToolTip(tooltip)
        handler = getattr(self, str(handler_name or ""), None)
        action.setEnabled(callable(handler))
        action.triggered.connect(
            lambda checked=False, name=handler_name: self._run_workspace_app(name)
        )
        menu.addAction(action)

    def _run_workspace_app(self, handler_name: str):
        handler = getattr(self, str(handler_name or ""), None)
        if not callable(handler):
            return
        try:
            handler()
        except Exception as exc:
            log_exception("WorkspaceTabsMixin._run_workspace_app", exc)

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
                    content = self._workspace_content_for_page(existing)
                    tabs.setCurrentIndex(index)
                    if content is not None:
                        content.show()
                        self._queue_workspace_tab_geometry_sync(content)
                        content.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                        return content
                    existing.show()
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

        page = self._create_workspace_tab_page(widget)
        index = tabs.addTab(page, title)
        self._install_workspace_tab_close_button(index, widget)
        tabs.setCurrentIndex(index)
        if tooltip:
            tabs.setTabToolTip(index, tooltip)
        self._workspace_tab_keys[clean_key] = page
        self._workspace_tab_widgets[clean_key] = widget
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
        self._queue_workspace_tab_geometry_sync(widget)
        return widget

    def focus_workspace_tab(self, key: str) -> bool:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return False
        page = self._workspace_tab_keys.get(str(key or "").strip())
        if page is None:
            return False
        index = tabs.indexOf(page)
        if index < 0:
            return False
        tabs.setCurrentIndex(index)
        return True

    def close_workspace_tab(self, index: int):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None or index <= 0 or index >= tabs.count():
            return
        page = tabs.widget(index)
        if page is None:
            return
        widget = self._workspace_content_for_page(page) or page
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

    def close_workspace_widget(self, widget: QWidget):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return
        key = self._workspace_key_for_widget(widget)
        page = self._workspace_tab_keys.get(key) if key else widget
        try:
            index = tabs.indexOf(page)
        except RuntimeError:
            return
        self.close_workspace_tab(index)

    def _install_workspace_tab_close_button(self, index: int, widget: QWidget):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None or index <= 0:
            return
        button = QPushButton()
        button.setObjectName("workspaceTabCloseButton")
        button.setFixedSize(18, 18)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip("Close tab")
        button.setIcon(_make_workspace_tab_close_icon())
        button.setIconSize(QSize(12, 12))
        button.clicked.connect(
            lambda _checked=False, tab_widget=widget: self.close_workspace_widget(
                tab_widget
            )
        )
        tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def _create_workspace_tab_page(self, widget: QWidget) -> QWidget:
        page = QWidget()
        page.setObjectName("workspaceTabPage")
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        try:
            page.installEventFilter(self)
        except Exception:
            pass
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._prepare_workspace_tab_widget(widget, page)
        layout.addWidget(widget)
        return page

    def _prepare_workspace_tab_widget(self, widget: QWidget, page: QWidget):
        try:
            setattr(widget, "_workspace_host", self)
            widget.setProperty("fzastro_workspace_tab", True)
        except Exception:
            pass
        widget.setWindowFlags(Qt.WindowType.Widget)
        widget.setParent(page)
        widget.setWindowModality(Qt.WindowModality.NonModal)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        widget.move(0, 0)
        self._hide_redundant_dialog_buttons_for_tab(widget)

    def _hide_redundant_dialog_buttons_for_tab(self, widget: QWidget):
        if not isinstance(widget, QDialog):
            return
        action_words = ("save", "apply", "use", "run", "send", "update", "import")
        for button_box in widget.findChildren(QDialogButtonBox):
            try:
                buttons = button_box.buttons()
                labels = [
                    str(button.text() or "").replace("&", "").strip().casefold()
                    for button in buttons
                ]
                if any(
                    any(action_word in label for action_word in action_words)
                    for label in labels
                ):
                    continue
                button_box.hide()
                button_box.setMaximumHeight(0)
            except RuntimeError:
                continue

    def _sync_current_workspace_tab_geometry(self, index: int):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None or index <= 0:
            return
        page = tabs.widget(index)
        widget = self._workspace_content_for_page(page) if page is not None else None
        if widget is not None:
            self._queue_workspace_tab_geometry_sync(widget)

    def _handle_workspace_tab_changed(self, index: int):
        self._sync_current_workspace_tab_geometry(index)
        self._update_workspace_chat_chrome(index)

    def eventFilter(self, watched, event):
        try:
            if getattr(
                watched, "objectName", lambda: ""
            )() == "workspaceTabPage" and event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
            ):
                widget = self._workspace_content_for_page(watched)
                if widget is not None:
                    self._sync_workspace_tab_geometry(widget)
                    if event.type() != QEvent.Type.LayoutRequest:
                        self._queue_workspace_tab_geometry_sync(widget)
        except RuntimeError:
            pass

        parent_filter = getattr(super(), "eventFilter", None)
        if callable(parent_filter):
            return parent_filter(watched, event)
        return False

    def _update_workspace_chat_chrome(self, index: int | None = None):
        tabs = getattr(self, "workspace_tabs", None)
        if index is None and tabs is not None:
            index = tabs.currentIndex()
        is_chat_tab = int(index or 0) == 0
        composer_shell = getattr(self, "composer_shell", None)
        if composer_shell is not None:
            try:
                composer_shell.setVisible(is_chat_tab)
            except RuntimeError:
                pass
        thought_panel = getattr(self, "thought_panel", None)
        if thought_panel is not None:
            try:
                if is_chat_tab and hasattr(self, "refresh_thought_panel_visibility"):
                    self.refresh_thought_panel_visibility()
                else:
                    thought_panel.hide()
            except RuntimeError:
                pass

    def _sync_workspace_tab_geometry(self, widget: QWidget):
        if widget is getattr(self, "_workspace_chat_widget", None):
            return
        try:
            parent = widget.parentWidget()
            if parent is None:
                return
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            parent.updateGeometry()
            widget.setGeometry(parent.rect())
            widget.resize(parent.size())
            widget.move(0, 0)
            child_layout = widget.layout()
            if child_layout is not None:
                child_layout.activate()
            widget.updateGeometry()
            widget.update()
        except RuntimeError:
            return

    def _queue_workspace_tab_geometry_sync(self, widget: QWidget):
        self._sync_workspace_tab_geometry(widget)
        for delay_ms in (0, 16, 40, 90, 180, 320):
            QTimer.singleShot(
                delay_ms,
                lambda tab_widget=widget: self._sync_workspace_tab_geometry(tab_widget),
            )

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

        key = self._workspace_key_for_widget(widget)
        page = self._workspace_tab_keys.get(key) if key else widget
        page_index = tabs.indexOf(page)
        if page_index <= 0:
            return
        tabs.removeTab(page_index)
        if key:
            callback = self._workspace_tab_close_callbacks.pop(key, None)
            content = self._workspace_tab_widgets.get(key) or widget
            self._workspace_forget_tab(key)
            if callback is not None:
                try:
                    callback(content)
                except Exception:
                    log_exception("WorkspaceTabsMixin tab close callback")

        if delete_widget:
            try:
                page.deleteLater()
            except RuntimeError:
                pass

    def _workspace_key_for_widget(self, widget: QWidget) -> str:
        for key, page in list(self._workspace_tab_keys.items()):
            if page is widget or self._workspace_tab_widgets.get(key) is widget:
                return key
        return ""

    def _workspace_content_for_page(self, page: QWidget | None) -> QWidget | None:
        if page is None:
            return None
        for key, candidate_page in list(self._workspace_tab_keys.items()):
            if candidate_page is page:
                return self._workspace_tab_widgets.get(key)
        return None

    def _workspace_forget_tab(self, key: str):
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        self._workspace_tab_keys.pop(clean_key, None)
        self._workspace_tab_widgets.pop(clean_key, None)
        self._workspace_tab_titles.pop(clean_key, None)
        self._workspace_tab_close_callbacks.pop(clean_key, None)

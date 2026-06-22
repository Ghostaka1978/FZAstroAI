"""Main-window layout and lightweight UI helper methods for FZAstro AI.

These methods were extracted from app.py without behavior changes. They are
implemented as a mixin because they operate on widgets owned by FZAstroAI.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .message_widgets import AutoHeightRichText, MessageWidget


class MainLayoutMixin:

    def set_action_button_mode(self, mode):
        """Apply a clear visual and semantic state to the composer action."""
        if mode == "stop":
            object_name = "stopButton"
            label = "Stop"
            tooltip = "Stop the current operation"
            enabled = True
        elif mode == "stopping":
            object_name = "stopButton"
            label = "Stopping…"
            tooltip = "Stopping the current operation"
            enabled = False
        else:
            object_name = "sendButton"
            label = "Send"
            tooltip = "Send message"
            enabled = True

        self.action_button.setObjectName(object_name)
        self.action_button.setText(label)
        self.action_button.setToolTip(tooltip)
        # Text-only controls avoid platform-dependent coloured native icons.
        self.action_button.setIcon(QIcon())
        self.action_button.setEnabled(enabled)

        # Object-name selectors are cached by Qt; repolish after changing modes.
        button_style = self.action_button.style()
        button_style.unpolish(self.action_button)
        button_style.polish(self.action_button)
        self.action_button.update()

    def set_busy_ui_state(self, status_text=None):
        """Lock every interactive control except the active Stop button."""
        if not hasattr(self, "_busy_control_states"):
            self._busy_control_states = []

        controlled_widgets = []

        for widget_type in (
            QPushButton,
            QComboBox,
            QSpinBox,
            QLineEdit,
            QSlider,
            QCheckBox,
            QListWidget,
        ):
            controlled_widgets.extend(self.findChildren(widget_type))

        # These editors are intentionally listed explicitly so message text
        # browsers remain selectable and the chat can still be scrolled.
        for widget_name in ("input_box", "system_prompt", "persistent_memory"):
            widget = getattr(self, widget_name, None)

            if widget is not None:
                controlled_widgets.append(widget)

        saved_widget_ids = {id(widget) for widget, _ in self._busy_control_states}
        seen_widget_ids = set()

        for widget in controlled_widgets:
            widget_id = id(widget)

            if widget_id in seen_widget_ids:
                continue

            seen_widget_ids.add(widget_id)

            if widget is self.action_button:
                continue

            if widget_id not in saved_widget_ids:
                try:
                    self._busy_control_states.append((widget, widget.isEnabled()))
                    saved_widget_ids.add(widget_id)
                except RuntimeError:
                    continue

            try:
                widget.setEnabled(False)
            except RuntimeError:
                pass

        self.set_action_button_mode("stop")

        if status_text is not None:
            self.stats_label.setText(status_text)

    def restore_busy_ui_state(self):
        saved_states = getattr(self, "_busy_control_states", [])
        self._busy_control_states = []

        for widget, was_enabled in saved_states:
            try:
                widget.setEnabled(was_enabled)
            except RuntimeError:
                pass

    def set_idle_ui_state(self, status_text=None):
        self.generation_timer.stop()
        self.restore_busy_ui_state()
        self.set_action_button_mode("send")
        self.input_box.setEnabled(True)
        self.attach_button.setEnabled(True)
        if hasattr(self, "voice_button"):
            self.voice_button.setEnabled(True)
        self.new_chat_button.setEnabled(True)
        self.history_button.setEnabled(True)
        self.help_button.setEnabled(True)
        self.diagnostics_button.setEnabled(True)
        self.news_button.setEnabled(True)
        if hasattr(self, "composer_markets_button"):
            self.composer_markets_button.setEnabled(True)
        self.crm_stock_button.setEnabled(True)
        self.dbx_stock_button.setEnabled(True)
        self.crude_oil_button.setEnabled(True)
        self.gold_button.setEnabled(True)

        if hasattr(self, "import_documents_memory_button"):
            memory_busy = bool(self.memory_worker and self.memory_worker.isRunning())
            knowledge_busy = bool(
                self.knowledge_worker and self.knowledge_worker.isRunning()
            )
            self.import_documents_memory_button.setEnabled(
                not memory_busy and not knowledge_busy
            )

        if hasattr(self, "open_persistent_memory_button"):
            memory_busy = bool(self.memory_worker and self.memory_worker.isRunning())
            self.open_persistent_memory_button.setEnabled(not memory_busy)

        self.stop_in_progress = False
        self.cancel_generation = False

        if status_text is not None:
            self.stats_label.setText(status_text)

        self.input_box.setFocus()

    def _create_settings_card(self, title_text, subtitle_text=""):
        """Create a reusable sidebar surface with consistent spacing."""
        card = QFrame()
        card.setObjectName("settingsCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(8)

        title = QLabel(title_text)
        title.setObjectName("settingsCardTitle")
        layout.addWidget(title)

        if subtitle_text:
            subtitle = QLabel(subtitle_text)
            subtitle.setObjectName("settingsCardSubtitle")
            subtitle.setWordWrap(True)
            layout.addWidget(subtitle)

        return card, layout

    def _create_toolbar_button(self, text, object_name, tooltip, width=42, height=42):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedSize(width, height)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def refresh_thought_panel_visibility(self):
        panel = getattr(self, "thought_panel", None)
        browser = getattr(self, "global_thought_box", None)

        if panel is None or browser is None:
            return

        workspace_tabs = getattr(self, "workspace_tabs", None)
        if workspace_tabs is not None and workspace_tabs.currentIndex() != 0:
            panel.hide()
            return

        panel.setVisible(bool(browser.toPlainText().strip()))

    def show_empty_chat_state(self):
        if not hasattr(self, "chat_layout"):
            return

        self.chat_layout.setAlignment(Qt.AlignTop)

        current = getattr(self, "empty_state_widget", None)

        if current is not None:
            try:
                current.deleteLater()
            except RuntimeError:
                pass

        empty_state = QFrame()
        empty_state.setObjectName("emptyState")
        empty_state.setMaximumWidth(620)
        empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(empty_state)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        mark = QLabel("FZ")
        mark.setObjectName("emptyStateMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(46, 46)

        title = QLabel("Ready when you are")
        title.setObjectName("emptyStateTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel(
            "Ask a question, attach a document, or expand Skills from the bottom bar."
        )
        subtitle.setObjectName("emptyStateSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)

        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 8, 0, 0)
        hint_row.setSpacing(7)
        hint_row.setAlignment(Qt.AlignCenter)

        for hint_text in (
            "Enter to send",
            "Shift+Enter for newline",
            "Drop files anywhere",
        ):
            hint = QLabel(hint_text)
            hint.setObjectName("emptyStateHint")
            hint.setAlignment(Qt.AlignCenter)
            hint_row.addWidget(hint)

        layout.addWidget(mark, 0, Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(hint_row)

        holder = QWidget()
        holder.setObjectName("emptyStateHolder")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 80, 0, 20)
        holder_layout.addStretch()
        holder_layout.addWidget(empty_state)
        holder_layout.addStretch()

        self.empty_state_widget = holder
        self.chat_layout.addWidget(holder)

    def hide_empty_chat_state(self):
        widget = getattr(self, "empty_state_widget", None)

        if widget is None:
            self.chat_layout.setAlignment(Qt.AlignTop)
            return

        try:
            self.chat_layout.removeWidget(widget)
            widget.deleteLater()
        except RuntimeError:
            pass

        self.empty_state_widget = None
        self.chat_layout.setAlignment(Qt.AlignTop)

    def refresh_chat_layout(self, scroll_to_bottom=False):
        """Recalculate restored message heights after Qt finishes layout."""
        try:
            self.chat_layout.invalidate()
            self.chat_container.adjustSize()
            self.chat_container.updateGeometry()

            for index in range(self.chat_layout.count()):
                item = self.chat_layout.itemAt(index)
                message_widget = item.widget()

                if not isinstance(message_widget, MessageWidget):
                    continue

                message_widget.adjustSize()
                message_widget.updateGeometry()

                for text_view in message_widget.findChildren(AutoHeightRichText):
                    text_view._schedule_height_update()

            if self.chat_scroll.widget() is not None:
                self.chat_scroll.widget().adjustSize()
                self.chat_scroll.widget().updateGeometry()

            self.chat_scroll.viewport().updateGeometry()
            self.chat_scroll.viewport().update()
            self.chat_scroll.updateGeometry()

            if hasattr(self, "sync_chat_container_height"):
                self.sync_chat_container_height()

            if scroll_to_bottom:
                self.force_scroll_to_bottom()

        except RuntimeError:
            pass

    def settle_chat_layout(self, scroll_to_bottom=False):
        """Run several short layout passes while restored rich text settles."""
        for delay in (0, 40, 120, 240):
            QTimer.singleShot(
                delay,
                lambda should_scroll=scroll_to_bottom: self.refresh_chat_layout(
                    should_scroll
                ),
            )

    def update_clock_label(self):
        """Keep a compact local date/time readout opposite the live statistics."""
        if not hasattr(self, "time_label"):
            return

        self.time_label.setText(datetime.now().strftime("%d %b %Y • %H:%M:%S"))

    def update_gpu_metrics(
        self, gpu_load, memory_used_mb, memory_total_mb, gpu_temp_c=None
    ):
        """Display live NVIDIA GPU load, temperature and VRAM use."""
        if not hasattr(self, "gpu_label"):
            return

        used_gb = max(0, memory_used_mb) / 1024.0
        total_gb = max(0, memory_total_mb) / 1024.0
        memory_percent = (
            (memory_used_mb / memory_total_mb) * 100.0 if memory_total_mb > 0 else 0.0
        )

        gpu_load = max(0, gpu_load)
        temperature_text = self._format_temperature(gpu_temp_c)
        temperature_segment = f" • {temperature_text}" if temperature_text else ""

        self.gpu_label.setText(
            f"GPU {gpu_load}%{temperature_segment} • "
            f"VRAM {used_gb:.1f}/{total_gb:.1f} GB"
        )
        self.gpu_label.setToolTip(
            f"GPU load: {gpu_load}%\n"
            f"GPU temperature: {temperature_text or 'unavailable'}\n"
            f"VRAM: {used_gb:.2f} / {total_gb:.2f} GB ({memory_percent:.1f}%)"
        )

    def update_system_metrics(
        self, cpu_load, ram_used_mb, ram_total_mb, cpu_temp_c=None
    ):
        """Display live CPU and RAM telemetry in the lower status row."""
        if not hasattr(self, "system_label"):
            return

        cpu_text = self._format_percent(cpu_load)
        ram_text = self._format_memory_pair(ram_used_mb, ram_total_mb)
        temperature_text = self._format_temperature(cpu_temp_c)
        temperature_segment = f" • {temperature_text}" if temperature_text else ""

        self.system_label.setText(
            f"CPU {cpu_text}{temperature_segment} • RAM {ram_text}"
        )
        self.system_label.setToolTip(
            f"CPU load: {cpu_text}\n"
            f"CPU temperature: {temperature_text or 'unavailable'}\n"
            f"RAM: {ram_text}"
        )

    def _format_percent(self, value):
        if value is None:
            return "--%"

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return "--%"

        if numeric_value < 0:
            return "--%"

        return f"{numeric_value:.0f}%"

    def _format_temperature(self, value):
        if value is None:
            return ""

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return ""

        if not (-50.0 <= numeric_value <= 150.0):
            return ""

        return f"{numeric_value:.0f}°C"

    def _format_memory_pair(self, used_mb, total_mb):
        try:
            used_mb = float(used_mb)
            total_mb = float(total_mb)
        except (TypeError, ValueError):
            return "--/-- GB"

        if used_mb < 0 or total_mb <= 0:
            return "--/-- GB"

        return f"{used_mb / 1024.0:.1f}/{total_mb / 1024.0:.1f} GB"

    def show_gpu_unavailable(self, error_text=""):
        if not hasattr(self, "gpu_label"):
            return

        self.gpu_label.setText("GPU telemetry unavailable")
        self.gpu_label.setToolTip(
            error_text or "nvidia-smi did not return GPU telemetry"
        )

    def _position_overlay_panels(self):
        """Keep side panels above the main workspace without layout cramping."""
        root = getattr(self, "root_shell", None)

        if root is None:
            root = self.centralWidget() if hasattr(self, "centralWidget") else None

        if root is None:
            return

        root_width = max(0, int(root.width()))
        root_height = max(0, int(root.height()))

        sidebar = getattr(self, "sidebar", None)
        if sidebar is not None:
            sidebar_width = max(0, int(sidebar.width() or sidebar.sizeHint().width()))
            sidebar.setGeometry(0, 0, sidebar_width, root_height)

            close_button = getattr(self, "sidebar_close_button", None)
            if close_button is not None:
                close_x = max(8, sidebar_width - int(close_button.width()) - 12)
                close_button.move(close_x, 16)
                close_button.setVisible(sidebar.isVisible())
                if sidebar.isVisible():
                    close_button.raise_()

            if sidebar.isVisible():
                sidebar.raise_()
                if close_button is not None:
                    close_button.raise_()

        history_panel = getattr(self, "history_panel", None)
        if history_panel is not None:
            history_width = max(
                0, int(history_panel.width() or history_panel.sizeHint().width())
            )
            history_x = max(0, root_width - history_width)
            history_panel.setGeometry(history_x, 0, history_width, root_height)
            if history_panel.isVisible():
                history_panel.raise_()

        idle_overlay = getattr(self, "idle_stars_overlay", None)
        if idle_overlay is not None:
            idle_overlay.setGeometry(0, 0, root_width, root_height)
            if idle_overlay.isVisible():
                idle_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlay_panels()

    def close_sidebar(self):
        sidebar = getattr(self, "sidebar", None)

        if sidebar is None:
            return

        self.sidebar_visible = False
        sidebar.hide()

        button = getattr(self, "sidebar_button", None)
        if button is not None:
            button.setChecked(False)

        self._position_overlay_panels()

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(self.sidebar_visible)
        self.sidebar_button.setChecked(self.sidebar_visible)
        self._position_overlay_panels()

    def toggle_skills_drawer(self):
        """Backward-compatible helper: open the Skills menu instead of an inline drawer."""
        button = getattr(self, "composer_actions_button", None)

        if button is None:
            return

        menu = button.menu() if hasattr(button, "menu") else None

        if menu is not None:
            menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

import json
import re
import uuid
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QPushButton, QSizePolicy

from ..history_store import create_chat_record, save_chat_history
from ..market_sources import parse_stock_quote_payload, stock_quote_plain_text
from ..memory_store import preserve_source_attachments_for_memory


def save_current_chat(self):
    if self.active_chat_id:
        for record in self.chat_history:
            if record.get("id") == self.active_chat_id:
                record["messages"] = json.loads(json.dumps(self.messages))
                record["updated"] = datetime.now().isoformat()
                save_chat_history(self.chat_history)
                self.render_history()
                return

    if not self.messages:
        return

    record = create_chat_record(json.loads(json.dumps(self.messages)))
    record["updated"] = datetime.now().isoformat()
    self.active_chat_id = record["id"]
    self.chat_history.append(record)
    save_chat_history(self.chat_history)
    self.render_history()


def load_chat(self, chat_id):
    if self.worker and self.worker.isRunning():
        self.worker.stop()
        self.worker.wait(3000)
        self.worker = None

    python_worker = getattr(self, "python_worker", None)

    if python_worker is not None and python_worker.isRunning():
        self.stats_label.setText("Stop Python execution before loading history")
        return

    self.current_stream_widget = None
    self.current_assistant_message_id = None
    self.pending_python_auto_test = None
    self.current_progress_news_widget = None
    self.generation_timer.stop()
    self._last_thoughts_text = ""
    self.global_thought_box.setMarkdown("")

    for record in self.chat_history:
        if record.get("id") != chat_id:
            continue

        self.active_chat_id = chat_id
        self.messages = json.loads(json.dumps(record.get("messages", [])))

        for message in self.messages:
            if not message.get("id"):
                message["id"] = uuid.uuid4().hex

        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        for msg in self.messages:
            role = msg.get("role", "")

            if role == "user":
                content = msg.get("content", "")
                files = msg.get("files", [])

                if isinstance(content, list):
                    text = ""

                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text", "")
                            break
                else:
                    text = str(content)

                for pattern in (
                    r"\n\n\[INTERNET CONTEXT\].*",
                    r"\n\n\[STOCK QUOTE\].*",
                ):
                    text = re.sub(pattern, "", text, flags=re.DOTALL).strip()

                if files:
                    text = re.sub(
                        r"\n\nAttached file:.*", "", text, flags=re.DOTALL
                    ).strip()

                    if text == "Analyze the attached file.":
                        text = ""

                self.add_message_widget(
                    ":ME:", text, files, message_id=msg.get("id", ""), animate=False
                )

            elif role == "assistant":
                content = msg.get("content", "")
                files = msg.get("files", [])
                news_sources = msg.get("news_sources", {})

                self.add_message_widget(
                    ":AI:",
                    str(content),
                    files=files,
                    news_sources=news_sources,
                    message_id=msg.get("id", ""),
                    response_time=msg.get("response_time"),
                    source_tags=msg.get("source_tags"),
                    animate=False,
                )

        self.set_idle_ui_state()
        self.chat_scroll.setFocus()
        self.settle_chat_layout(scroll_to_bottom=True)
        break


def render_history(self):
    while self.history_list.count():
        item = self.history_list.takeAt(0)

        if item.widget():
            item.widget().deleteLater()

    # Show pinned chats first, and within each group show the most
    # recently updated chat at the top. Python's sort is stable, so the
    # second sort preserves the newest-first order inside each pin group.
    records = sorted(
        self.chat_history,
        key=lambda r: r.get("updated", r.get("created", "")),
        reverse=True,
    )
    records.sort(key=lambda r: not r.get("pinned", False))

    for record in records[:100]:
        raw_title = str(record.get("title", "New Chat")).strip() or "New Chat"
        display_title = raw_title

        if len(display_title) > 46:
            display_title = display_title[:43].rstrip() + "..."

        if record.get("pinned", False):
            display_title = "Pinned — " + display_title

        # Compact one-line history rows. The frequent actions stay visible:
        # select, open, and pin. Less frequent actions move into a small
        # More menu, which keeps each saved conversation short and readable.
        row = QFrame()
        row.setObjectName("historyItemCard")
        row.setProperty(
            "selected",
            "true" if record.get("id") in self.selected_history_ids else "false",
        )
        row.setProperty("pinned", "true" if record.get("pinned", False) else "false")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(7, 6, 7, 6)
        row_layout.setSpacing(6)

        chat_id = record.get("id")
        is_selected = chat_id in self.selected_history_ids

        select_button = QPushButton("✓" if is_selected else "Select")
        select_button.setObjectName("historySelectButton")
        select_button.setCheckable(True)
        select_button.setChecked(is_selected)
        select_button.setFixedSize(56, 30)
        select_button.setCursor(Qt.PointingHandCursor)
        select_button.setToolTip(
            "Remove this chat from the memory selection"
            if is_selected
            else "Select this chat for persistent-memory extraction"
        )
        select_button.toggled.connect(
            lambda selected, control=select_button, chat_id=chat_id: self.handle_history_selection_toggle(
                control, chat_id, selected
            )
        )

        title_button = QPushButton(display_title)
        title_button.setObjectName("historyButton")
        title_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        title_button.setMinimumWidth(0)
        title_button.setFixedHeight(30)
        title_button.setToolTip(raw_title)
        title_button.clicked.connect(
            lambda _checked=False, chat_id=chat_id: self.load_chat(chat_id)
        )

        pin_button = QPushButton("Unpin" if record.get("pinned", False) else "Pin")
        pin_button.setObjectName("historyActionButton")
        pin_button.setFixedSize(48, 30)
        pin_button.setCursor(Qt.PointingHandCursor)
        pin_button.setToolTip(
            "Unpin this chat" if record.get("pinned", False) else "Pin this chat"
        )
        pin_button.clicked.connect(
            lambda _checked=False, chat_id=chat_id: self.toggle_pin_chat(chat_id)
        )

        more_button = QPushButton("More")
        more_button.setObjectName("historyMoreButton")
        more_button.setFixedSize(50, 30)
        more_button.setCursor(Qt.PointingHandCursor)
        more_button.setToolTip("Rename or delete this saved chat")

        more_menu = QMenu(more_button)

        rename_action = more_menu.addAction("Rename")
        rename_action.triggered.connect(
            lambda _checked=False, chat_id=chat_id: self.rename_chat(chat_id)
        )

        delete_action = more_menu.addAction("Delete")
        delete_action.triggered.connect(
            lambda _checked=False, chat_id=chat_id: self.delete_chat(chat_id)
        )

        more_button.setMenu(more_menu)

        row_layout.addWidget(select_button, 0)
        row_layout.addWidget(title_button, 1)
        row_layout.addWidget(pin_button, 0)
        row_layout.addWidget(more_button, 0)

        self.history_list.addWidget(row)

    self.history_list.addStretch()
    self.update_history_selection_ui()


def handle_history_selection_toggle(self, button, chat_id, selected):
    """Keep the visible selector and the selected-history set in sync."""
    button.setText("✓" if selected else "Select")
    button.setToolTip(
        "Remove this chat from the memory selection"
        if selected
        else "Select this chat for persistent-memory extraction"
    )

    row = button.parentWidget()

    if row is not None:
        row.setProperty("selected", "true" if selected else "false")
        row.style().unpolish(row)
        row.style().polish(row)
        row.update()

    self.update_history_selection(chat_id, selected)


def update_history_selection(self, chat_id, selected):
    if not chat_id:
        return

    if selected:
        self.selected_history_ids.add(chat_id)
    else:
        self.selected_history_ids.discard(chat_id)

    self.update_history_selection_ui()


def update_history_selection_ui(self):
    valid_ids = {record.get("id") for record in self.chat_history if record.get("id")}
    self.selected_history_ids.intersection_update(valid_ids)
    selected_count = len(self.selected_history_ids)

    if hasattr(self, "history_selection_label"):
        self.history_selection_label.setText(f"{selected_count} selected")

    busy = bool(self.memory_worker and self.memory_worker.isRunning())

    if hasattr(self, "remember_selected_button"):
        self.remember_selected_button.setEnabled(selected_count > 0 and not busy)

    if hasattr(self, "clear_history_selection_button"):
        self.clear_history_selection_button.setEnabled(selected_count > 0 and not busy)

    if getattr(self, "memory_stop_button", None) is not None:
        self.memory_stop_button.setVisible(busy)
        self.memory_stop_button.setEnabled(busy)
        self.memory_stop_button.setText("Stop Extraction")

    if hasattr(self, "import_documents_memory_button"):
        knowledge_busy = bool(
            self.knowledge_worker and self.knowledge_worker.isRunning()
        )
        self.import_documents_memory_button.setEnabled(not busy and not knowledge_busy)

    if hasattr(self, "open_persistent_memory_button"):
        self.open_persistent_memory_button.setEnabled(not busy)


def clear_history_selection(self):
    self.selected_history_ids.clear()
    self.render_history()


def history_message_to_text(self, content, news_sources=None):
    if isinstance(content, list):
        parts = []

        for part in content:
            if not isinstance(part, dict):
                continue

            if part.get("type") == "text":
                parts.append(str(part.get("text", "")))

        text = "\n".join(parts)
    else:
        text = str(content or "")

    # Convert structured market cards to readable text before memory
    # extraction. This lets explicitly selected quote chats be retained as
    # dated snapshots instead of being rejected as opaque JSON.
    quote_payload = parse_stock_quote_payload(text)

    if quote_payload is not None:
        text = stock_quote_plain_text(quote_payload)

    # History stores exact news source metadata separately from the Markdown
    # response. Expand citation IDs before extraction so every retained article
    # keeps its publisher and URL rather than an opaque NEWS_#### token.
    for source_id, source_value in (news_sources or {}).items():
        clean_id = str(source_id or "").strip()

        if not clean_id:
            continue

        if isinstance(source_value, dict):
            source_name = str(source_value.get("name") or "Source").strip()
            source_url = str(source_value.get("url") or "").strip()
        else:
            source_name = clean_id
            source_url = str(source_value or "").strip()

        replacement_text = source_name

        if source_url:
            replacement_text += f" ({source_url})"

        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(clean_id)}(?![A-Za-z0-9_])",
            replacement_text,
            text,
        )

    complete_source_records = []

    for source_id, source_value in (news_sources or {}).items():
        if not isinstance(source_value, dict):
            continue

        source_title = re.sub(r"\s+", " ", str(source_value.get("title") or "")).strip()
        source_summary = re.sub(
            r"\s+", " ", str(source_value.get("summary") or "")
        ).strip()
        source_published_at = re.sub(
            r"\s+", " ", str(source_value.get("published_at") or "")
        ).strip()
        source_image_url = str(source_value.get("image_url") or "").strip()
        source_name = str(source_value.get("name") or "Source").strip()
        source_url = str(source_value.get("url") or "").strip()

        # Older history contains only name/url. Do not fabricate a headline
        # for those records; displayed bullets are still extracted normally.
        if not source_title and not source_summary:
            continue

        article_text = source_title or source_summary

        if source_summary and source_summary.casefold() not in article_text.casefold():
            article_text += f" Summary: {source_summary}"

        article_text += f" Source: {source_name}"

        if source_published_at:
            article_text += f" Published: {source_published_at}"

        if source_url:
            article_text += f" URL: {source_url}"

        if source_image_url:
            article_text += f" Image: {source_image_url}"

        complete_source_records.append(f"- {article_text}")

    if complete_source_records:
        text += "\n\n## Complete Daily News Source Records\n\n" + "\n\n".join(
            complete_source_records
        )

    for pattern in (
        r"\n\n\[INTERNET CONTEXT\].*",
        r"\n\n\[STOCK QUOTE\].*",
    ):
        text = re.sub(pattern, "", text, flags=re.DOTALL).strip()

    # Keep exact source-code attachments (especially .py files) for memory
    # while still excluding ordinary document bodies that belong in the
    # separate Document Knowledge Library.
    text = preserve_source_attachments_for_memory(text)

    return text


def build_history_memory_transcript(self, records):
    chat_sections = []

    for record in records:
        title = str(record.get("title", "New Chat")).strip()
        created = str(record.get("created", "")).strip()
        lines = [f"CHAT TITLE: {title}", f"CHAT CREATED: {created or 'Unknown'}"]

        for message in record.get("messages", []):
            role = str(message.get("role", "unknown")).upper()
            text = self.history_message_to_text(
                message.get("content", ""), message.get("news_sources", {})
            ).strip()

            if not text:
                continue

            lines.append(f"{role}: {text}")

        chat_sections.append("\n\n".join(lines))

    # Do not cut the middle of long news briefs. MemoryExtractionWorker
    # processes this complete transcript in bounded chunks.
    return "\n\n==============================\n\n".join(chat_sections)


def clear_all_history(self):
    self.chat_history = [
        record for record in self.chat_history if record.get("pinned", False)
    ]

    save_chat_history(self.chat_history)
    self.selected_history_ids.intersection_update(
        {record.get("id") for record in self.chat_history}
    )
    self.render_history()


def toggle_history_panel(self):
    show_panel = not self.history_panel.isVisible()
    self.history_panel.setVisible(show_panel)
    self.history_button.setChecked(show_panel)

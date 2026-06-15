import json
import re
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..config import MEMORY_SCHEMA_VERSION
from ..memory_store import (
    normalize_memory_entry,
    normalize_persistent_memory,
    parse_memory_extraction_payload,
    save_persistent_memory,
)
from ..workers import MemoryExtractionWorker


def remember_selected_history(self):
    if self.memory_worker and self.memory_worker.isRunning():
        return

    if self.worker and self.worker.isRunning():
        self.stats_label.setText(
            "Finish or stop the current response before importing memory"
        )
        return

    if (
        hasattr(self, "decision_worker")
        and self.decision_worker
        and self.decision_worker.isRunning()
    ):
        self.stats_label.setText(
            "Finish or stop the web decision before importing memory"
        )
        return

    if hasattr(self, "web_worker") and self.web_worker and self.web_worker.isRunning():
        self.stats_label.setText(
            "Finish or stop the web search before importing memory"
        )
        return

    self.save_current_chat()

    selected_records = [
        record
        for record in self.chat_history
        if record.get("id") in self.selected_history_ids
    ]

    if not selected_records:
        self.stats_label.setText("Select at least one history chat")
        self.update_history_selection_ui()
        return

    transcript = self.build_history_memory_transcript(selected_records)

    if not transcript.strip():
        self.stats_label.setText("Selected chats contain no extractable text")
        return

    memory_base_url = self.current_base_url()
    memory_api_key = self.current_api_key()
    self.pending_memory_source_records = selected_records
    self.memory_worker = MemoryExtractionWorker(
        transcript, self.current_model_name(), memory_base_url, memory_api_key
    )
    self.memory_worker.extraction_ready.connect(self.handle_memory_extraction_ready)
    self.memory_worker.error_received.connect(self.handle_memory_extraction_error)
    self.memory_worker.progress_updated.connect(self.update_memory_extraction_progress)
    self.memory_worker.stopped.connect(self.handle_memory_extraction_stopped)
    self.memory_worker.finished.connect(self.finish_memory_extraction_worker)

    self.stats_label.setText(
        f"Extracting useful memory from {len(selected_records)} selected chat(s)..."
    )
    self.memory_worker.start()
    self.update_history_selection_ui()


def update_memory_extraction_progress(self, current_chunk, total_chunks):
    self.stats_label.setText(
        f"Extracting non-news memory • chunk {current_chunk}/{total_chunks}"
    )


def stop_memory_extraction(self):
    worker = self.memory_worker

    if worker is None or not worker.isRunning():
        return

    if self.memory_stop_button is not None:
        self.memory_stop_button.setText("Stopping...")
        self.memory_stop_button.setEnabled(False)

    self.stats_label.setText("Stopping persistent-memory extraction...")
    worker.stop()


def handle_memory_extraction_stopped(self):
    self.pending_memory_source_records = []
    self.stats_label.setText("Persistent-memory extraction stopped")


def finish_memory_extraction_worker(self):
    worker = self.memory_worker
    self.memory_worker = None

    if worker is not None:
        worker.deleteLater()

    self.update_history_selection_ui()


def handle_memory_extraction_error(self, error_text):
    self.pending_memory_source_records = []
    self.stats_label.setText("Memory extraction failed")
    QMessageBox.warning(
        self,
        "Persistent Memory",
        "Could not extract memory from the selected history chats.\n\n"
        + str(error_text),
    )


def handle_memory_extraction_ready(self, extracted_text):
    extracted_entries = parse_memory_extraction_payload(extracted_text)

    if not extracted_entries:
        self.pending_memory_source_records = []
        self.stats_label.setText("No useful memory found")
        QMessageBox.information(
            self,
            "Persistent Memory",
            "The selected chats did not contain meaningful reusable information for persistent memory.",
        )
        return

    source_records = list(self.pending_memory_source_records)

    dialog = QDialog(self)
    dialog.setWindowTitle("Review Structured Persistent Memory")
    dialog.resize(980, 720)

    layout = QVBoxLayout(dialog)
    explanation = QLabel(
        "Review the structured entries extracted from the selected chats. Long news briefs are split into "
        "one snapshot entry per article instead of broad category summaries. Fenced code blocks and attached "
        "source files are preserved exactly, with large files split into ordered searchable parts. Checked "
        "entries will be stored in memory.json. Double-click an entry to edit its fields."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    review_list = QListWidget()
    review_list.setObjectName("persistentMemoryList")
    review_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    review_list.setWordWrap(True)
    review_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def update_review_item(item, entry):
        item.setText(self.format_persistent_memory_item(entry))
        item.setData(Qt.UserRole, entry)
        item.setToolTip(json.dumps(entry, ensure_ascii=False, indent=2))

    for entry in extracted_entries:
        item = QListWidgetItem()
        item.setFlags(
            item.flags()
            | Qt.ItemIsUserCheckable
            | Qt.ItemIsSelectable
            | Qt.ItemIsEnabled
        )
        item.setCheckState(Qt.Checked)
        update_review_item(item, entry)
        review_list.addItem(item)

    def edit_review_item(item=None):
        if item is None:
            selected = review_list.selectedItems()

            if not selected:
                return

            item = selected[0]

        entry = item.data(Qt.UserRole)
        updated = self.show_persistent_memory_entry_editor(entry)

        if updated is not None:
            update_review_item(item, updated)

    review_list.itemDoubleClicked.connect(edit_review_item)
    layout.addWidget(review_list, 1)

    action_row = QHBoxLayout()
    edit_button = QPushButton("Edit Selected")
    edit_button.clicked.connect(lambda: edit_review_item())
    action_row.addWidget(edit_button)
    action_row.addStretch()
    layout.addLayout(action_row)

    replace_existing = QCheckBox(
        "Replace all existing persistent-memory entries instead of appending"
    )
    layout.addWidget(replace_existing)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        self.pending_memory_source_records = []
        self.stats_label.setText("Memory import cancelled")
        return

    reviewed_entries = []

    for index in range(review_list.count()):
        item = review_list.item(index)

        if item.checkState() != Qt.Checked:
            continue

        entry = normalize_memory_entry(item.data(Qt.UserRole), default_source="history")

        if entry is not None:
            reviewed_entries.append(entry)

    if not reviewed_entries:
        self.pending_memory_source_records = []
        self.stats_label.setText("No memory saved: no entries were checked")
        return

    self.commit_history_memory(
        reviewed_entries, source_records, replace_existing.isChecked()
    )


def commit_history_memory(self, memory_entries, source_records, replace_existing=False):
    source_titles = []

    for record in source_records:
        title = re.sub(r"\s+", " ", str(record.get("title", "New Chat"))).strip()

        if title and title not in source_titles:
            source_titles.append(title)

    imported_at = datetime.now().isoformat(timespec="seconds")
    prepared_entries = []

    for raw_entry in memory_entries:
        payload = dict(raw_entry or {})
        payload["source"] = str(payload.get("source") or "history").strip()

        if not payload.get("source_titles"):
            payload["source_titles"] = source_titles

        payload["created_at"] = payload.get("created_at") or imported_at
        payload["updated_at"] = imported_at
        entry = normalize_memory_entry(payload, default_source="history")

        if entry is not None:
            prepared_entries.append(entry)

    if not prepared_entries:
        self.pending_memory_source_records = []
        self.stats_label.setText("No valid structured memory entries were produced")
        return

    existing_entries = (
        []
        if replace_existing
        else list(self.persistent_memory_data.get("entries") or [])
    )

    existing_keys = {
        (
            str(entry.get("category") or ""),
            str(entry.get("title") or "").casefold(),
            str(entry.get("content") or "").casefold(),
            str(entry.get("snapshot_date") or ""),
        )
        for entry in existing_entries
    }

    added_entries = []

    for entry in prepared_entries:
        key = (
            str(entry.get("category") or ""),
            str(entry.get("title") or "").casefold(),
            str(entry.get("content") or "").casefold(),
            str(entry.get("snapshot_date") or ""),
        )

        if key in existing_keys:
            continue

        existing_keys.add(key)
        existing_entries.append(entry)
        added_entries.append(entry)

    if not added_entries and not replace_existing:
        self.pending_memory_source_records = []
        self.stats_label.setText("The selected memories already exist")
        QMessageBox.information(
            self,
            "Persistent Memory",
            "All reviewed structured entries are already stored.",
        )
        return

    self.persistent_memory_data = normalize_persistent_memory(
        {"version": MEMORY_SCHEMA_VERSION, "entries": existing_entries}
    )

    if not save_persistent_memory(self.persistent_memory_data):
        self.stats_label.setText("Could not save persistent memory")
        QMessageBox.warning(
            self, "Persistent Memory", "The JSON memory file could not be written."
        )
        return

    self.refresh_persistent_memory_list()
    self.selected_history_ids.clear()
    self.pending_memory_source_records = []
    self.render_history()

    saved_count = len(added_entries) if not replace_existing else len(existing_entries)
    self.stats_label.setText(
        f"Saved {saved_count} structured memory entr"
        + ("y" if saved_count == 1 else "ies")
    )
    QMessageBox.information(
        self,
        "Persistent Memory",
        f"Saved {saved_count} structured entr"
        + ("y" if saved_count == 1 else "ies")
        + " to memory.json. They will be supplied to future chats.",
    )

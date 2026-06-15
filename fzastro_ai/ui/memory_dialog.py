import json
import re
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..config import MEMORY_CATEGORIES
from ..memory_store import (
    empty_persistent_memory,
    normalize_memory_entry,
    normalize_persistent_memory,
    save_persistent_memory,
    search_persistent_memory_entries,
)


def format_persistent_memory_item(self, entry):
    category = str(entry.get("category") or "other").upper()
    title = re.sub(r"\s+", " ", str(entry.get("title") or "Untitled")).strip()
    content = re.sub(r"\s+", " ", str(entry.get("content") or "")).strip()
    snapshot_date = str(entry.get("snapshot_date") or "").strip()

    if len(content) > 320:
        content = content[:317].rstrip() + "..."

    first_line = f"{category}  •  {title}"

    if snapshot_date:
        first_line += f"  •  {snapshot_date}"

    return first_line + "\n" + content


def refresh_persistent_memory_list(self):
    self.persistent_memory_data = normalize_persistent_memory(
        getattr(self, "persistent_memory_data", empty_persistent_memory())
    )
    entries = self.persistent_memory_data.get("entries") or []
    character_count = sum(
        len(str(entry.get("title") or "")) + len(str(entry.get("content") or ""))
        for entry in entries
    )

    if hasattr(self, "persistent_memory_summary_label"):
        self.persistent_memory_summary_label.setText(
            f"{len(entries):,} structured entries • {character_count:,} characters\n"
            "Relevant entries are retrieved automatically for each request."
        )

    if self.memory_list_widget is not None:
        try:
            selected_ids = {
                str(item.data(Qt.UserRole) or "")
                for item in self.memory_list_widget.selectedItems()
            }
            self.memory_list_widget.clear()

            for entry in entries:
                item = QListWidgetItem(self.format_persistent_memory_item(entry))
                item.setData(Qt.UserRole, entry.get("id"))
                item.setToolTip(json.dumps(entry, ensure_ascii=False, indent=2))
                self.memory_list_widget.addItem(item)

                if str(entry.get("id") or "") in selected_ids:
                    item.setSelected(True)

        except RuntimeError:
            self.memory_list_widget = None

    if self.memory_status_label is not None:
        try:
            self.memory_status_label.setText(
                f"{len(entries):,} structured entries • {character_count:,} characters • stored in memory.json"
            )
        except RuntimeError:
            self.memory_status_label = None


def save_persistent_memory_from_ui(self):
    saved = save_persistent_memory(self.persistent_memory_data)

    if saved:
        self.stats_label.setText("Structured persistent memory saved")
        self.refresh_persistent_memory_list()
    else:
        self.stats_label.setText("Could not save persistent memory")

    return saved


def open_persistent_memory_library(self):
    dialog = QDialog(self)
    dialog.setWindowTitle("Persistent Memory Library")
    dialog.resize(980, 760)
    self.memory_dialog = dialog

    layout = QVBoxLayout(dialog)

    explanation = QLabel(
        "Persistent memories are stored as complete structured JSON entries in a local library. "
        "The app searches the full library for each question and injects only the most relevant "
        "entries, so hundreds or thousands of saved articles and facts do not consume the context "
        "window on every request."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    self.memory_list_widget = QListWidget()
    self.memory_list_widget.setObjectName("systemPromptBox")
    self.memory_list_widget.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
    )
    self.memory_list_widget.setWordWrap(True)
    self.memory_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    self.memory_list_widget.itemDoubleClicked.connect(
        lambda _item: self.edit_selected_persistent_memory_entry()
    )
    layout.addWidget(self.memory_list_widget, 1)

    self.memory_status_label = QLabel()
    self.memory_status_label.setObjectName("webArticleBody")
    layout.addWidget(self.memory_status_label)

    action_row = QHBoxLayout()
    action_row.setSpacing(8)

    self.memory_add_button = QPushButton("Add Entry")
    self.memory_add_button.clicked.connect(self.add_persistent_memory_entry)

    self.memory_edit_button = QPushButton("Edit Selected")
    self.memory_edit_button.clicked.connect(self.edit_selected_persistent_memory_entry)

    self.memory_delete_button = QPushButton("Remove Selected")
    self.memory_delete_button.clicked.connect(
        self.delete_selected_persistent_memory_entries
    )

    self.memory_clear_button = QPushButton("Clear Library")
    self.memory_clear_button.clicked.connect(self.clear_persistent_memory_library)

    action_row.addWidget(self.memory_add_button)
    action_row.addWidget(self.memory_edit_button)
    action_row.addWidget(self.memory_delete_button)
    action_row.addWidget(self.memory_clear_button)
    action_row.addStretch()
    layout.addLayout(action_row)

    search_label = QLabel("Test Memory Search")
    layout.addWidget(search_label)

    search_row = QHBoxLayout()
    self.memory_search_input = QLineEdit()
    self.memory_search_input.setPlaceholderText(
        "Example: SpaceX IPO, DBX price, astrophotography workflow, UI preference"
    )
    search_button = QPushButton("Search")
    search_button.clicked.connect(self.test_persistent_memory_search)
    self.memory_search_input.returnPressed.connect(self.test_persistent_memory_search)
    search_row.addWidget(self.memory_search_input, 1)
    search_row.addWidget(search_button)
    layout.addLayout(search_row)

    self.memory_search_preview = QTextEdit()
    self.memory_search_preview.setObjectName("systemPromptBox")
    self.memory_search_preview.setReadOnly(True)
    self.memory_search_preview.setPlaceholderText(
        "Relevant memory entries will appear here."
    )
    self.memory_search_preview.setFixedHeight(230)
    layout.addWidget(self.memory_search_preview)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    self.memory_close_button = buttons.button(QDialogButtonBox.StandardButton.Close)

    self.refresh_persistent_memory_list()
    dialog.exec()

    self.memory_dialog = None
    self.memory_list_widget = None
    self.memory_status_label = None
    self.memory_search_input = None
    self.memory_search_preview = None
    self.memory_add_button = None
    self.memory_edit_button = None
    self.memory_delete_button = None
    self.memory_clear_button = None
    self.memory_close_button = None


def test_persistent_memory_search(self):
    if self.memory_search_input is None or self.memory_search_preview is None:
        return

    query = self.memory_search_input.text().strip()

    if not query:
        self.memory_search_preview.setPlainText("Enter a search query.")
        return

    matches = search_persistent_memory_entries(
        self.persistent_memory_data, query, max_results=25
    )

    if not matches:
        self.memory_search_preview.setPlainText(
            "No matching persistent-memory entries were found."
        )
        return

    result_lines = []

    for index, entry in enumerate(matches, start=1):
        header = (
            f"{index}. {str(entry.get('category') or 'other').upper()} — "
            f"{entry.get('title') or 'Untitled'}"
        )
        snapshot_date = str(entry.get("snapshot_date") or "").strip()

        if snapshot_date:
            header += f" — {snapshot_date}"

        result_lines.extend([header, str(entry.get("content") or "").strip(), ""])

    self.memory_search_preview.setPlainText("\n".join(result_lines).strip())


def show_persistent_memory_entry_editor(self, entry=None):
    existing = normalize_memory_entry(entry or {}) if entry else None
    parent = self.memory_dialog if self.memory_dialog is not None else self

    dialog = QDialog(parent)
    dialog.setWindowTitle(
        "Edit Persistent Memory" if existing else "Add Persistent Memory"
    )
    dialog.resize(720, 500)

    layout = QVBoxLayout(dialog)
    explanation = QLabel(
        "Create one complete structured memory entry. It will be stored in memory.json "
        "and retrieved automatically when a future question is relevant."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    fields = QGridLayout()
    fields.setHorizontalSpacing(10)
    fields.setVerticalSpacing(8)

    category_box = QComboBox()
    category_box.addItems([category.capitalize() for category in MEMORY_CATEGORIES])

    title_edit = QLineEdit()
    title_edit.setPlaceholderText("Short descriptive title")

    content_edit = QTextEdit()
    content_edit.setObjectName("systemPromptBox")
    content_edit.setPlaceholderText(
        "The complete self-contained fact, preference, decision, procedure, article, or dated snapshot."
    )
    content_edit.setFixedHeight(190)

    snapshot_edit = QLineEdit()
    snapshot_edit.setPlaceholderText(
        "Optional date/timestamp for time-sensitive information"
    )

    tags_edit = QLineEdit()
    tags_edit.setPlaceholderText("Optional comma-separated tags")

    fields.addWidget(QLabel("Category"), 0, 0)
    fields.addWidget(category_box, 0, 1)
    fields.addWidget(QLabel("Title"), 1, 0)
    fields.addWidget(title_edit, 1, 1)
    fields.addWidget(QLabel("Content"), 2, 0, Qt.AlignTop)
    fields.addWidget(content_edit, 2, 1)
    fields.addWidget(QLabel("Snapshot date"), 3, 0)
    fields.addWidget(snapshot_edit, 3, 1)
    fields.addWidget(QLabel("Tags"), 4, 0)
    fields.addWidget(tags_edit, 4, 1)
    fields.setColumnStretch(1, 1)
    layout.addLayout(fields)

    if existing:
        category_box.setCurrentText(
            str(existing.get("category") or "other").capitalize()
        )
        title_edit.setText(str(existing.get("title") or ""))
        content_edit.setPlainText(str(existing.get("content") or ""))
        snapshot_edit.setText(str(existing.get("snapshot_date") or ""))
        tags_edit.setText(", ".join(existing.get("tags") or []))

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    content = content_edit.toPlainText().strip()

    if not content:
        QMessageBox.information(
            parent, "Persistent Memory", "The memory content cannot be empty."
        )
        return None

    tags = [value.strip() for value in tags_edit.text().split(",") if value.strip()]

    payload = dict(existing or {})
    payload.update(
        {
            "category": category_box.currentText().lower(),
            "title": title_edit.text().strip(),
            "content": content,
            "snapshot_date": snapshot_edit.text().strip() or None,
            "tags": tags,
            "source": (existing or {}).get("source", "manual"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )

    return normalize_memory_entry(payload)


def add_persistent_memory_entry(self):
    entry = self.show_persistent_memory_entry_editor()

    if entry is None:
        return

    self.persistent_memory_data.setdefault("entries", []).append(entry)
    self.persistent_memory_data = normalize_persistent_memory(
        self.persistent_memory_data
    )

    if self.save_persistent_memory_from_ui():
        self.stats_label.setText("Persistent memory entry added")


def selected_persistent_memory_entry_ids(self):
    if self.memory_list_widget is None:
        return []

    try:
        return [
            str(item.data(Qt.UserRole) or "")
            for item in self.memory_list_widget.selectedItems()
            if str(item.data(Qt.UserRole) or "")
        ]
    except RuntimeError:
        return []


def edit_selected_persistent_memory_entry(self):
    selected_ids = self.selected_persistent_memory_entry_ids()

    if len(selected_ids) != 1:
        self.stats_label.setText("Select one persistent-memory entry to edit")
        return

    selected_id = selected_ids[0]
    entries = self.persistent_memory_data.get("entries") or []
    existing = next(
        (entry for entry in entries if entry.get("id") == selected_id), None
    )

    if existing is None:
        return

    updated = self.show_persistent_memory_entry_editor(existing)

    if updated is None:
        return

    for index, entry in enumerate(entries):
        if entry.get("id") == selected_id:
            entries[index] = updated
            break

    self.persistent_memory_data["entries"] = entries

    if self.save_persistent_memory_from_ui():
        self.stats_label.setText("Persistent memory entry updated")


def delete_selected_persistent_memory_entries(self):
    selected_ids = set(self.selected_persistent_memory_entry_ids())

    if not selected_ids:
        self.stats_label.setText("Select persistent-memory entries to delete")
        return

    parent = self.memory_dialog if self.memory_dialog is not None else self
    answer = QMessageBox.question(
        parent,
        "Delete Persistent Memory",
        f"Delete {len(selected_ids)} selected memory entr"
        + ("y?" if len(selected_ids) == 1 else "ies?"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if answer != QMessageBox.StandardButton.Yes:
        return

    self.persistent_memory_data["entries"] = [
        entry
        for entry in self.persistent_memory_data.get("entries") or []
        if entry.get("id") not in selected_ids
    ]

    if self.save_persistent_memory_from_ui():
        self.stats_label.setText(
            f"Deleted {len(selected_ids)} persistent-memory entr"
            + ("y" if len(selected_ids) == 1 else "ies")
        )


def clear_persistent_memory_library(self):
    entries = self.persistent_memory_data.get("entries") or []

    if not entries:
        return

    parent = self.memory_dialog if self.memory_dialog is not None else self
    answer = QMessageBox.question(
        parent,
        "Clear Persistent Memory Library",
        f"Delete all {len(entries):,} persistent-memory entries?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )

    if answer != QMessageBox.StandardButton.Yes:
        return

    self.persistent_memory_data = empty_persistent_memory()

    if self.save_persistent_memory_from_ui():
        self.stats_label.setText("Persistent memory library cleared")

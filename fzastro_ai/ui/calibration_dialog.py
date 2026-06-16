from datetime import datetime

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .message_widgets import SystemPromptTextEdit
from .window_utils import apply_window_defaults


def open_system_prompt_editor(self):
    dialog = QDialog(self)
    apply_window_defaults(dialog)
    dialog.setWindowTitle("AI Role / System Prompt")
    dialog.resize(1050, 800)
    self.system_prompt_dialog = dialog

    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)

    explanation = QLabel(
        "Edit the complete system prompt in a dedicated workspace. "
        "Each calibration keeps its own saved prompt. Press Enter in the "
        "editor to save; use Shift+Enter for a new line. Save does not "
        "close this window."
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    profile_row = QHBoxLayout()
    profile_row.setSpacing(8)
    profile_row.addWidget(QLabel("Load calibration:"))

    draft_profile_label = QLabel()
    draft_profile_label.setObjectName("calibrationStatusLabel")

    active_profile_key = getattr(self, "active_calibration_profile", "precise")

    if active_profile_key not in self.calibration_profiles:
        active_profile_key = "precise"

    draft_state = {"profile_key": active_profile_key}

    editor = SystemPromptTextEdit()
    editor.setObjectName("systemPromptBox")
    editor.setPlainText(self.calibration_profiles[active_profile_key]["prompt"])
    editor.setAcceptRichText(False)
    self.system_prompt_editor = editor

    save_status_label = QLabel("")
    save_status_label.setObjectName("webArticleBody")

    def current_profile():
        profile_key = draft_state["profile_key"]
        return profile_key, self.calibration_profiles[profile_key]

    def refresh_editor_status():
        profile_key, profile = current_profile()
        current_text = editor.toPlainText().strip()
        stored_text = str(profile.get("prompt") or "").strip()
        default_text = str(profile.get("default_prompt") or "").strip()

        if current_text != stored_text:
            state_text = "unsaved edits"
        elif stored_text != default_text:
            state_text = "saved custom"
        else:
            state_text = "built-in"

        draft_profile_label.setText(
            f"Draft calibration: {profile['name']} • {state_text}"
        )
        self.system_prompt_character_label.setText(
            f"{len(editor.toPlainText()):,} characters"
        )

    def load_profile(profile_key):
        if profile_key not in self.calibration_profiles:
            return

        draft_state["profile_key"] = profile_key
        profile = self.calibration_profiles[profile_key]
        editor.setPlainText(profile["prompt"])
        save_status_label.setText(f"Loaded {profile['name']} calibration")
        editor.setFocus()

    for profile_key in ("precise", "architect", "explorer", "companion"):
        profile = self.calibration_profiles[profile_key]
        button = QPushButton(profile["name"])
        button.setToolTip(
            profile["tooltip"]
            + " — loads this profile's saved custom prompt when available"
        )
        button.clicked.connect(
            lambda _checked=False, key=profile_key: load_profile(key)
        )
        profile_row.addWidget(button)

    restore_button = QPushButton("Restore Default")
    restore_button.setToolTip(
        "Immediately restore and save the built-in version of the "
        "selected calibration."
    )

    def restore_default_profile():
        profile_key, profile = current_profile()
        default_prompt = str(profile.get("default_prompt") or "").strip()

        if not default_prompt:
            QMessageBox.warning(
                dialog,
                "AI Role / System Prompt",
                "The built-in prompt for this calibration is unavailable.",
            )
            return

        # Reset both the visible draft and the saved profile.  This removes
        # the custom override from calibration_profiles.json immediately,
        # so loading the profile again cannot bring the old custom text back.
        profile["prompt"] = default_prompt
        profile["customized"] = False
        profile["updated_at"] = datetime.now().isoformat(timespec="seconds")

        editor.blockSignals(True)
        editor.setPlainText(default_prompt)
        editor.blockSignals(False)

        self.active_calibration_profile = profile_key
        self.persist_calibration_profile_store()
        self.apply_calibration_profile(profile_key, announce=False)

        restored_time = datetime.now().strftime("%H:%M:%S")
        save_status_label.setText(
            f"Restored built-in {profile['name']} calibration " f"at {restored_time}"
        )
        self.stats_label.setText(f"{profile['name']} defaults restored")
        refresh_editor_status()
        editor.setFocus()

    restore_button.clicked.connect(restore_default_profile)
    profile_row.addWidget(restore_button)
    profile_row.addStretch()
    profile_row.addWidget(draft_profile_label)
    layout.addLayout(profile_row)

    search_row = QHBoxLayout()
    search_input = QLineEdit()
    search_input.setPlaceholderText("Find text in the system prompt")
    find_button = QPushButton("Find Next")

    def find_next():
        query = search_input.text()

        if not query:
            return

        if not editor.find(query):
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            editor.find(query)

    find_button.clicked.connect(find_next)
    search_input.returnPressed.connect(find_button.click)
    search_row.addWidget(search_input, 1)
    search_row.addWidget(find_button)
    layout.addLayout(search_row)

    layout.addWidget(editor, 1)

    footer_row = QHBoxLayout()
    self.system_prompt_character_label = QLabel()
    self.system_prompt_character_label.setObjectName("webArticleBody")
    footer_row.addWidget(self.system_prompt_character_label)
    footer_row.addSpacing(16)
    footer_row.addWidget(save_status_label)
    footer_row.addStretch()
    layout.addLayout(footer_row)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
    )
    save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
    close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
    close_button.setToolTip("Close the editor. Unsaved changes are not applied.")

    def save_without_closing():
        prompt_text = editor.toPlainText().strip()

        if not prompt_text:
            QMessageBox.information(
                dialog,
                "AI Role / System Prompt",
                "The system prompt cannot be empty.",
            )
            return

        profile_key, profile = current_profile()
        profile["prompt"] = prompt_text
        profile["updated_at"] = datetime.now().isoformat(timespec="seconds")
        profile["customized"] = (
            prompt_text != str(profile.get("default_prompt") or "").strip()
        )

        self.active_calibration_profile = profile_key
        self.persist_calibration_profile_store()
        self.apply_calibration_profile(profile_key, announce=False)

        editor.blockSignals(True)
        editor.setPlainText(profile["prompt"])
        editor.blockSignals(False)

        saved_time = datetime.now().strftime("%H:%M:%S")
        save_status_label.setText(
            f"Saved {profile['name']} calibration at {saved_time}"
        )
        self.stats_label.setText(f"{profile['name']} system prompt saved")
        refresh_editor_status()

    save_button.clicked.connect(save_without_closing)
    editor.save_requested.connect(save_button.click)
    close_button.clicked.connect(dialog.reject)
    layout.addWidget(buttons)

    editor.textChanged.connect(refresh_editor_status)
    refresh_editor_status()
    dialog.exec()

    self.system_prompt_dialog = None
    self.system_prompt_editor = None
    self.system_prompt_editor_status = None
    self.system_prompt_character_label = None

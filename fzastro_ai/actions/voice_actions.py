"""Offline voice-command actions for the FZAstro AI main window."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_DIR
from ..logging_utils import log_exception, log_warning
from ..skill_registry import SKILL_ACTION_BY_ID
from ..ui.window_utils import apply_window_defaults
from ..voice import resolve_voice_command, voice_help_examples
from ..workers.voice_command_worker import VoiceCommandWorker


class VoiceActionsMixin:
    """Push-to-talk offline voice-command controller."""

    def default_vosk_model_path(self) -> Path:
        configured = os.environ.get("FZASTRO_VOSK_MODEL", "").strip()
        if configured:
            return Path(configured).expanduser()

        configured_root = os.environ.get("FZASTRO_VOICE_MODELS_DIR", "").strip()
        root = (
            Path(configured_root).expanduser()
            if configured_root
            else Path(APP_DIR) / "voice_models"
        )
        preferred_names = (
            "vosk-model-small-en-us-0.15",
            "vosk-model-en-us-0.22",
        )
        for name in preferred_names:
            candidate = root / name
            if self._looks_like_vosk_model(candidate):
                return candidate

        if root.exists():
            for candidate in sorted(root.glob("vosk-model*")):
                if self._looks_like_vosk_model(candidate):
                    return candidate

        return root / preferred_names[0]

    def _looks_like_vosk_model(self, path: Path) -> bool:
        if not path or not path.is_dir():
            return False
        return all((path / name).exists() for name in ("am", "conf", "graph"))

    def _set_voice_button_recording(self, recording: bool):
        button = getattr(self, "voice_button", None)
        if button is None:
            return

        button.setText("")
        button.setChecked(bool(recording))
        icon_name = "_voice_icon_recording" if recording else "_voice_icon_idle"
        icon = getattr(self, icon_name, None)
        if icon is not None:
            button.setIcon(icon)
        button.setToolTip(
            "Stop offline voice capture"
            if recording
            else "Offline voice command. Say: what can I say"
        )
        button.setEnabled(True)

    def toggle_offline_voice_command(self):
        worker = getattr(self, "voice_worker", None)
        if worker is not None and worker.isRunning():
            worker.request_stop()
            self.stats_label.setText("Processing offline voice command…")
            return

        self.start_offline_voice_command()

    def start_offline_voice_command(self):
        if self._voice_app_busy():
            self.stats_label.setText(
                "Voice command unavailable while another task is running."
            )
            return

        model_path = self.default_vosk_model_path()
        self.voice_worker = VoiceCommandWorker(
            model_path=model_path,
            max_seconds=10.0,
            silence_seconds=0.9,
            min_speech_seconds=0.25,
        )
        self.voice_worker.status.connect(self.handle_voice_status)
        self.voice_worker.transcribed.connect(self.handle_voice_transcript)
        self.voice_worker.failed.connect(self.handle_voice_error)
        self.voice_worker.finished.connect(self.finish_voice_command)

        self._set_voice_button_recording(True)

        self.stats_label.setText("Starting offline voice command…")
        self.voice_worker.start()

    def _voice_app_busy(self) -> bool:
        for name in (
            "worker",
            "decision_worker",
            "web_worker",
            "python_worker",
            "astro_worker",
            "memory_worker",
            "knowledge_worker",
            "knowledge_maintenance_worker",
        ):
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def handle_voice_status(self, status_text):
        self.stats_label.setText(str(status_text or ""))

    def handle_voice_error(self, error_text):
        message = str(error_text or "Offline voice failed.").strip()
        log_warning("VoiceActions.handle_voice_error", message)
        self.stats_label.setText(message)

        QMessageBox.information(
            self,
            "Offline voice commands",
            (
                f"{message}\n\n"
                "Setup:\n"
                "1. Run: .\\scripts\\install_offline_voice.ps1 -PersistEnvironment\n"
                "2. Or manually install packages: pip install vosk sounddevice\n"
                "3. Put an extracted Vosk model folder here:\n"
                f"   {Path(APP_DIR) / 'voice_models'}\n\n"
                "You can also set FZASTRO_VOSK_MODEL to the extracted model path."
            ),
        )

    def handle_voice_transcript(self, transcript):
        transcript = str(transcript or "").strip()
        result = resolve_voice_command(transcript)

        if result.kind == "empty":
            self.stats_label.setText("No voice command recognized.")
            return

        try:
            if result.requires_confirmation and not self.confirm_voice_action(result):
                self.stats_label.setText(f'Voice action cancelled: "{transcript}"')
                return

            if result.kind == "command" and result.text:
                self._execute_voice_slash_command(result.text, transcript)
                return

            if result.kind == "skill" and result.action_id:
                self._execute_voice_skill_action(result.action_id, transcript)
                return

            if result.kind == "method" and result.method:
                self._execute_voice_method(result.method, transcript)
                return

            self.insert_prompt_into_composer(result.text or transcript)
            self.stats_label.setText(f'Voice inserted for review: "{transcript}"')
        except Exception as exc:
            log_exception("VoiceActions.handle_voice_transcript", exc)
            self.insert_prompt_into_composer(transcript)
            self.stats_label.setText(
                "Voice command was inserted for review after an execution error."
            )

    def confirm_voice_action(self, result) -> bool:
        transcript = str(getattr(result, "transcript", "") or "").strip()
        if getattr(result, "action_id", ""):
            action_spec = SKILL_ACTION_BY_ID.get(result.action_id)
            action_label = (
                action_spec.label if action_spec is not None else result.action_id
            )
        elif getattr(result, "method", "") == "voice_send_message":
            action_label = "Send current message"
        else:
            action_label = getattr(result, "text", "") or getattr(result, "method", "")

        response = QMessageBox.question(
            self,
            "Confirm voice action",
            (f'Voice heard: "{transcript}"\n\n' f"Run this action?\n{action_label}"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return response == QMessageBox.Yes

    def _execute_voice_slash_command(self, command_text, transcript):
        command_text = str(command_text or "").strip()
        if not command_text:
            return

        if self.is_astro_direct_request(command_text):
            executed = self.execute_astro_direct_request(command_text)
            if executed:
                self.input_box.clear()
                self.stats_label.setText(
                    f'Voice command: "{transcript}" → {command_text}'
                )
            return

        self.input_box.setPlainText(command_text)
        self.send_message()
        self.stats_label.setText(f'Voice command: "{transcript}" → {command_text}')

    def _execute_voice_skill_action(self, action_id, transcript):
        action_spec = SKILL_ACTION_BY_ID.get(str(action_id or ""))
        if action_spec is None:
            self.insert_prompt_into_composer(transcript)
            self.stats_label.setText(
                "Voice Skill unavailable; inserted transcript for review."
            )
            return

        self.run_skill_action(action_spec.action_id)
        self.stats_label.setText(f'Voice Skill: "{transcript}" → {action_spec.label}')

    def _execute_voice_method(self, method_name, transcript):
        method = getattr(self, str(method_name or ""), None)
        if not callable(method):
            self.insert_prompt_into_composer(transcript)
            self.stats_label.setText(
                "Voice action unavailable; inserted transcript for review."
            )
            return

        method()
        self.stats_label.setText(f'Voice action: "{transcript}"')

    def voice_send_message(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            self.stats_label.setText("Voice send cancelled: composer is empty.")
            self.input_box.setFocus()
            return
        self.send_message()

    def show_voice_commands_help_dialog(self):
        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle("Offline voice commands")
        dialog.resize(780, 640)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("What can I say?")
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #f4f7fb;")
        root.addWidget(title)

        subtitle = QLabel(
            "Click the microphone, say a short command, then pause. The app auto-processes after silence."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9aa6b5; font-size: 12px;")
        root.addWidget(subtitle)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for index, (category, phrases) in enumerate(voice_help_examples()):
            card = self._build_voice_help_card(category, phrases)
            row = index // 2
            col = index % 2
            grid.addWidget(card, row, col)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            "Risky actions such as sending, starting a new chat, or running Python ask for confirmation."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #7f8a99; font-size: 11px;")
        footer.addWidget(hint, 1)

        close_button = QPushButton("Close")
        close_button.setObjectName("primaryActionButton")
        close_button.clicked.connect(dialog.accept)
        footer.addWidget(close_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(footer)

        dialog.exec()

    def _build_voice_help_card(self, category: str, phrases: tuple[str, ...]) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        card.setStyleSheet(
            "QFrame { background: #141a21; border: 1px solid #29323d; "
            "border-radius: 13px; }"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(8)

        header = QLabel(str(category))
        header.setStyleSheet("color: #eef3f8; font-size: 13px; font-weight: 800;")
        layout.addWidget(header)

        for phrase in phrases:
            chip = QLabel(str(phrase))
            chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            chip.setStyleSheet(
                "QLabel { background: #0f141a; color: #dfe6ee; "
                "border: 1px solid #2b3540; border-radius: 8px; "
                "padding: 6px 8px; font-size: 12px; font-weight: 600; }"
            )
            layout.addWidget(chip)

        layout.addStretch(1)
        return card

    def finish_voice_command(self):
        self._set_voice_button_recording(False)

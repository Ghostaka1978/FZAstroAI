from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTextBrowser,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import API_KEY, BASE_URL, DEFAULT_MODEL_NAME
from ..dev_agent.subprocess_utils import hidden_subprocess_kwargs
from ..dev_agent.openclaude_settings import (
    clear_openclaude_api_key,
    clear_openclaude_git_api_token,
    load_openclaude_api_settings,
    openclaude_api_key_state,
    openclaude_git_token_state,
    save_openclaude_api_key,
    save_openclaude_git_api_token,
)
from ..dev_agent import DevAgentSession
from ..dev_agent.memory import (
    load_developer_agent_memory,
    save_developer_agent_last_project_root,
)
from ..dev_agent.agent_loop import DevAgentLoop
from ..dev_agent.llm_client import (
    DevAgentLLMError,
    RuntimeAgentClient,
    RuntimeAgentConfig,
)
from ..dev_agent.openclaude_bridge import (
    OpenClaudeBridgeError,
    OpenClaudeLaunchConfig,
    DEFAULT_CLAUDE_CODE_MAX_OUTPUT_TOKENS,
    DEFAULT_CLAUDE_CODE_USE_POWERSHELL_TOOL,
    audit_openclaude_project_root,
    openclaude_workspace_isolation_lines,
    build_openclaude_task_prompt,
    launch_openclaude_companion,
    openclaude_artifact_paths,
    safe_first_prompt,
    write_openclaude_project_context,
    write_openclaude_task_prompt,
    ensure_openclaude_agents_file,
)
from ..dev_agent.openclaude_embedded_terminal import (
    build_openclaude_embedded_command,
    command_to_cmdline,
    get_embedded_terminal_support,
)
from ..dev_agent.openclaude_attachments import (
    OpenClaudeAttachmentError,
    OpenClaudeImageAttachment,
    build_image_handoff_prompt,
    copy_image_attachment,
    make_clipboard_image_attachment_path,
    make_terminal_screenshot_attachment_path,
)
from .openclaude_terminal_widget import OpenClaudeTerminalWidget
from ..dev_agent.patch_applier import (
    PatchPathError,
    apply_patch_proposal,
    make_patch_proposal,
    preflight_patch_with_git,
    save_patch_exports,
)
from ..dev_agent.test_runner import (
    ValidationPreset,
    detect_validation_profile,
    run_validation_preset,
)
from ..dev_agent.types import AgentMode, PatchProposal, SafetyMode
from .window_utils import apply_window_defaults


def _project_root_from_package() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_runtime_owner(candidate: Any) -> bool:
    return candidate is not None and (
        callable(getattr(candidate, "current_model_name", None))
        or getattr(candidate, "model_box", None) is not None
    )


class _OpenClaudeTaskEdit(QPlainTextEdit):
    """Single OpenClaude composer. Enter sends; Shift+Enter inserts a newline."""

    submitted = Signal()

    def keyPressEvent(self, event):  # noqa: N802 - Qt override name
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not (modifiers & Qt.ShiftModifier):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _OpenClaudePtyWorker(QObject):
    """Run OpenClaude inside a Windows ConPTY session for the embedded OpenClaude tab."""

    started = Signal(str)
    output = Signal(str)
    failed = Signal(str)
    completed = Signal()

    def __init__(
        self,
        config: OpenClaudeLaunchConfig,
        task_prompt: str,
        *,
        auto_send_prompt: bool = True,
        initial_cols: int = 120,
        initial_rows: int = 30,
        openclaude_args: tuple[str, ...] | None = None,
        shell_only: bool = False,
    ):
        super().__init__()
        self.config = config
        self.task_prompt = task_prompt
        self.auto_send_prompt = auto_send_prompt
        self.initial_cols = max(40, int(initial_cols or 120))
        self.initial_rows = max(10, int(initial_rows or 30))
        self.openclaude_args = tuple(openclaude_args or ())
        self.shell_only = bool(shell_only)
        self._latest_cols = self.initial_cols
        self._latest_rows = self.initial_rows
        self._stop_requested = threading.Event()
        self._pty_lock = threading.Lock()
        self._pty = None

    def send_input(self, text: str) -> None:
        payload = str(text or "")
        if not payload:
            return
        self._write_pty(payload)

    def resize_terminal(self, cols: int, rows: int) -> None:
        cols = max(40, int(cols or self.initial_cols))
        rows = max(10, int(rows or self.initial_rows))
        self._latest_cols = cols
        self._latest_rows = rows
        with self._pty_lock:
            pty = self._pty
        if pty is None:
            return
        for method_name in ("setwinsize", "set_size", "resize"):
            method = getattr(pty, method_name, None)
            if callable(method):
                try:
                    method(int(cols), int(rows))
                    return
                except TypeError:
                    try:
                        method(int(rows), int(cols))
                        return
                    except Exception:
                        continue
                except Exception:
                    continue

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._close_pty()

    def _write_pty(self, payload: str) -> None:
        with self._pty_lock:
            pty = self._pty
        if pty is None:
            return
        try:
            pty.write(payload)
        except Exception as exc:
            self.output.emit(f"\n[embedded terminal write failed: {exc}]\n")

    def _close_pty(self) -> None:
        with self._pty_lock:
            pty = self._pty
        if pty is None:
            return
        for method_name in ("close", "kill", "terminate"):
            method = getattr(pty, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    continue

    def _spawn_pty(self, command_line: str, cwd: Path, env: dict[str, str]):
        import winpty  # type: ignore[import-not-found]

        try:
            pty = winpty.PTY(self._latest_cols, self._latest_rows)
        except TypeError:
            try:
                pty = winpty.PTY(cols=self._latest_cols, rows=self._latest_rows)
            except TypeError:
                pty = winpty.PTY()

        spawn = getattr(pty, "spawn", None)
        if not callable(spawn):
            raise RuntimeError("pywinpty PTY object does not expose spawn().")

        attempts = (
            lambda: spawn(command_line, cwd=str(cwd), env=env),
            lambda: spawn(command_line, cwd=str(cwd)),
            lambda: spawn(command_line),
        )
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                attempt()
                return pty
            except TypeError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("Could not spawn OpenClaude PTY session.")

    def _read_pty(self, pty) -> str:
        read = getattr(pty, "read", None)
        if not callable(read):
            raise RuntimeError("pywinpty PTY object does not expose read().")
        try:
            return str(read(4096) or "")
        except TypeError:
            return str(read() or "")

    def run(self) -> None:
        try:
            context = build_openclaude_embedded_command(
                self.config,
                openclaude_args=self.openclaude_args,
                shell_only=self.shell_only,
            )
            if not context.support.supported:
                self.failed.emit(
                    context.support.reason
                    + (
                        f"\n{context.support.install_hint}"
                        if context.support.install_hint
                        else ""
                    )
                )
                return

            pty = self._spawn_pty(
                command_to_cmdline(context.command),
                context.cwd,
                context.env,
            )
            with self._pty_lock:
                self._pty = pty
            self.resize_terminal(self._latest_cols, self._latest_rows)

            self.started.emit(
                f"Embedded OpenClaude started with {context.support.backend} in {context.cwd}"
            )

            started_at = time.monotonic()
            initial_sent = not (self.auto_send_prompt and self.task_prompt.strip())
            readiness_buffer = ""

            while not self._stop_requested.is_set():
                try:
                    chunk = self._read_pty(pty)
                except Exception as exc:
                    if not self._stop_requested.is_set():
                        message = str(exc)
                        if "EOF" in message.upper():
                            self.output.emit(
                                "\n[embedded terminal session ended: standard output closed. "
                                "If this happened immediately, check setup/build/deploy and the OpenClaude launcher output.]\n"
                            )
                        else:
                            self.failed.emit(
                                f"Embedded OpenClaude terminal stopped: {exc}"
                            )
                    return
                if chunk:
                    self.output.emit(chunk)
                    if not initial_sent:
                        readiness_buffer = (readiness_buffer + chunk)[-6000:]
                else:
                    time.sleep(0.03)

                if not initial_sent:
                    lowered = readiness_buffer.casefold()
                    ready = (
                        ("ready" in lowered and "/help" in lowered)
                        or "type /help" in lowered
                        or "openclaude v" in lowered
                    )
                    timed_out = time.monotonic() - started_at >= 8.0
                    if ready or timed_out:
                        if timed_out and not ready:
                            self.output.emit(
                                "\n[fzastro] OpenClaude readiness was not detected; sending queued task anyway.\n"
                            )
                        self._write_pty(self.task_prompt.rstrip() + "\r")
                        initial_sent = True
        except Exception as exc:
            if not self._stop_requested.is_set():
                self.failed.emit(str(exc))
        finally:
            self._close_pty()
            self.completed.emit()


class _DevAgentWorker(QObject):
    """Run the OpenClaude loop away from the Qt UI thread."""

    # Include the run id in worker-to-UI signals so the UI can connect these
    # signals directly to QObject methods. Avoid Python lambda wrappers here:
    # PySide may execute plain-callable signal receivers in the emitter thread,
    # which can crash Qt when those callables touch widgets.
    stream_delta = Signal(int, str)
    event = Signal(int, object)
    finished = Signal(int, object)
    failed = Signal(int, str, str)
    completed = Signal(int)

    def __init__(
        self,
        *,
        run_id: int,
        project_root: Path,
        request: str,
        config: RuntimeAgentConfig,
        mode: AgentMode,
        safety_mode: SafetyMode,
        max_steps: int = 8,
        conversation_messages: list[dict[str, str]] | None = None,
        steering: str | None = None,
    ):
        super().__init__()
        self.run_id = int(run_id)
        self.project_root = project_root
        self.request = request
        self.config = config
        self.mode = mode
        self.safety_mode = safety_mode
        self.max_steps = max_steps
        self.conversation_messages = conversation_messages
        self.steering = steering or ""
        self._queued_steering: list[str] = []
        self._steering_lock = threading.Lock()
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def stop_requested(self) -> bool:
        return bool(self._stop_requested)

    def add_steering_note(self, note: str) -> None:
        clean = str(note or "").strip()
        if not clean:
            return
        with self._steering_lock:
            self._queued_steering.append(clean)

    def pop_steering_notes(self) -> list[str]:
        with self._steering_lock:
            notes = list(self._queued_steering)
            self._queued_steering.clear()
        return notes

    def _emit_stream_delta(self, delta: str) -> None:
        self.stream_delta.emit(self.run_id, str(delta or ""))

    def _emit_event(self, event: object) -> None:
        self.event.emit(self.run_id, event)

    def run(self):
        try:
            client = RuntimeAgentClient(self.config)
            if not client.is_available():
                self.failed.emit(
                    self.run_id,
                    "Active model unavailable",
                    "The active FZAstro model endpoint is not reachable. OpenClaude did not auto-start Ollama.",
                )
                return

            loop = DevAgentLoop(
                self.project_root,
                client,
                mode=self.mode,
                safety_mode=self.safety_mode,
                max_steps=self.max_steps,
            )
            result = loop.run(
                self.request,
                stream_callback=self._emit_stream_delta,
                event_callback=self._emit_event,
                conversation_messages=self.conversation_messages,
                stop_requested=self.stop_requested,
                steering=self.steering,
                steering_note_callback=self.pop_steering_notes,
            )
            self.finished.emit(self.run_id, result)
        except DevAgentLLMError as exc:
            self.failed.emit(self.run_id, "Active model request failed", str(exc))
        except Exception as exc:
            self.failed.emit(self.run_id, "Agent loop failed", str(exc))
        finally:
            self.completed.emit(self.run_id)


class DevWorkbenchDialog(QWidget):
    """Step-based FZAstro AI OpenClaude workspace.

    The dialog is intentionally preview-first: it scans, prepares context, asks
    the active app model to inspect/plan/propose patches, applies only after
    visible approval, and records real validation output.
    """

    def __init__(self, parent=None, project_root: Path | str | None = None):
        super().__init__(parent, Qt.Window)
        self.app_window = self._find_runtime_owner(parent)
        self.setWindowTitle("FZAstro AI OpenClaude")
        self.resize(1360, 860)
        self.setMinimumSize(1040, 700)
        apply_window_defaults(self)

        self.project_root = self._initial_project_root(project_root)
        self.openclaude_api_settings = load_openclaude_api_settings()
        self.session = DevAgentSession(self.project_root)
        self.latest_prompt_package = ""
        self.latest_system_prompt = ""
        self.latest_plan = ""
        self.latest_task = None
        self.latest_proposal: PatchProposal | None = None
        self.latest_changed_paths: tuple[str, ...] = ()
        self.latest_checks: list[str] = []
        self._patch_previewed = False
        self._patch_applied = False
        self._workflow_stage = "start"
        self._agent_busy = False
        self._drawer_mode = ""
        self._drawer_width = 460
        self.agent_conversation_messages: list[dict[str, str]] = []
        self.agent_transcript_markdown = ""
        self.agent_steering_notes: list[str] = []
        self._agent_active_request = ""
        self._agent_is_followup = False
        self.agent_thread: QThread | None = None
        self.agent_worker: _DevAgentWorker | None = None
        self.openclaude_thread: QThread | None = None
        self.openclaude_worker: _OpenClaudePtyWorker | None = None
        self.openclaude_prompt_thread: QThread | None = None
        self.openclaude_prompt_worker: _OpenClaudePtyWorker | None = None
        self._openclaude_terminal_running = False
        self._openclaude_prompt_running = False
        self._openclaude_terminal_cols = 120
        self._openclaude_terminal_rows = 30
        self._openclaude_prompt_cols = 120
        self._openclaude_prompt_rows = 30
        self._openclaude_prompt_echo_lines: set[str] = set()
        self._openclaude_prompt_echo_notice_shown = False
        self._openclaude_spinner_notice_shown = False
        self._openclaude_launch_snapshot: dict[str, str] | None = None
        self._openclaude_last_resume_id = ""
        self._openclaude_last_resume_command = ""
        self._openclaude_terminal_output_buffer: list[str] = []
        self._openclaude_terminal_output_buffer_chars = 0
        self._openclaude_terminal_output_timer = QTimer(self)
        self._openclaude_terminal_output_timer.setSingleShot(True)
        self._openclaude_terminal_output_timer.timeout.connect(
            self._flush_openclaude_terminal_output
        )
        self._workspace_git_summary_cache: tuple[str, float, list[str]] | None = None
        self._agent_run_id = 0
        self._retired_agent_runs: list[tuple[int, QThread, _DevAgentWorker]] = []
        self._agent_stop_requested = False
        # OpenClaude runs should behave like local coding-agent sessions:
        # do not kill a long patch/review run just because a fixed wall-clock
        # timer elapsed. The user-controlled Stop Agent button remains the
        # cancellation boundary. Keep a generous provider read timeout as a
        # socket safety fuse, but do not run an app-level hard timeout by
        # default.
        self._agent_timeout_ms: int | None = None
        self._agent_http_timeout_seconds = 300.0
        self._agent_stream_markdown = ""
        self._agent_activity_phase = "idle"
        self._agent_activity_detail = ""
        self._agent_activity_context_count = 0
        self._agent_started_monotonic: float | None = None
        self._agent_last_activity_monotonic: float | None = None
        self._agent_activity_timer = QTimer(self)
        self._agent_activity_timer.timeout.connect(self._refresh_agent_activity_label)
        self._agent_render_timer = QTimer(self)
        self._agent_render_timer.setSingleShot(True)
        self._agent_render_timer.timeout.connect(self._flush_agent_stream_markdown)
        self._agent_timeout_timer = QTimer(self)
        self._agent_timeout_timer.setSingleShot(True)
        self._agent_timeout_timer.timeout.connect(self._handle_agent_timeout)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self.refresh_telemetry_from_app)

        self._build_ui()
        self._log(
            "OpenClaude ready. Select a workspace in Session, then type directly in Claude Terminal."
        )
        self._set_next_step(
            "Ready: set workspace defaults in Session, then type directly in Claude Terminal."
        )
        self._update_runtime_status()
        self._reset_progress_idle()
        self._set_workflow_stage("start")
        self.refresh_telemetry_from_app()
        self.telemetry_timer.start(1000)

    def _initial_project_root(self, explicit_root: Path | str | None = None) -> Path:
        if explicit_root is not None:
            return Path(explicit_root).expanduser().resolve()
        try:
            memory = load_developer_agent_memory()
            saved_root = str(memory.last_project_root or "").strip()
            if saved_root:
                candidate = Path(saved_root).expanduser().resolve()
                if candidate.exists() and candidate.is_dir():
                    return candidate
        except Exception:
            pass
        return _project_root_from_package().resolve()

    def _persist_project_root_if_valid(self) -> None:
        try:
            if self.project_root.exists() and self.project_root.is_dir():
                save_developer_agent_last_project_root(self.project_root)
        except Exception as exc:
            self._log(f"Could not save OpenClaude project root: {exc}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(6)

        title = QLabel("OpenClaude")
        title.setObjectName("settingsCardTitle")
        title.setVisible(False)

        subtitle = QLabel(
            "OpenClaude is hosted as a real terminal inside the selected workspace."
        )
        subtitle.setObjectName("settingsCardSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setVisible(False)

        config_box = QFrame()
        config_box.setObjectName("settingsCard")
        config_layout = QVBoxLayout(config_box)
        config_layout.setContentsMargins(12, 10, 12, 10)
        config_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Workspace:"))
        self.root_input = QLineEdit(str(self.project_root))
        self.root_input.setMinimumWidth(420)
        top_row.addWidget(self.root_input, 1)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_root)
        top_row.addWidget(browse_button)
        top_row.addStretch(1)
        config_layout.addLayout(top_row)

        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("Git API Token:"))
        self.openclaude_git_api_token_input = QLineEdit()
        self.openclaude_git_api_token_input.setEchoMode(QLineEdit.Password)
        self.openclaude_git_api_token_input.setPlaceholderText(
            "GitHub/Git API token for repository operations; saved under AppData, not the workspace"
        )
        self.openclaude_git_api_token_input.setMinimumWidth(420)
        if self.openclaude_api_settings.has_git_api_token:
            self.openclaude_git_api_token_input.setText(
                self.openclaude_api_settings.git_api_token
            )
        api_row.addWidget(self.openclaude_git_api_token_input, 1)
        self.openclaude_save_api_button = QPushButton("Save Git API Token")
        self.openclaude_save_api_button.clicked.connect(self.save_openclaude_api_key)
        api_row.addWidget(self.openclaude_save_api_button)
        self.openclaude_clear_api_button = QPushButton("Clear")
        self.openclaude_clear_api_button.clicked.connect(self.clear_openclaude_api_key)
        api_row.addWidget(self.openclaude_clear_api_button)
        api_row.addStretch(1)
        config_layout.addLayout(api_row)

        self.openclaude_api_status_label = QLabel("")
        self.openclaude_api_status_label.setObjectName("sidebarFooter")
        self.openclaude_api_status_label.setWordWrap(True)
        config_layout.addWidget(self.openclaude_api_status_label)

        self.session_summary_label = QLabel("")
        self.session_summary_label.setObjectName("settingsCardSubtitle")
        self.session_summary_label.setWordWrap(True)
        self.session_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        config_layout.addWidget(self.session_summary_label)

        # OpenClaude now owns edit/review behavior inside its terminal. These
        # hidden defaults are retained only for compatibility with older helper
        # methods and project-rule generation. They are not part of the visible UI.
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in AgentMode])
        self.mode_combo.setCurrentText(AgentMode.PATCH_RUN_TESTS.value)
        self.mode_combo.setVisible(False)
        self.safety_combo = QComboBox()
        self.safety_combo.addItems([mode.value for mode in SafetyMode])
        self.safety_combo.setCurrentText(SafetyMode.ASK_BEFORE_EDITING.value)
        self.safety_combo.setVisible(False)

        self.session_details_label = QLabel("")
        self.session_details_label.setObjectName("sidebarFooter")
        self.session_details_label.setWordWrap(True)
        self.session_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        config_layout.addWidget(self.session_details_label)

        # Runtime/model details are owned by the main FZAstro top bar. OpenClaude keeps
        # them out of the normal and advanced UI so diagnostics stay focused on
        # the selected project, tools, patch, and validation results.
        self.runtime_status_label = QLabel("")
        self.runtime_status_label.setVisible(False)
        self.runtime_status_label.setObjectName("sidebarFooter")
        self.runtime_status_label.setWordWrap(True)

        status_strip = QFrame()
        status_strip.setObjectName("settingsCard")
        status_strip_layout = QVBoxLayout(status_strip)
        status_strip_layout.setContentsMargins(10, 6, 10, 6)
        status_strip_layout.setSpacing(4)

        telemetry_row = QHBoxLayout()
        telemetry_row.setSpacing(10)
        telemetry_caption = QLabel("Telemetry:")
        telemetry_caption.setObjectName("settingsCardSubtitle")
        self.agent_status_label = QLabel("Agent idle")
        self.agent_status_label.setObjectName("settingsCardSubtitle")
        self.gpu_telemetry_label = QLabel("GPU --% • VRAM --/-- GB")
        self.gpu_telemetry_label.setObjectName("settingsCardSubtitle")
        self.system_telemetry_label = QLabel("CPU --% • RAM --/-- GB")
        self.system_telemetry_label.setObjectName("settingsCardSubtitle")
        telemetry_row.addWidget(telemetry_caption)
        telemetry_row.addWidget(self.agent_status_label, 1)
        telemetry_row.addWidget(self.gpu_telemetry_label, 1)
        telemetry_row.addWidget(self.system_telemetry_label, 1)
        telemetry_row.addStretch(1)
        status_strip_layout.addLayout(telemetry_row)

        state_row = QHBoxLayout()
        state_row.setSpacing(10)
        self.progress_label = QLabel("State: idle")
        self.progress_label.setObjectName("settingsCardSubtitle")
        self.progress_label.setVisible(False)
        self.openclaude_state_label = QLabel("● IDLE")
        self.openclaude_state_label.setObjectName("settingsCardSubtitle")
        self.openclaude_state_label.setAlignment(Qt.AlignCenter)
        self.openclaude_state_label.setMinimumWidth(96)
        self.openclaude_state_label.setVisible(False)
        self._set_openclaude_state_badge("idle")
        root_layout.addWidget(status_strip)

        self.mode_help_label = QLabel("")
        self.mode_help_label.setVisible(False)
        self.mode_help_label.setObjectName("sidebarFooter")
        self.mode_help_label.setWordWrap(True)
        config_layout.addWidget(self.mode_help_label)

        # Model settings are owned by the main FZAstro model controls. Hidden
        # fallbacks only support standalone dialog tests; normal app use should
        # resolve the live main-window runtime.
        self.model_input = QLineEdit(DEFAULT_MODEL_NAME)
        self.model_input.setVisible(False)
        self.base_url_input = QLineEdit(BASE_URL)
        self.base_url_input.setVisible(False)

        # The visible interaction is the embedded terminal itself. Keep a hidden
        # composer only so older helper methods/tests that inspect the attribute
        # do not break; it is no longer part of the OpenClaude UI.
        self.request_edit = _OpenClaudeTaskEdit()
        self.request_edit.setVisible(False)
        self.request_edit.setFixedHeight(0)
        self.request_edit.submitted.connect(self.submit_openclaude_from_composer)

        # Steering/guidance is now internal prompt context. The normal UI keeps a
        # single composer so users do not have to decide between task text and a
        # separate steering prompt. These hidden controls keep older queued-note
        # plumbing safe without exposing it as a second input.
        self.steering_input = QLineEdit()
        self.steering_input.setVisible(False)
        self.steer_button = QPushButton("Steer Next Step")
        self.steer_button.setVisible(False)
        self.steer_button.clicked.connect(self.add_agent_steering)

        # Keep the OpenClaude workspace compact: OpenClaude is now the only normal
        # OpenClaude execution path. Tests and patch utilities live behind one tools
        # dropdown so the embedded terminal has the screen space.
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.scan_project)
        self.plan_button = QPushButton("Plan")
        self.plan_button.clicked.connect(self.build_context_plan)
        self.local_agent_button = QPushButton("Ask")
        self.local_agent_button.clicked.connect(self.run_local_agent)
        self.stop_agent_button = QPushButton("Stop Agent")
        self.stop_agent_button.clicked.connect(self.stop_agent)
        self.stop_agent_button.setEnabled(False)
        self.preview_patch_button = QPushButton("Preview Diff")
        self.preview_patch_button.clicked.connect(self.preview_patch)
        self.apply_patch_button = QPushButton("Apply Diff")
        self.apply_patch_button.clicked.connect(self.apply_patch)
        self.compile_button = QPushButton("Compile")
        self.compile_button.clicked.connect(
            lambda: self.run_validation(ValidationPreset.COMPILE_ONLY)
        )
        self.final_report_button = QPushButton("Final Report")
        self.final_report_button.clicked.connect(self.build_final_report)

        self.fast_tests_button = QPushButton("Fast Tests")
        self.fast_tests_button.clicked.connect(
            lambda: self.run_validation(ValidationPreset.FAST_UNIT_TESTS)
        )
        self.feature_tests_button = QPushButton("Feature Tests")
        self.feature_tests_button.clicked.connect(
            lambda: self.run_validation(ValidationPreset.FEATURE_TESTS)
        )
        self.full_pytest_button = QPushButton("Full Pytest")
        self.full_pytest_button.clicked.connect(
            lambda: self.run_validation(ValidationPreset.FULL_PYTEST)
        )
        self.copy_prompt_button = QPushButton("Internal Prompt")
        self.copy_prompt_button.clicked.connect(self.copy_system_prompt)
        self.copy_prompt_button.setVisible(False)
        self.copy_context_button = QPushButton("Copy Context")
        self.copy_context_button.clicked.connect(self.copy_context_package)
        self.openclaude_status_button = QPushButton("Refresh Session")
        self.openclaude_status_button.clicked.connect(self.check_openclaude_companion)
        self.openclaude_status_button.setVisible(True)
        self.openclaude_launch_button = QPushButton("Start / Restart")
        self.openclaude_launch_button.setToolTip(
            "Start OpenClaude, or restart the current embedded terminal."
        )
        self.openclaude_launch_button.clicked.connect(
            self.restart_embedded_openclaude_terminal
        )
        self.openclaude_continue_button = QPushButton("Continue")
        self.openclaude_continue_button.setToolTip(
            "Run openclaude --continue immediately."
        )
        self.openclaude_continue_button.clicked.connect(self.run_openclaude_continue)
        self.openclaude_resume_button = QPushButton("Resume")
        self.openclaude_resume_button.setToolTip(
            "Run the last detected openclaude --resume <session-id> command."
        )
        self.openclaude_resume_button.clicked.connect(self.run_openclaude_resume_last)
        self.openclaude_shell_button = QPushButton("Prompt")
        self.openclaude_shell_button.setToolTip(
            "Open a normal project PowerShell prompt in a separate Prompt tab at the selected workspace."
        )
        self.openclaude_shell_button.clicked.connect(self.start_openclaude_shell_prompt)
        self.openclaude_prompt_start_button = QPushButton("Start Prompt")
        self.openclaude_prompt_start_button.setToolTip(
            "Start a normal PowerShell prompt at the selected workspace."
        )
        self.openclaude_prompt_start_button.clicked.connect(
            self.start_openclaude_shell_prompt
        )
        self.openclaude_prompt_stop_button = QPushButton("Stop Prompt")
        self.openclaude_prompt_stop_button.setToolTip(
            "Stop the separate Prompt tab shell."
        )
        self.openclaude_prompt_stop_button.clicked.connect(
            self.stop_openclaude_prompt_terminal
        )
        self.openclaude_prompt_clear_button = QPushButton("Clear")
        self.openclaude_prompt_clear_button.clicked.connect(
            self.clear_openclaude_prompt_output
        )
        self.openclaude_prompt_top_button = QPushButton("Top")
        self.openclaude_prompt_top_button.clicked.connect(
            lambda: self.openclaude_prompt_output.scroll_to_top()
        )
        self.openclaude_prompt_bottom_button = QPushButton("Bottom")
        self.openclaude_prompt_bottom_button.clicked.connect(
            lambda: self.openclaude_prompt_output.scroll_to_bottom()
        )
        self.openclaude_help_button = QPushButton("Help")
        self.openclaude_help_button.setToolTip(
            "Send /help to the active OpenClaude terminal."
        )
        self.openclaude_help_button.clicked.connect(self.send_openclaude_help_command)
        self.openclaude_ctx_button = QPushButton("Ctx")
        self.openclaude_ctx_button.setToolTip(
            "Send /ctx to the active OpenClaude terminal."
        )
        self.openclaude_ctx_button.clicked.connect(self.send_openclaude_ctx_command)
        self.openclaude_slash_clear_button = QPushButton("Clear")
        self.openclaude_slash_clear_button.setToolTip(
            "Send /clear to the active OpenClaude terminal."
        )
        self.openclaude_slash_clear_button.clicked.connect(
            self.send_openclaude_clear_command
        )
        self.openclaude_config_button = QPushButton("Config")
        self.openclaude_config_button.setToolTip(
            "Send /config to the active OpenClaude terminal."
        )
        self.openclaude_config_button.clicked.connect(
            self.send_openclaude_config_command
        )
        self.openclaude_buddy_button = QPushButton("Buddy")
        self.openclaude_buddy_button.setToolTip(
            "Send /buddy to the active OpenClaude terminal."
        )
        self.openclaude_buddy_button.clicked.connect(self.send_openclaude_buddy_command)

        self.session_start_button = QPushButton("Start Claude")
        self.session_start_button.clicked.connect(
            self.restart_embedded_openclaude_terminal
        )
        self.session_continue_button = QPushButton("Continue")
        self.session_continue_button.clicked.connect(self.run_openclaude_continue)
        self.session_resume_button = QPushButton("Resume")
        self.session_resume_button.clicked.connect(self.run_openclaude_resume_last)
        # Retained as hidden compatibility attributes only. The Session tab stays
        # focused on Claude start/recovery/stop; Prompt and slash commands live
        # in the terminal tabs where they act.
        self.session_prompt_button = QPushButton("Open Prompt")
        self.session_prompt_button.setVisible(False)
        self.session_prompt_button.clicked.connect(self.start_openclaude_shell_prompt)
        self.session_help_button = QPushButton("Help")
        self.session_help_button.setVisible(False)
        self.session_help_button.clicked.connect(self.send_openclaude_help_command)
        self.session_stop_button = QPushButton("Stop Claude")
        self.session_stop_button.clicked.connect(self.stop_embedded_openclaude_terminal)
        session_action_row = QHBoxLayout()
        session_action_row.setSpacing(6)
        session_action_row.addWidget(self.openclaude_status_button)
        session_action_row.addWidget(QLabel("OpenClaude:"))
        session_action_row.addWidget(self.session_start_button)
        session_action_row.addWidget(self.session_continue_button)
        session_action_row.addWidget(self.session_resume_button)
        session_action_row.addWidget(self.session_stop_button)
        session_action_row.addStretch(1)
        config_layout.addLayout(session_action_row)
        self.openclaude_send_task_button = QPushButton("Send")
        self.openclaude_send_task_button.setVisible(False)
        self.openclaude_send_task_button.clicked.connect(
            self.send_openclaude_task_to_terminal
        )
        self.openclaude_stop_button = QPushButton("Stop")
        self.openclaude_stop_button.clicked.connect(
            self.stop_embedded_openclaude_terminal
        )
        self.openclaude_clear_button = QPushButton("Clear")
        self.openclaude_clear_button.clicked.connect(
            self.clear_openclaude_terminal_output
        )
        self.openclaude_paste_button = QPushButton("Paste")
        self.openclaude_paste_button.clicked.connect(
            self.paste_clipboard_into_openclaude_terminal
        )
        self.openclaude_page_up_button = QPushButton("Page Up")
        self.openclaude_page_up_button.clicked.connect(
            lambda: self.openclaude_terminal_output.scroll_page_up()
        )
        self.openclaude_top_button = QPushButton("Top")
        self.openclaude_top_button.clicked.connect(
            lambda: self.openclaude_terminal_output.scroll_to_top()
        )
        self.openclaude_bottom_button = QPushButton("Bottom")
        self.openclaude_bottom_button.clicked.connect(
            lambda: self.openclaude_terminal_output.scroll_to_bottom()
        )
        self.openclaude_screenshot_button = QPushButton("Screenshot")
        self.openclaude_screenshot_button.clicked.connect(
            self.save_openclaude_terminal_screenshot
        )
        self.openclaude_paste_image_button = QPushButton("Paste Image")
        self.openclaude_paste_image_button.clicked.connect(
            self.paste_clipboard_image_to_openclaude
        )
        self.openclaude_attach_image_button = QPushButton("Attach Image")
        self.openclaude_attach_image_button.clicked.connect(
            self.attach_image_file_to_openclaude
        )
        self.openclaude_send_screenshot_button = QPushButton("Send Shot")
        self.openclaude_send_screenshot_button.clicked.connect(
            self.send_terminal_screenshot_to_openclaude
        )
        self.openclaude_external_button = QPushButton("Hidden Fallback")
        self.openclaude_external_button.clicked.connect(
            self.open_openclaude_external_terminal
        )
        self.openclaude_prompt_button = QPushButton("Copy Claude Task")
        self.openclaude_prompt_button.clicked.connect(self.copy_openclaude_safe_prompt)
        self.export_patch_button = QPushButton("Save Patch ZIP")
        self.export_patch_button.clicked.connect(self.export_patch)
        self.reset_chat_button = QPushButton("New Chat")
        self.reset_chat_button.clicked.connect(self.reset_agent_chat)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(8)
        for button in (self.openclaude_launch_button,):
            button.setCursor(Qt.PointingHandCursor)
        self.openclaude_external_button.setVisible(False)
        primary_row.addSpacing(10)

        self.dev_action_combo = QComboBox()
        self.dev_action_combo.setVisible(False)
        self.dev_action_combo.setMinimumWidth(180)
        self.dev_action_combo.addItem("Internal actions...", "")
        for label, action in (
            ("Preview Diff", "preview"),
            ("Apply Diff", "apply"),
            ("Compile", "compile"),
            ("Fast Tests", "fast_tests"),
            ("Feature Tests", "feature_tests"),
            ("Full Pytest", "full_pytest"),
            ("Final Report", "final_report"),
            ("Copy Claude Task", "copy_claude_task"),
            ("Save Patch ZIP", "export_patch"),
            ("New Chat", "new_chat"),
        ):
            self.dev_action_combo.addItem(label, action)
        self.dev_action_run_button = QPushButton("Run")
        self.dev_action_run_button.setVisible(False)
        self.dev_action_run_button.clicked.connect(self.run_selected_dev_action)
        # Session is setup/status only. Do not expose legacy patch/test action
        # dropdowns here; OpenClaude is the visible coding surface.

        for button in (
            self.stop_agent_button,
            self.preview_patch_button,
            self.apply_patch_button,
            self.compile_button,
            self.final_report_button,
            self.fast_tests_button,
            self.feature_tests_button,
            self.full_pytest_button,
            self.session_start_button,
            self.session_continue_button,
            self.session_resume_button,
            self.session_prompt_button,
            self.session_help_button,
            self.session_stop_button,
            self.openclaude_launch_button,
            self.openclaude_continue_button,
            self.openclaude_resume_button,
            self.openclaude_shell_button,
            self.openclaude_prompt_start_button,
            self.openclaude_prompt_stop_button,
            self.openclaude_prompt_clear_button,
            self.openclaude_prompt_top_button,
            self.openclaude_prompt_bottom_button,
            self.openclaude_help_button,
            self.openclaude_ctx_button,
            self.openclaude_slash_clear_button,
            self.openclaude_config_button,
            self.openclaude_buddy_button,
            self.openclaude_send_task_button,
            self.openclaude_stop_button,
            self.openclaude_clear_button,
            self.openclaude_paste_button,
            self.openclaude_page_up_button,
            self.openclaude_top_button,
            self.openclaude_bottom_button,
            self.openclaude_screenshot_button,
            self.openclaude_paste_image_button,
            self.openclaude_attach_image_button,
            self.openclaude_send_screenshot_button,
            self.openclaude_external_button,
            self.openclaude_prompt_button,
            self.export_patch_button,
            self.reset_chat_button,
            self.dev_action_run_button,
        ):
            button.setCursor(Qt.PointingHandCursor)

        self.workflow_buttons = (
            self.openclaude_launch_button,
            self.preview_patch_button,
            self.apply_patch_button,
            self.compile_button,
            self.final_report_button,
        )
        self.utility_buttons = (
            self.openclaude_continue_button,
            self.openclaude_resume_button,
            self.openclaude_shell_button,
            self.openclaude_prompt_start_button,
            self.openclaude_prompt_stop_button,
            self.openclaude_prompt_clear_button,
            self.openclaude_prompt_top_button,
            self.openclaude_prompt_bottom_button,
            self.openclaude_help_button,
            self.openclaude_ctx_button,
            self.openclaude_slash_clear_button,
            self.openclaude_config_button,
            self.openclaude_buddy_button,
            self.openclaude_send_task_button,
            self.openclaude_stop_button,
            self.openclaude_clear_button,
            self.openclaude_paste_button,
            self.openclaude_page_up_button,
            self.openclaude_top_button,
            self.openclaude_bottom_button,
            self.openclaude_screenshot_button,
            self.openclaude_paste_image_button,
            self.openclaude_attach_image_button,
            self.openclaude_send_screenshot_button,
            self.openclaude_prompt_button,
            self.export_patch_button,
            self.reset_chat_button,
            self.dev_action_run_button,
        )
        self._button_base_labels = {
            button: button.text()
            for button in (*self.workflow_buttons, *self.utility_buttons)
        }

        self.next_step_label = QLabel("")
        self.next_step_label.setObjectName("settingsCardSubtitle")
        self.next_step_label.setWordWrap(True)
        self.next_step_label.setVisible(False)

        # Do not keep the session controls as a permanent top card. They are
        # added to the workspace tabs below so the live terminal/timeline can
        # use the vertical space while configuration stays one click away.
        # The diagnostics can grow well beyond the visible tab height, so the
        # Session tab owns a real scroll area instead of clipping lower lines.
        self.session_config_content = config_box
        self.session_config_scroll = QScrollArea()
        self.session_config_scroll.setObjectName("openClaudeSessionScroll")
        self.session_config_scroll.setWidgetResizable(True)
        self.session_config_scroll.setFrameShape(QFrame.NoFrame)
        self.session_config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.session_config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.session_config_scroll.setWidget(config_box)
        self.session_config_panel = self.session_config_scroll

        workspace_box = QFrame()
        workspace_box.setObjectName("settingsCard")
        workspace_layout = QVBoxLayout(workspace_box)
        workspace_layout.setContentsMargins(8, 6, 8, 8)
        workspace_layout.setSpacing(4)
        root_layout.addWidget(workspace_box, 1)

        workspace_header = QHBoxLayout()
        workspace_title = QLabel("OpenClaude Workspace")
        workspace_title.setObjectName("settingsCardTitle")
        workspace_header.addWidget(workspace_title)
        workspace_header.addStretch(1)
        self.evidence_toggle_button = QPushButton("Internal Files")
        self.evidence_toggle_button.setVisible(False)
        self.advanced_toggle_button = QPushButton("Internal Details")
        self.advanced_toggle_button.setVisible(False)
        workspace_layout.addLayout(workspace_header)

        self.agent_activity_label = QLabel(
            "Activity: idle. OpenClaude terminal activity stays visible in the compact telemetry strip."
        )
        self.agent_activity_label.setObjectName("sidebarFooter")
        self.agent_activity_label.setWordWrap(True)
        self.agent_activity_label.setVisible(False)

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(8)
        workspace_layout.addWidget(self.workspace_splitter, 1)

        workspace_main_widget = QWidget()
        workspace_main = QVBoxLayout(workspace_main_widget)
        workspace_main.setContentsMargins(0, 0, 0, 0)
        workspace_main.setSpacing(8)
        self.workspace_splitter.addWidget(workspace_main_widget)

        self.workspace_tabs = QTabWidget()
        workspace_main.addWidget(self.workspace_tabs, 1)
        self.workspace_tabs.addTab(self.session_config_panel, "Session")

        self.plan_output = QTextBrowser()
        self.plan_output.setReadOnly(True)
        self.plan_output.setOpenExternalLinks(True)
        self.plan_output.setPlaceholderText(
            "Internal status output. The visible OpenClaude workflow uses the Claude Terminal tab."
        )
        self.plan_output.setVisible(False)

        self.openclaude_terminal_frame = QFrame()
        self.openclaude_terminal_frame.setObjectName("settingsCard")
        terminal_layout = QVBoxLayout(self.openclaude_terminal_frame)
        terminal_layout.setContentsMargins(4, 4, 4, 4)
        terminal_layout.setSpacing(4)
        terminal_header = QHBoxLayout()
        terminal_header.setSpacing(6)

        def _terminal_section_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sidebarFooter")
            label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            return label

        terminal_header.addWidget(_terminal_section_label("SESSION"))
        terminal_header.addWidget(self.openclaude_launch_button)
        terminal_header.addWidget(self.openclaude_continue_button)
        terminal_header.addWidget(self.openclaude_resume_button)
        terminal_header.addWidget(self.openclaude_shell_button)
        terminal_header.addWidget(self.openclaude_stop_button)
        terminal_header.addSpacing(12)
        terminal_header.addWidget(_terminal_section_label("CLAUDE"))
        terminal_header.addWidget(self.openclaude_help_button)
        terminal_header.addWidget(self.openclaude_ctx_button)
        terminal_header.addWidget(self.openclaude_slash_clear_button)
        terminal_header.addWidget(self.openclaude_config_button)
        terminal_header.addWidget(self.openclaude_buddy_button)
        terminal_header.addSpacing(12)
        terminal_header.addWidget(_terminal_section_label("INPUT"))
        terminal_header.addWidget(self.openclaude_paste_button)
        terminal_header.addWidget(self.openclaude_paste_image_button)
        terminal_header.addWidget(self.openclaude_attach_image_button)
        terminal_header.addWidget(self.openclaude_send_screenshot_button)
        terminal_header.addSpacing(12)
        terminal_header.addWidget(_terminal_section_label("VIEW"))
        terminal_header.addWidget(self.openclaude_page_up_button)
        terminal_header.addWidget(self.openclaude_top_button)
        terminal_header.addWidget(self.openclaude_bottom_button)
        terminal_header.addWidget(self.openclaude_screenshot_button)
        terminal_header.addWidget(self.openclaude_clear_button)
        terminal_header.addStretch(1)
        terminal_layout.addLayout(terminal_header)
        self.openclaude_terminal_output = OpenClaudeTerminalWidget()
        self.openclaude_terminal_output.setObjectName("embeddedClaudeTerminalHost")
        self.openclaude_terminal_output.setMinimumHeight(620)
        self.openclaude_terminal_output.input_received.connect(
            self._send_raw_openclaude_terminal_input
        )
        self.openclaude_terminal_output.resized.connect(
            self._resize_openclaude_terminal
        )
        self.openclaude_terminal_output.frontend_ready.connect(
            self._on_openclaude_terminal_frontend_ready
        )
        terminal_layout.addWidget(self.openclaude_terminal_output, 1)
        # The terminal is the only visible OpenClaude input. Keyboard data is
        # routed through xterm.js/ConPTY exactly like the standalone CLI.
        self.openclaude_stop_button.setEnabled(False)
        self.openclaude_send_task_button.setEnabled(False)
        self.openclaude_clear_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_continue_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_resume_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_shell_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_help_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_ctx_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_slash_clear_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_config_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_buddy_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_paste_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_page_up_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_top_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_bottom_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_screenshot_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_paste_image_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_attach_image_button.setCursor(Qt.PointingHandCursor)
        self.openclaude_send_screenshot_button.setCursor(Qt.PointingHandCursor)
        self.workspace_tabs.addTab(self.openclaude_terminal_frame, "Claude Terminal")

        self.openclaude_prompt_frame = QFrame()
        self.openclaude_prompt_frame.setObjectName("settingsCard")
        prompt_layout = QVBoxLayout(self.openclaude_prompt_frame)
        prompt_layout.setContentsMargins(4, 4, 4, 4)
        prompt_layout.setSpacing(4)
        prompt_header = QHBoxLayout()
        prompt_header.setSpacing(6)
        prompt_title = QLabel("Project PowerShell Prompt")
        prompt_title.setObjectName("sidebarFooter")
        prompt_header.addWidget(prompt_title)
        prompt_header.addWidget(self.openclaude_prompt_start_button)
        prompt_header.addWidget(self.openclaude_prompt_stop_button)
        prompt_header.addSpacing(12)
        prompt_header.addWidget(self.openclaude_prompt_top_button)
        prompt_header.addWidget(self.openclaude_prompt_bottom_button)
        prompt_header.addWidget(self.openclaude_prompt_clear_button)
        prompt_header.addStretch(1)
        prompt_layout.addLayout(prompt_header)
        self.openclaude_prompt_hint_label = QLabel(
            "Normal shell at the selected workspace. Use this for manual commands, openclaude --continue, or openclaude --resume without disturbing the Claude Terminal tab."
        )
        self.openclaude_prompt_hint_label.setObjectName("sidebarFooter")
        self.openclaude_prompt_hint_label.setWordWrap(True)
        prompt_layout.addWidget(self.openclaude_prompt_hint_label)
        self.openclaude_prompt_output = OpenClaudeTerminalWidget()
        self.openclaude_prompt_output.setObjectName("embeddedClaudePromptTerminalHost")
        self.openclaude_prompt_output.setMinimumHeight(560)
        self.openclaude_prompt_output.input_received.connect(
            self._send_raw_openclaude_prompt_input
        )
        self.openclaude_prompt_output.resized.connect(
            self._resize_openclaude_prompt_terminal
        )
        self.openclaude_prompt_output.frontend_ready.connect(
            self._on_openclaude_prompt_frontend_ready
        )
        prompt_layout.addWidget(self.openclaude_prompt_output, 1)
        self.workspace_tabs.addTab(self.openclaude_prompt_frame, "Prompt")

        self.workspace_tabs.setCurrentWidget(self.openclaude_terminal_frame)

        # No separate chat/composer surface: the OpenClaude terminal is the only
        # interaction surface, matching the external CLI. Keyboard input goes
        # directly through xterm.js/ConPTY into OpenClaude.
        self.request_edit.textChanged.connect(self._update_action_buttons)

        self.drawer_frame = QFrame()
        self.drawer_frame.setObjectName("settingsCard")
        self.drawer_frame.setMinimumWidth(320)
        self.drawer_frame.setMaximumWidth(820)
        drawer_layout = QVBoxLayout(self.drawer_frame)
        drawer_layout.setContentsMargins(10, 8, 10, 8)
        drawer_layout.setSpacing(6)
        drawer_header = QHBoxLayout()
        self.drawer_title_label = QLabel("Details")
        self.drawer_title_label.setObjectName("settingsCardSubtitle")
        drawer_header.addWidget(self.drawer_title_label, 1)
        self.drawer_close_button = QPushButton("Close")
        self.drawer_close_button.setCursor(Qt.PointingHandCursor)
        self.drawer_close_button.clicked.connect(self.close_workspace_drawer)
        drawer_header.addWidget(self.drawer_close_button)
        drawer_layout.addLayout(drawer_header)
        self.drawer_scroll = QScrollArea()
        self.drawer_scroll.setWidgetResizable(True)
        self.drawer_scroll.setFrameShape(QFrame.NoFrame)
        self.drawer_content = QWidget()
        self.drawer_content_layout = QVBoxLayout(self.drawer_content)
        self.drawer_content_layout.setContentsMargins(0, 0, 0, 0)
        self.drawer_content_layout.setSpacing(8)
        self.drawer_scroll.setWidget(self.drawer_content)
        drawer_layout.addWidget(self.drawer_scroll, 1)
        self.workspace_splitter.addWidget(self.drawer_frame)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)
        self.workspace_splitter.splitterMoved.connect(
            lambda *_: self._remember_workspace_drawer_width()
        )
        self.drawer_frame.setVisible(False)
        QTimer.singleShot(0, self._restore_workspace_splitter_sizes)

        self.evidence_panel = QFrame()
        self.evidence_panel.setObjectName("settingsCard")
        evidence_layout = QVBoxLayout(self.evidence_panel)
        evidence_layout.setContentsMargins(10, 8, 10, 8)
        evidence_layout.setSpacing(6)
        evidence_title = QLabel("Internal Files")
        evidence_title.setObjectName("settingsCardSubtitle")
        evidence_layout.addWidget(evidence_title)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(220)
        evidence_layout.addWidget(self.file_list)
        self.summary_label = QLabel("No scan yet.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("sidebarFooter")
        evidence_layout.addWidget(self.summary_label)
        self.evidence_panel.setVisible(False)
        self.drawer_content_layout.addWidget(self.evidence_panel)

        self.advanced_panel = QFrame()
        self.advanced_panel.setObjectName("settingsCard")
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(10, 8, 10, 8)
        advanced_layout.setSpacing(6)
        advanced_title = QLabel("Internal Details")
        advanced_title.setObjectName("settingsCardSubtitle")
        advanced_layout.addWidget(advanced_title)
        self.tabs = QTabWidget()
        self.action_log = QPlainTextEdit()
        self.action_log.setReadOnly(True)
        self.context_output = QPlainTextEdit()
        self.context_output.setReadOnly(True)
        self.patch_output = QPlainTextEdit()
        self.patch_output.setPlaceholderText(
            "Generated patch proposals appear here. You can also paste a unified diff, then click Preview Patch."
        )
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.final_output = QTextBrowser()
        self.final_output.setReadOnly(True)
        self.final_output.setOpenExternalLinks(True)
        self.tabs.addTab(self.action_log, "Tool Log")
        self.tabs.addTab(self.context_output, "Context")
        self.tabs.addTab(self.patch_output, "Patch Diff")
        self.tabs.addTab(self.test_output, "Validation")
        self.tabs.addTab(self.final_output, "Report")
        advanced_layout.addWidget(self.tabs)
        self.advanced_panel.setVisible(False)
        self.drawer_content_layout.addWidget(self.advanced_panel)
        self.drawer_content_layout.addStretch(1)

        self._update_mode_help()
        self._refresh_session_details()

    # ------------------------------------------------------------------
    # Runtime resolution and status
    # ------------------------------------------------------------------
    def _find_runtime_owner(self, start=None):
        if _is_runtime_owner(start):
            return start

        cursor = start
        visited = set()
        while cursor is not None and id(cursor) not in visited:
            visited.add(id(cursor))
            if _is_runtime_owner(cursor):
                return cursor
            try:
                cursor = cursor.parent()
            except Exception:
                break

        try:
            app = QApplication.instance()
            for widget in app.topLevelWidgets() if app is not None else []:
                if _is_runtime_owner(widget):
                    return widget
        except Exception:
            pass
        return None

    def _runtime_owner(self):
        owner = self.app_window if _is_runtime_owner(self.app_window) else None
        if owner is None:
            owner = self._find_runtime_owner(self.parent())
            self.app_window = owner
        return owner

    def _call_runtime(self, name: str, fallback=None):
        owner = self._runtime_owner()
        candidate = getattr(owner, name, None) if owner is not None else None
        if callable(candidate):
            try:
                value = candidate()
            except Exception:
                value = fallback
            return value if value is not None else fallback
        return fallback

    def _model_from_runtime_owner(self) -> str:
        owner = self._runtime_owner()
        value = self._call_runtime("current_model_name", None)
        clean_value = str(value or "").strip()
        if clean_value:
            return clean_value

        model_box = getattr(owner, "model_box", None) if owner is not None else None
        if model_box is not None:
            try:
                current_data = model_box.currentData(Qt.UserRole)
            except Exception:
                current_data = None
            clean_data = str(current_data or "").strip()
            if clean_data:
                return clean_data
            try:
                current_text = model_box.currentText()
            except Exception:
                current_text = ""
            clean_text = str(current_text or "").strip()
            if clean_text and "unavailable" not in clean_text.casefold():
                return clean_text

        return self.model_input.text().strip() or DEFAULT_MODEL_NAME

    def _reload_openclaude_api_settings(self):
        self.openclaude_api_settings = load_openclaude_api_settings()
        return self.openclaude_api_settings

    def _openclaude_typed_git_api_token(self) -> str:
        field = getattr(self, "openclaude_git_api_token_input", None)
        if field is None:
            return ""
        try:
            return str(field.text() or "").strip()
        except Exception:
            return ""

    def _active_openclaude_api_key(self, fallback_api_key: str = API_KEY) -> str:
        settings = self._reload_openclaude_api_settings()
        if settings.has_api_key:
            return settings.api_key
        return str(fallback_api_key or API_KEY)

    def _active_openclaude_git_api_token(self) -> str:
        typed = self._openclaude_typed_git_api_token()
        if typed:
            return typed
        settings = self._reload_openclaude_api_settings()
        if settings.has_git_api_token:
            return settings.git_api_token
        return ""

    def _update_openclaude_api_status(self) -> None:
        label = getattr(self, "openclaude_api_status_label", None)
        if label is None:
            return
        settings = self._reload_openclaude_api_settings()
        git_state = openclaude_git_token_state(settings)
        if settings.has_git_api_token:
            label.setText(
                "Git API token storage: saved locally under AppData / hidden. "
                "Used only as GITHUB_TOKEN/GH_TOKEN for repository operations; not written to the workspace, AGENTS.md, project context, launcher script, or git output."
            )
        else:
            label.setText(
                f"Git API token storage: not saved locally ({git_state}). "
                "OpenClaude can still use existing system git credentials if configured."
            )

    def save_openclaude_api_key(
        self, checked: bool = False, *, silent: bool = False
    ) -> bool:
        key = self._openclaude_typed_git_api_token()
        if not key:
            if not silent:
                QMessageBox.information(
                    self,
                    "OpenClaude Git API Token",
                    "Enter a GitHub/Git API token first, or use Clear to remove the saved token.",
                )
            self._update_openclaude_api_status()
            return False
        self.openclaude_api_settings = save_openclaude_git_api_token(key)
        self._update_openclaude_api_status()
        self._refresh_session_details()
        if not silent:
            self._log(
                "Saved OpenClaude Git API token in local AppData settings; value remains hidden."
            )
            self._set_next_step(
                "OpenClaude Git API token saved locally; restart terminal to use it."
            )
        return True

    def clear_openclaude_api_key(self, checked: bool = False):
        self.openclaude_api_settings = clear_openclaude_git_api_token()
        try:
            self.openclaude_git_api_token_input.clear()
        except Exception:
            pass
        self._update_openclaude_api_status()
        self._refresh_session_details()
        self._log(
            "Cleared the saved OpenClaude Git API token from local AppData settings."
        )
        self._set_next_step(
            "OpenClaude Git API token cleared; system git credentials can still be used."
        )

    def _main_app_runtime_config(self) -> RuntimeAgentConfig:
        fallback_api_key = str(self._call_runtime("current_api_key", API_KEY))
        return RuntimeAgentConfig(
            model=self._model_from_runtime_owner(),
            base_url=str(
                self._call_runtime(
                    "current_base_url", self.base_url_input.text().strip() or BASE_URL
                )
            ),
            api_key=self._active_openclaude_api_key(fallback_api_key),
            keep_alive=self._call_runtime("current_ollama_keep_alive_value", None),
            timeout_seconds=self._agent_http_timeout_seconds,
            num_ctx=8192,
            num_predict=3072,
        )

    def _runtime_summary(self) -> str:
        config = self._main_app_runtime_config()
        owner_state = (
            "main app" if _is_runtime_owner(self._runtime_owner()) else "fallback"
        )
        return f"Runtime source: {owner_state}"

    def _run_git_command(self, root: Path, *args: str) -> tuple[bool, str]:
        """Run a small read-only git command for Session diagnostics."""

        try:
            env = dict(os.environ)
            env["GIT_CEILING_DIRECTORIES"] = str(Path(root).resolve().parent)
            completed = subprocess.run(
                ["git", *args],
                cwd=str(root),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except FileNotFoundError:
            return False, "git executable not found"
        except Exception as exc:
            return False, str(exc)
        output = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode == 0, output

    def _redact_git_remote(self, remote: str) -> str:
        text = str(remote or "").strip()
        if not text:
            return "none"
        # Hide credentials if a remote was configured as https://token@host/...
        return re.sub(r"(https?://)([^/@]+)@", r"\1***@", text)

    def _same_filesystem_path(self, left: Path | str, right: Path | str) -> bool:
        try:
            return Path(left).resolve() == Path(right).resolve()
        except Exception:
            return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
                os.path.abspath(str(right))
            )

    def _workspace_git_summary_lines(self, root: Path) -> list[str]:
        cache_key = str(Path(root).expanduser())
        now = time.monotonic()
        cache = getattr(self, "_workspace_git_summary_cache", None)
        if cache is not None:
            cached_key, cached_at, cached_lines = cache
            if cached_key == cache_key and now - cached_at < 3.0:
                return list(cached_lines)

        try:
            audit = audit_openclaude_project_root(root)
        except OpenClaudeBridgeError as exc:
            lines = ["Workspace isolation: blocked", str(exc)]
            self._workspace_git_summary_cache = (cache_key, now, list(lines))
            return lines

        ok, top = self._run_git_command(audit.root, "rev-parse", "--show-toplevel")
        if not ok:
            lines = ["Git repo: not detected"]
            self._workspace_git_summary_cache = (cache_key, now, list(lines))
            return lines
        git_top = Path(top).expanduser()
        if not self._same_filesystem_path(git_top, audit.root):
            lines = [
                "Workspace isolation: blocked",
                f"Git resolved outside selected workspace: {git_top}",
                f"Selected workspace boundary: {audit.root}",
            ]
            self._workspace_git_summary_cache = (cache_key, now, list(lines))
            return lines

        ok_branch, branch = self._run_git_command(
            audit.root, "branch", "--show-current"
        )
        if not ok_branch or not branch:
            ok_branch, branch = self._run_git_command(
                audit.root, "rev-parse", "--short", "HEAD"
            )
        branch = branch or "unknown"

        ok_remote, remote = self._run_git_command(
            audit.root, "remote", "get-url", "origin"
        )
        remote = self._redact_git_remote(remote if ok_remote else "none")

        ok_status, status = self._run_git_command(audit.root, "status", "--short")
        if ok_status and status:
            changed = len([line for line in status.splitlines() if line.strip()])
            dirty = f"⚠ dirty · {changed} changed path(s)"
        elif ok_status:
            dirty = "✓ clean"
        else:
            dirty = "unknown"

        auth_bits = []
        settings = self._reload_openclaude_api_settings()
        if settings.has_git_api_token:
            auth_bits.append("AppData Git API token stored / hidden")
        if os.environ.get("GITHUB_TOKEN"):
            auth_bits.append("process GITHUB_TOKEN present")
        if os.environ.get("GH_TOKEN"):
            auth_bits.append("process GH_TOKEN present")
        if not auth_bits:
            auth_bits.append(
                "no FZAstro Git API token; system credentials are not inspected and prompts are disabled"
            )

        lines = list(openclaude_workspace_isolation_lines(audit.root))
        lines.extend(
            [
                f"Git root path: {git_top.resolve()} · verified inside selected workspace",
                "Git identity source: selected workspace .git/config only",
                "Git parent/sibling repos: not queried",
                f"Git branch: {branch}",
                f"Git remote from selected clone: {remote}",
                f"Git status: {dirty}",
                f"Git auth: {', '.join(auth_bits)}",
            ]
        )
        self._workspace_git_summary_cache = (cache_key, now, list(lines))
        return lines

    def _workspace_git_summary(self, root: Path) -> str:
        return " · ".join(self._workspace_git_summary_lines(root))

    def _refresh_session_details(self) -> None:
        if not hasattr(self, "session_details_label"):
            return
        try:
            root = Path(self.root_input.text().strip()).expanduser()
        except Exception:
            root = self.project_root
        runtime = self._main_app_runtime_config()
        agents_path = root / "AGENTS.md"
        terminal_frontend = getattr(
            getattr(self, "openclaude_terminal_output", None),
            "frontend_name",
            "not initialized",
        )
        exists = root.exists() and root.is_dir()
        settings = self._reload_openclaude_api_settings()
        api_state = openclaude_api_key_state(
            settings,
            fallback_api_key=str(self._call_runtime("current_api_key", API_KEY)),
        )
        git_state = openclaude_git_token_state(settings)
        details = [
            f"Workspace: {root} {'✓' if exists else 'not found'}",
            "Workspace warning: OpenClaude works directly in this folder. Use a test clone if you do not want the live checkout edited.",
            "",
            "OpenClaude environment:",
            "CLAUDE_CODE_USE_OPENAI=1",
            f"CLAUDE_CODE_USE_POWERSHELL_TOOL={DEFAULT_CLAUDE_CODE_USE_POWERSHELL_TOOL}",
            f"CLAUDE_CODE_MAX_OUTPUT_TOKENS={DEFAULT_CLAUDE_CODE_MAX_OUTPUT_TOKENS}",
            f"OPENAI_BASE_URL={runtime.base_url or BASE_URL}",
            f"OPENAI_MODEL={runtime.model or DEFAULT_MODEL_NAME}",
            api_state,
            "OPENAI_API_KEY purpose: model endpoint only",
            f"GITHUB_TOKEN={'stored locally for Git API / hidden' if settings.has_git_api_token else 'not set by FZAstro'}",
            f"GH_TOKEN={'mirrors stored Git API token / hidden' if settings.has_git_api_token else 'not set by FZAstro'}",
            f"FZASTRO_OPENCLAUDE_SETTINGS_FILE={settings.path}",
            f"FZASTRO_OPENCLAUDE_GIT_TOKEN_FILE={settings.path}",
            "Git API token file: AppData only / hidden / not scanned",
            f"FZASTRO_PROJECT_ROOT={root}",
            f"OPENCLAUDE_WORKSPACE_ROOT={root}",
            f"FZASTRO_WORKSPACE_BOUNDARY={root}",
            f"GIT_CEILING_DIRECTORIES={root.resolve().parent if exists else root.parent}",
            "GIT_TERMINAL_PROMPT=0",
            "GIT_CONFIG_NOSYSTEM=1",
            "GIT_CONFIG credential.helper=disabled for OpenClaude terminal",
            "Git credential safety: repository API token only; no interactive/system credential prompts",
            f"Claude Terminal state: {'running' if getattr(self, '_openclaude_terminal_running', False) else 'stopped'}",
            f"Prompt tab state: {'running' if getattr(self, '_openclaude_prompt_running', False) else 'stopped'}",
            "",
        ]
        snapshot = getattr(self, "_openclaude_launch_snapshot", None)
        if getattr(self, "_openclaude_terminal_running", False) and snapshot:
            details.extend(
                [
                    "Active OpenClaude terminal:",
                    f"Started: {snapshot.get('started_at', 'unknown')}",
                    f"Workspace at start: {snapshot.get('project_root', 'unknown')}",
                    f"Model at start: {snapshot.get('model', 'unknown')}",
                    f"Endpoint at start: {snapshot.get('base_url', 'unknown')}",
                    f"Git token at start: {snapshot.get('git_token_state', 'unknown')}",
                ]
            )
            current_git_state = "stored" if settings.has_git_api_token else "not stored"
            stale_reasons = []
            if str(snapshot.get("project_root", "")) != str(root):
                stale_reasons.append("workspace changed")
            if str(snapshot.get("model", "")) != str(
                runtime.model or DEFAULT_MODEL_NAME
            ):
                stale_reasons.append("model changed")
            if str(snapshot.get("base_url", "")) != str(runtime.base_url or BASE_URL):
                stale_reasons.append("endpoint changed")
            if str(snapshot.get("git_token_state", "")) != current_git_state:
                stale_reasons.append("Git token changed")
            if stale_reasons:
                details.append(
                    "Restart required: running OpenClaude was launched with older settings ("
                    + ", ".join(stale_reasons)
                    + ")."
                )
            else:
                details.append("Running settings: current")
            details.append("")

        if exists:
            details.extend(self._workspace_git_summary_lines(root))
        else:
            details.append("Git repo: unavailable until workspace exists")
        details.extend(
            [
                "",
                f"AGENTS.md: {'present' if agents_path.exists() else 'will be created when OpenClaude starts'}",
                f"Claude Terminal frontend: {terminal_frontend}",
                f"Prompt frontend: {getattr(getattr(self, 'openclaude_prompt_output', None), 'frontend_name', 'not initialized')}",
            ]
        )
        summary = (
            f"Workspace: {root} | "
            f"Claude: {'running' if getattr(self, '_openclaude_terminal_running', False) else 'stopped'} | "
            f"Prompt: {'running' if getattr(self, '_openclaude_prompt_running', False) else 'stopped'} | "
            f"Model: {runtime.model or DEFAULT_MODEL_NAME} | "
            f"PowerShell tool: {DEFAULT_CLAUDE_CODE_USE_POWERSHELL_TOOL} | "
            f"Max output: {DEFAULT_CLAUDE_CODE_MAX_OUTPUT_TOKENS}"
        )
        if hasattr(self, "session_summary_label"):
            self.session_summary_label.setText(summary)
        self.session_details_label.setText("\n".join(details))

    def _update_runtime_status(self):
        try:
            self.runtime_status_label.setText(self._runtime_summary())
        except Exception as exc:
            self.runtime_status_label.setText(f"Runtime unavailable ({exc})")
        self._update_openclaude_api_status()
        self._refresh_session_details()

    def _openclaude_launch_config(
        self, *, install_if_missing: bool = False
    ) -> OpenClaudeLaunchConfig:
        if self._openclaude_typed_git_api_token():
            self.save_openclaude_api_key(silent=True)
        runtime = self._main_app_runtime_config()
        return OpenClaudeLaunchConfig(
            project_root=Path(self.root_input.text().strip()).expanduser(),
            model=str(runtime.model or DEFAULT_MODEL_NAME),
            base_url=str(runtime.base_url or BASE_URL),
            api_key=str(runtime.api_key or API_KEY),
            git_api_token=self._active_openclaude_git_api_token(),
            install_if_missing=install_if_missing,
        )

    def check_openclaude_companion(self):
        self._workspace_git_summary_cache = None
        self._refresh_root()
        self._refresh_session_details()
        self.workspace_tabs.setCurrentWidget(self.session_config_panel)
        self._log(
            "Refreshed OpenClaude Session diagnostics. No terminal output or files changed."
        )

    def _openclaude_task_prompt(self) -> str:
        task = self.request_edit.toPlainText().strip()
        config = self._openclaude_launch_config(install_if_missing=False)
        mode = str(self.mode_combo.currentText() or "plan")
        safety = str(self.safety_combo.currentText() or "ask-before-editing")
        context_path = write_openclaude_project_context(
            config, mode=mode, safety=safety
        )
        artifacts = openclaude_artifact_paths()
        return build_openclaude_task_prompt(
            task,
            mode=mode,
            context_path=context_path,
            output_log_path=artifacts["output_log"],
            diff_path=artifacts["diff"],
            report_path=artifacts["report"],
        )

    def _normalize_openclaude_prompt_echo_line(self, line: str) -> str:
        """Normalize OpenClaude TUI echo lines so the generated prompt can be hidden."""

        normalized = str(line or "").strip()
        normalized = normalized.lstrip(">│┃| ").strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _prepare_openclaude_prompt_echo_filter(self, prompt: str) -> None:
        """Track generated prompt lines that OpenClaude echoes back into the PTY."""

        lines: set[str] = set()
        for raw_line in str(prompt or "").splitlines():
            normalized = self._normalize_openclaude_prompt_echo_line(raw_line)
            if len(normalized) >= 8:
                lines.add(normalized)
        self._openclaude_prompt_echo_lines = lines
        self._openclaude_prompt_echo_notice_shown = False

    def _filter_openclaude_prompt_echo(self, text: str) -> str:
        """Collapse FZAstro's injected task prompt echo into a single terminal marker."""

        if not self._openclaude_prompt_echo_lines:
            return text

        kept: list[str] = []
        suppressed_any = False
        for line in str(text or "").splitlines(keepends=True):
            body = line.rstrip("\n")
            normalized = self._normalize_openclaude_prompt_echo_line(body)
            suppress = normalized in self._openclaude_prompt_echo_lines
            if not suppress and len(normalized) >= 32:
                suppress = any(
                    normalized.startswith(prompt_line[:32])
                    for prompt_line in self._openclaude_prompt_echo_lines
                    if len(prompt_line) >= 32
                )
            if suppress:
                suppressed_any = True
                continue
            kept.append(line)

        if suppressed_any and not self._openclaude_prompt_echo_notice_shown:
            self._openclaude_prompt_echo_notice_shown = True
            kept.insert(0, "\n[fzastro] task sent; generated prompt echo hidden\n")
        return "".join(kept)

    def _strip_terminal_ansi(self, text: str) -> str:
        # QPlainTextEdit is not a terminal renderer. Keep the embedded session
        # readable by removing ANSI CSI sequences and OSC title updates such as
        # ESC ] 0;... BEL that OpenClaude emits for real terminals.
        cleaned = str(text or "")
        cleaned = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", cleaned)
        cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
        # Some PTY reads can split an ANSI sequence after ESC was removed by
        # an upstream terminal layer. Drop orphan SGR fragments as well.
        cleaned = re.sub(r"\[[0-9;:]*m", "", cleaned)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        return cleaned

    def _looks_like_openclaude_spinner_line(self, line: str) -> bool:
        """Detect transient OpenClaude TUI spinner frames such as Crafting..."""

        raw = str(line or "").strip()
        if not raw:
            return False
        letters = re.sub(r"[^A-Za-z]", "", raw).lower()
        # OpenClaude's terminal UI updates a spinner in-place. Once terminal
        # controls are stripped for QPlainTextEdit those frames can become
        # broken fragments such as "oCra", "Cfrtaifn", or "otgin...".
        if letters and len(letters) <= 24:
            if "crafting" in letters or "crafting".startswith(letters):
                return True
            if letters.startswith("o") and "crafting".startswith(letters[1:]):
                return True
            if set(letters).issubset(set("ocrafting")) and any(
                ch in letters for ch in "craft"
            ):
                return True
        compact = re.sub(r"\s+", "", raw)
        compact = re.sub(r"[─━═╔╗╚╝║│╠╣╭╮╰╯┌┐└┘┬┴┼]+", "", compact)
        if compact and len(compact) <= 18:
            if all(ch in "oO◦○●◎◉∙•·.:-_" for ch in compact):
                return True
            if all((not ch.isalpha()) or ch.lower() in "ocrafting" for ch in compact):
                return True
        return False

    def _filter_openclaude_spinner_noise(self, text: str) -> str:
        lines = str(text or "").splitlines(keepends=True)
        if not lines:
            return ""
        kept: list[str] = []
        suppressed = False
        for line in lines:
            body = line.rstrip("\n")
            if self._looks_like_openclaude_spinner_line(body):
                suppressed = True
                continue
            kept.append(line)
        if suppressed:
            self._set_agent_status("OpenClaude thinking")
            self._set_progress(None, "OpenClaude thinking")
            if not self._openclaude_spinner_notice_shown:
                self._openclaude_spinner_notice_shown = True
                kept.insert(0, "\n[openclaude] Thinking...\n")
        return "".join(kept)

    def _capture_openclaude_resume_command(self, text: str) -> None:
        """Remember the latest OpenClaude resume command printed by the CLI."""

        raw = str(text or "")
        if not raw:
            return
        matches = re.findall(
            r"openclaude\s+--resume\s+([A-Za-z0-9][A-Za-z0-9-]{7,})",
            raw,
            flags=re.IGNORECASE,
        )
        if not matches:
            return
        resume_id = matches[-1].strip()
        self._openclaude_last_resume_id = resume_id
        self._openclaude_last_resume_command = f"openclaude --resume {resume_id}"
        self._update_openclaude_composer_buttons()

    def _append_openclaude_terminal_output(self, text: str):
        self._capture_openclaude_resume_command(text)
        if not hasattr(self, "openclaude_terminal_output"):
            return
        payload = str(text or "")
        if not payload:
            return
        self._openclaude_terminal_output_buffer.append(payload)
        self._openclaude_terminal_output_buffer_chars += len(payload)
        if self._openclaude_terminal_output_buffer_chars >= 32768:
            self._flush_openclaude_terminal_output()
            return
        timer = getattr(self, "_openclaude_terminal_output_timer", None)
        if timer is not None and not timer.isActive():
            timer.start(24)

    def _flush_openclaude_terminal_output(self):
        if not hasattr(self, "openclaude_terminal_output"):
            return
        buffer = getattr(self, "_openclaude_terminal_output_buffer", [])
        if not buffer:
            return
        self._openclaude_terminal_output_buffer = []
        self._openclaude_terminal_output_buffer_chars = 0
        text = "".join(buffer)
        terminal = self.openclaude_terminal_output
        # xterm.js is a real terminal renderer, so feed it raw PTY bytes/text.
        # Buffering keeps the UI responsive during high-frequency TUI repaint bursts.
        # The text fallback still needs ANSI/spinner cleanup because it is only a transcript view.
        try:
            is_real_terminal = bool(terminal.is_real_terminal())
        except Exception:
            is_real_terminal = False
        if is_real_terminal:
            if text:
                terminal.append_output(text)
            return

        cleaned = self._strip_terminal_ansi(text)
        cleaned = self._filter_openclaude_prompt_echo(cleaned)
        cleaned = self._filter_openclaude_spinner_noise(cleaned)
        if not cleaned:
            return
        terminal.append_output(cleaned)

    def _append_openclaude_prompt_output(self, text: str):
        """Append output to the separate Prompt tab without touching Claude scrollback."""

        self._capture_openclaude_resume_command(text)
        if not hasattr(self, "openclaude_prompt_output"):
            return
        terminal = self.openclaude_prompt_output
        try:
            is_real_terminal = bool(terminal.is_real_terminal())
        except Exception:
            is_real_terminal = False
        if is_real_terminal:
            if text:
                terminal.append_output(str(text))
            return
        cleaned = self._strip_terminal_ansi(text)
        if cleaned:
            terminal.append_output(cleaned)

    def _send_raw_openclaude_terminal_input(self, data: str):
        worker = self.openclaude_worker
        if worker is not None and data:
            worker.send_input(data)

    def _send_raw_openclaude_prompt_input(self, data: str):
        worker = self.openclaude_prompt_worker
        if worker is not None and data:
            worker.send_input(data)

    def _resize_openclaude_terminal(self, cols: int, rows: int):
        self._openclaude_terminal_cols = max(40, int(cols or 120))
        self._openclaude_terminal_rows = max(10, int(rows or 30))
        worker = self.openclaude_worker
        if worker is not None:
            worker.resize_terminal(
                self._openclaude_terminal_cols, self._openclaude_terminal_rows
            )

    def _resize_openclaude_prompt_terminal(self, cols: int, rows: int):
        self._openclaude_prompt_cols = max(40, int(cols or 120))
        self._openclaude_prompt_rows = max(10, int(rows or 30))
        worker = self.openclaude_prompt_worker
        if worker is not None:
            worker.resize_terminal(
                self._openclaude_prompt_cols, self._openclaude_prompt_rows
            )

    def _on_openclaude_terminal_frontend_ready(self, frontend_name: str):
        self._log(f"OpenClaude terminal frontend ready: {frontend_name}")
        self._refresh_session_details()
        try:
            self.openclaude_terminal_output.fit()
            self.openclaude_terminal_output.focus_terminal()
        except Exception:
            pass
        if frontend_name != "xterm.js":
            self._set_agent_status(f"OpenClaude terminal frontend: {frontend_name}")

    def _on_openclaude_prompt_frontend_ready(self, frontend_name: str):
        self._log(f"OpenClaude prompt frontend ready: {frontend_name}")
        self._refresh_session_details()
        try:
            self.openclaude_prompt_output.fit()
        except Exception:
            pass

    def _set_openclaude_terminal_running(self, running: bool):
        self._openclaude_terminal_running = bool(running)
        self._update_action_buttons()
        self._update_openclaude_composer_buttons()
        self._refresh_session_details()

    def _set_openclaude_prompt_running(self, running: bool):
        self._openclaude_prompt_running = bool(running)
        self._update_openclaude_composer_buttons()
        self._refresh_session_details()

    def _update_openclaude_composer_buttons(self):
        if not hasattr(self, "openclaude_launch_button"):
            return
        running = bool(
            getattr(self, "_openclaude_terminal_running", False)
            and self.openclaude_worker is not None
        )
        prompt_running = bool(
            getattr(self, "_openclaude_prompt_running", False)
            and self.openclaude_prompt_worker is not None
        )
        has_resume = bool(getattr(self, "_openclaude_last_resume_command", ""))
        try:
            self.openclaude_launch_button.setEnabled(True)
            self.openclaude_continue_button.setEnabled(True)
            self.openclaude_resume_button.setEnabled(has_resume)
            self.openclaude_shell_button.setEnabled(True)
            self.openclaude_help_button.setEnabled(running)
            self.openclaude_ctx_button.setEnabled(running)
            self.openclaude_slash_clear_button.setEnabled(running)
            self.openclaude_config_button.setEnabled(running)
            self.openclaude_buddy_button.setEnabled(running)
            self.session_start_button.setEnabled(True)
            self.session_continue_button.setEnabled(True)
            self.session_resume_button.setEnabled(has_resume)
            self.session_prompt_button.setEnabled(True)
            self.session_help_button.setEnabled(running)
            self.session_stop_button.setEnabled(running)
            self.openclaude_prompt_start_button.setEnabled(True)
            self.openclaude_prompt_stop_button.setEnabled(prompt_running)
            self.openclaude_prompt_clear_button.setEnabled(True)
            self.openclaude_prompt_top_button.setEnabled(True)
            self.openclaude_prompt_bottom_button.setEnabled(True)
            state = "running" if running else ("prompt" if prompt_running else "idle")
            self._set_openclaude_state_badge(state)
            self.openclaude_send_task_button.setVisible(False)
            self.openclaude_send_task_button.setEnabled(False)
            self.openclaude_stop_button.setEnabled(running)
            self.openclaude_clear_button.setEnabled(True)
            self.openclaude_paste_button.setEnabled(running)
            self.openclaude_page_up_button.setEnabled(True)
            self.openclaude_top_button.setEnabled(True)
            self.openclaude_bottom_button.setEnabled(True)
            self.openclaude_screenshot_button.setEnabled(True)
            self.openclaude_paste_image_button.setEnabled(True)
            self.openclaude_attach_image_button.setEnabled(True)
            self.openclaude_send_screenshot_button.setEnabled(True)
        except Exception:
            pass

    def _send_openclaude_terminal_command(
        self,
        command: str,
        *,
        start_args: tuple[str, ...] = (),
        status: str = "OpenClaude command sent",
    ) -> None:
        """Run a recovery/action command without requiring the user to press Enter."""

        clean_command = str(command or "").strip()
        worker = self.openclaude_worker
        if worker is None:
            self.start_embedded_openclaude_terminal(openclaude_args=start_args)
            self._set_agent_status(status)
            return
        if not clean_command:
            return
        try:
            self.openclaude_terminal_output.scroll_to_bottom()
            self.openclaude_terminal_output.focus_terminal()
        except Exception:
            pass
        worker.send_input(clean_command.rstrip("\r\n") + "\r")
        self._set_agent_status(status)
        self._set_progress(None, status)
        self._log(f"Sent OpenClaude terminal command: {clean_command}")

    def run_openclaude_continue(self):
        """Recover the most recent OpenClaude session with one click."""

        self._send_openclaude_terminal_command(
            "openclaude --continue",
            start_args=("--continue",),
            status="OpenClaude continue requested",
        )

    def run_openclaude_resume_last(self):
        """Resume the latest session id printed by OpenClaude."""

        command = str(getattr(self, "_openclaude_last_resume_command", "") or "")
        if not command:
            self._append_openclaude_terminal_output(
                "\n[fzastro] No OpenClaude resume id has been detected yet. Use Continue, or paste a resume command manually.\n"
            )
            self._set_agent_status("No OpenClaude resume id detected")
            return
        resume_id = str(getattr(self, "_openclaude_last_resume_id", "") or "")
        self._send_openclaude_terminal_command(
            command,
            start_args=("--resume", resume_id) if resume_id else (),
            status="OpenClaude resume requested",
        )

    def start_openclaude_shell_prompt(self):
        """Open a normal project shell prompt in its own Prompt tab."""

        try:
            self.workspace_tabs.setCurrentWidget(self.openclaude_prompt_frame)
            self.openclaude_prompt_output.focus_terminal()
        except Exception:
            pass
        if self.openclaude_prompt_worker is not None:
            self._set_agent_status("Project prompt already running")
            return
        self.start_openclaude_prompt_terminal()
        self._set_agent_status("Project prompt starting")

    def _send_openclaude_slash_command(self, slash_command: str, label: str) -> None:
        """Send an OpenClaude slash command and auto-submit it with Enter."""

        command = str(slash_command or "").strip()
        if not command.startswith("/"):
            command = "/" + command
        if self.openclaude_worker is None:
            self._append_openclaude_terminal_output(
                f"\n[fzastro] Start OpenClaude first, then press {label} to send {command}.\n"
            )
            self._set_agent_status("OpenClaude not running")
            return
        self._send_openclaude_terminal_command(
            command, status=f"OpenClaude {label.lower()} requested"
        )

    def send_openclaude_help_command(self):
        """Show OpenClaude's native help without making the user press Enter."""

        self._send_openclaude_slash_command("/help", "Help")

    def send_openclaude_ctx_command(self):
        """Show OpenClaude context state without making the user press Enter."""

        self._send_openclaude_slash_command("/ctx", "Ctx")

    def send_openclaude_clear_command(self):
        """Clear OpenClaude's active conversation/context via its native command."""

        self._send_openclaude_slash_command("/clear", "Clear")

    def send_openclaude_config_command(self):
        """Open OpenClaude configuration without making the user press Enter."""

        self._send_openclaude_slash_command("/config", "Config")

    def send_openclaude_buddy_command(self):
        """Open OpenClaude buddy mode without making the user press Enter."""

        self._send_openclaude_slash_command("/buddy", "Buddy")

    def clear_openclaude_terminal_output(self):
        if hasattr(self, "openclaude_terminal_output"):
            self.openclaude_terminal_output.clear()

    def clear_openclaude_prompt_output(self):
        if hasattr(self, "openclaude_prompt_output"):
            self.openclaude_prompt_output.clear()

    def paste_clipboard_into_openclaude_terminal(self):
        text = QGuiApplication.clipboard().text()
        if not text:
            self._set_agent_status("Clipboard is empty")
            return
        if self.openclaude_worker is None:
            self._append_openclaude_terminal_output(
                "\n[fzastro] OpenClaude is not running. Press Start / Restart before pasting into the terminal.\n"
            )
            self._set_agent_status("OpenClaude terminal not running")
            return
        self.openclaude_terminal_output.paste_text(text)
        self._set_agent_status("Pasted clipboard into OpenClaude terminal")
        self._log("Pasted clipboard text into OpenClaude terminal.")

    def save_openclaude_terminal_screenshot(self):
        if not hasattr(self, "openclaude_terminal_output"):
            return
        default_name = time.strftime("fzastro_openclaude_terminal_%Y%m%d_%H%M%S.png")
        default_path = Path.home() / "Pictures" / default_name
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save OpenClaude Terminal Screenshot",
            str(default_path),
            "PNG Images (*.png)",
        )
        if not selected:
            return
        target = Path(selected)
        if target.suffix.casefold() != ".png":
            target = target.with_suffix(".png")
        try:
            ok = self.openclaude_terminal_output.save_screenshot(target)
        except Exception as exc:
            QMessageBox.warning(
                self, "OpenClaude Screenshot", f"Could not save screenshot: {exc}"
            )
            return
        if not ok:
            QMessageBox.warning(
                self,
                "OpenClaude Screenshot",
                "Could not capture the terminal screenshot.",
            )
            return
        QGuiApplication.clipboard().setText(str(target))
        self._set_agent_status("OpenClaude screenshot saved")
        self._log(f"Saved OpenClaude terminal screenshot: {target}")
        self._append_openclaude_terminal_output(
            f"\n[fzastro] Terminal screenshot saved: {target}\n"
        )

    def _openclaude_attachment_user_note(self) -> str:
        """Return optional text the user typed before attaching an image."""

        try:
            return self.request_edit.toPlainText().strip()
        except Exception:
            return ""

    def _handoff_openclaude_image_attachment(
        self,
        attachment: OpenClaudeImageAttachment,
        *,
        user_note: str = "",
        source_label: str = "image",
    ) -> None:
        """Send or stage an image attachment prompt for the OpenClaude terminal."""

        prompt = build_image_handoff_prompt(attachment, user_note=user_note)
        QGuiApplication.clipboard().setText(prompt)
        rel_path = attachment.relative_path
        worker = self.openclaude_worker
        if worker is None:
            self._append_openclaude_terminal_output(
                "\n[fzastro] Image attachment prepared but OpenClaude is not running. "
                f"Start OpenClaude, then paste the clipboard prompt. Image: {rel_path}\n"
            )
            self._set_agent_status("Image prompt copied; OpenClaude not running")
            self._log(f"Prepared OpenClaude image attachment prompt: {attachment.path}")
            return

        self._append_openclaude_terminal_output(
            f"\nfzastro$ {source_label} attachment sent: {rel_path}\n"
        )
        worker.send_input(prompt.rstrip("\r\n") + "\r")
        self._set_agent_status("Image attachment sent to OpenClaude")
        self._set_progress(None, "image attachment sent")
        self._log(f"Sent OpenClaude image attachment: {attachment.path}")
        try:
            self.request_edit.clear()
        except Exception:
            pass
        self._update_openclaude_composer_buttons()

    def paste_clipboard_image_to_openclaude(self):
        """Save a clipboard screenshot/image and hand its path to OpenClaude."""

        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None or not mime.hasImage():
            self._set_agent_status("Clipboard does not contain an image")
            self._append_openclaude_terminal_output(
                "\n[fzastro] Clipboard does not contain an image. Use Paste for text, or Attach Image for an image file.\n"
            )
            return
        try:
            target = make_clipboard_image_attachment_path(
                Path(self.root_input.text().strip()).expanduser()
            )
            image = clipboard.image()
            if image.isNull() or not image.save(str(target), "PNG"):
                raise OpenClaudeAttachmentError("Clipboard image could not be saved.")
            root = Path(self.root_input.text().strip()).expanduser().resolve()
            attachment = OpenClaudeImageAttachment(
                path=target,
                project_root=root,
                source_label="clipboard-image",
            )
            self._handoff_openclaude_image_attachment(
                attachment,
                user_note=self._openclaude_attachment_user_note(),
                source_label="clipboard image",
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "OpenClaude Image", f"Could not attach clipboard image: {exc}"
            )
            self._set_agent_status("Clipboard image attach failed")

    def attach_image_file_to_openclaude(self):
        """Choose an image file, copy it into the workspace, and hand it off."""

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Attach Image to OpenClaude",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not selected:
            return
        try:
            attachment = copy_image_attachment(
                selected,
                Path(self.root_input.text().strip()).expanduser(),
                prefix="image",
            )
            self._handoff_openclaude_image_attachment(
                attachment,
                user_note=self._openclaude_attachment_user_note(),
                source_label="image",
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "OpenClaude Image", f"Could not attach image: {exc}"
            )
            self._set_agent_status("Image attach failed")

    def send_terminal_screenshot_to_openclaude(self):
        """Capture the visible terminal and send that screenshot path to OpenClaude."""

        if not hasattr(self, "openclaude_terminal_output"):
            return
        try:
            target = make_terminal_screenshot_attachment_path(
                Path(self.root_input.text().strip()).expanduser()
            )
            ok = self.openclaude_terminal_output.save_screenshot(target)
            if not ok:
                raise OpenClaudeAttachmentError(
                    "Could not capture the terminal screenshot."
                )
            root = Path(self.root_input.text().strip()).expanduser().resolve()
            attachment = OpenClaudeImageAttachment(
                path=target,
                project_root=root,
                source_label="terminal-screenshot",
            )
            self._handoff_openclaude_image_attachment(
                attachment,
                user_note=self._openclaude_attachment_user_note(),
                source_label="terminal screenshot",
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "OpenClaude Screenshot", f"Could not send screenshot: {exc}"
            )
            self._set_agent_status("Terminal screenshot handoff failed")

    def run_selected_dev_action(self):
        action = str(self.dev_action_combo.currentData() or "")
        if not action:
            self._append_workspace_card(
                "# More Actions\n\nChoose a tool action from the dropdown, then click **Run**."
            )
            return
        handlers = {
            "preview": self.preview_patch,
            "apply": self.apply_patch,
            "compile": lambda: self.run_validation(ValidationPreset.COMPILE_ONLY),
            "fast_tests": lambda: self.run_validation(ValidationPreset.FAST_UNIT_TESTS),
            "feature_tests": lambda: self.run_validation(
                ValidationPreset.FEATURE_TESTS
            ),
            "full_pytest": lambda: self.run_validation(ValidationPreset.FULL_PYTEST),
            "final_report": self.build_final_report,
            "copy_claude_task": self.copy_openclaude_safe_prompt,
            "export_patch": self.export_patch,
            "new_chat": self.reset_agent_chat,
        }
        handler = handlers.get(action)
        if handler is not None:
            handler()
        self.dev_action_combo.setCurrentIndex(0)

    def copy_openclaude_safe_prompt(self):
        prompt = self._openclaude_task_prompt()
        prompt_path = write_openclaude_task_prompt(prompt)
        QGuiApplication.clipboard().setText(prompt)
        self._append_workspace_card(
            "# OpenClaude Task Copied\n\n"
            f"**Prompt file:** `{prompt_path}`\n\n"
            "The compatibility prompt is on the clipboard. Normal OpenClaude use is terminal-first; type directly into the embedded terminal."
        )
        self._log("Copied structured OpenClaude task prompt to clipboard.")

    def _record_openclaude_launch_snapshot(
        self, config: OpenClaudeLaunchConfig
    ) -> None:
        git_token_state = (
            "stored" if str(config.git_api_token or "").strip() else "not stored"
        )
        self._openclaude_launch_snapshot = {
            "started_at": time.strftime("%H:%M:%S"),
            "project_root": str(Path(config.project_root).expanduser()),
            "model": str(config.model or DEFAULT_MODEL_NAME),
            "base_url": str(config.base_url or BASE_URL),
            "git_token_state": git_token_state,
        }

    def restart_embedded_openclaude_terminal(self):
        """Start OpenClaude as a direct embedded terminal session.

        The terminal is the interaction surface. FZAstro does not auto-send a
        hidden prompt and does not maintain a second chat composer.
        """

        if self.openclaude_worker is not None:
            self.stop_embedded_openclaude_terminal()
            QTimer.singleShot(600, self.start_embedded_openclaude_terminal)
            return
        self.start_embedded_openclaude_terminal()

    def submit_openclaude_from_composer(self):
        """Compatibility entry point; visible interaction is the terminal."""

        if self.openclaude_worker is None:
            self.start_embedded_openclaude_terminal()
        else:
            self.send_openclaude_task_to_terminal()

    def _mark_openclaude_submission_started(self):
        self._openclaude_spinner_notice_shown = False
        self._set_agent_status("OpenClaude task sent")
        self._set_progress(None, "OpenClaude task sent")

    def _clear_openclaude_composer_after_submit(self):
        try:
            self.request_edit.blockSignals(True)
            self.request_edit.clear()
        finally:
            try:
                self.request_edit.blockSignals(False)
            except Exception:
                pass
        self._update_openclaude_composer_buttons()

    def start_embedded_openclaude_terminal(
        self,
        *,
        openclaude_args: tuple[str, ...] | None = None,
        shell_only: bool = False,
    ):
        self._refresh_root()
        if self.openclaude_thread is not None or self.openclaude_worker is not None:
            self._append_openclaude_terminal_output(
                "\n[fzastro] Embedded terminal is already running. Type directly in the terminal, or press Restart.\n"
            )
            return

        config = self._openclaude_launch_config(install_if_missing=False)
        self._record_openclaude_launch_snapshot(config)
        try:
            ensure_openclaude_agents_file(
                config,
                mode="openclaude-terminal",
                safety="openclaude-native",
            )
        except Exception as exc:
            self._append_openclaude_terminal_output(
                f"[fzastro] could not create AGENTS.md: {exc}\n"
            )

        try:
            self.workspace_tabs.setCurrentWidget(self.openclaude_terminal_frame)
        except Exception:
            pass
        if not shell_only:
            self.openclaude_terminal_output.clear()
        try:
            self.openclaude_terminal_output.fit()
            self.openclaude_terminal_output.focus_terminal()
        except Exception:
            pass

        support = get_embedded_terminal_support()
        if not support.supported:
            self._append_openclaude_terminal_output(
                "Embedded terminal backend is not ready.\n"
                f"Reason: {support.reason}\n"
                f"Hint: {support.install_hint or 'Prepare pywinpty through setup/build/deploy.'}\n\n"
            )
            self._append_workspace_card(
                "# Embedded OpenClaude Not Available\n\n"
                f"{support.reason}\n\n"
                f"{support.install_hint or 'Prepare pywinpty through setup/build/deploy.'}\n\n"
                "FZAstro did not fake terminal automation or use SendKeys."
            )
            self._log(
                "Embedded OpenClaude terminal unavailable; fix setup/build/deploy backend."
            )
            return

        self.openclaude_thread = QThread(self)
        args = tuple(str(part) for part in (openclaude_args or ()) if str(part).strip())
        self.openclaude_worker = _OpenClaudePtyWorker(
            config,
            "",
            auto_send_prompt=False,
            initial_cols=getattr(self, "_openclaude_terminal_cols", 120),
            initial_rows=getattr(self, "_openclaude_terminal_rows", 30),
            openclaude_args=args,
            shell_only=shell_only,
        )
        self.openclaude_worker.moveToThread(self.openclaude_thread)
        self.openclaude_thread.started.connect(self.openclaude_worker.run)
        self.openclaude_worker.started.connect(self._on_openclaude_terminal_started)
        self.openclaude_worker.output.connect(self._append_openclaude_terminal_output)
        self.openclaude_worker.failed.connect(self._on_openclaude_terminal_failed)
        self.openclaude_worker.completed.connect(self._on_openclaude_terminal_completed)
        self.openclaude_worker.completed.connect(self.openclaude_thread.quit)
        self.openclaude_worker.completed.connect(self.openclaude_worker.deleteLater)
        self.openclaude_thread.finished.connect(self.openclaude_thread.deleteLater)
        self.openclaude_thread.finished.connect(self._clear_openclaude_terminal_thread)
        self._set_openclaude_terminal_running(True)
        launch_label = "project prompt" if shell_only else "OpenClaude terminal"
        if args:
            launch_label += " (" + " ".join(args) + ")"
        self._set_agent_status(f"{launch_label} starting")
        self._set_progress(None, f"starting {launch_label}")
        self.openclaude_thread.start()
        self._log(f"Started embedded {launch_label}.")

    def start_openclaude_prompt_terminal(self):
        """Start a separate normal project shell in the Prompt tab."""

        self._refresh_root()
        if (
            self.openclaude_prompt_thread is not None
            or self.openclaude_prompt_worker is not None
        ):
            try:
                self.workspace_tabs.setCurrentWidget(self.openclaude_prompt_frame)
                self.openclaude_prompt_output.focus_terminal()
            except Exception:
                pass
            self._append_openclaude_prompt_output(
                "\n[fzastro] Project prompt is already running in this tab.\n"
            )
            return

        config = self._openclaude_launch_config(install_if_missing=False)
        try:
            self.workspace_tabs.setCurrentWidget(self.openclaude_prompt_frame)
            self.openclaude_prompt_output.fit()
            self.openclaude_prompt_output.focus_terminal()
        except Exception:
            pass

        support = get_embedded_terminal_support()
        if not support.supported:
            self._append_openclaude_prompt_output(
                "Embedded terminal backend is not ready.\n"
                f"Reason: {support.reason}\n"
                f"Hint: {support.install_hint or 'Prepare pywinpty through setup/build/deploy.'}\n\n"
            )
            self._log("Prompt tab unavailable; embedded terminal backend is not ready.")
            return

        self.openclaude_prompt_thread = QThread(self)
        self.openclaude_prompt_worker = _OpenClaudePtyWorker(
            config,
            "",
            auto_send_prompt=False,
            initial_cols=getattr(self, "_openclaude_prompt_cols", 120),
            initial_rows=getattr(self, "_openclaude_prompt_rows", 30),
            openclaude_args=(),
            shell_only=True,
        )
        self.openclaude_prompt_worker.moveToThread(self.openclaude_prompt_thread)
        self.openclaude_prompt_thread.started.connect(self.openclaude_prompt_worker.run)
        self.openclaude_prompt_worker.started.connect(
            self._on_openclaude_prompt_started
        )
        self.openclaude_prompt_worker.output.connect(
            self._append_openclaude_prompt_output
        )
        self.openclaude_prompt_worker.failed.connect(self._on_openclaude_prompt_failed)
        self.openclaude_prompt_worker.completed.connect(
            self._on_openclaude_prompt_completed
        )
        self.openclaude_prompt_worker.completed.connect(
            self.openclaude_prompt_thread.quit
        )
        self.openclaude_prompt_worker.completed.connect(
            self.openclaude_prompt_worker.deleteLater
        )
        self.openclaude_prompt_thread.finished.connect(
            self.openclaude_prompt_thread.deleteLater
        )
        self.openclaude_prompt_thread.finished.connect(
            self._clear_openclaude_prompt_thread
        )
        self._set_openclaude_prompt_running(True)
        self._set_agent_status("Project prompt starting")
        self._set_progress(None, "starting project prompt")
        self.openclaude_prompt_thread.start()
        self._log("Started separate OpenClaude project prompt tab.")

    def _on_openclaude_terminal_started(self, message: str):
        # Keep the terminal content pure. OpenClaude owns the terminal screen;
        # FZAstro setup/status details live in Session and the compact telemetry/state strip.
        self._log(str(message or "OpenClaude started"))
        self._set_agent_status("OpenClaude terminal running")
        self._set_progress(None, "running")
        try:
            self.openclaude_terminal_output.fit()
            self.openclaude_terminal_output.focus_terminal()
        except Exception:
            pass

    def _on_openclaude_terminal_failed(self, message: str):
        self._append_openclaude_terminal_output(f"\n[OpenClaude error] {message}\n")
        self._append_workspace_card(
            "# Embedded OpenClaude Error\n\n"
            f"{message}\n\n"
            "Check setup/build/deploy if the embedded ConPTY backend is unstable on this machine."
        )
        self._openclaude_launch_snapshot = None
        self._set_openclaude_terminal_running(False)
        self._set_agent_status("OpenClaude error")
        self._set_progress(None, "error")
        self._log(f"Embedded OpenClaude terminal error: {message}")

    def _on_openclaude_terminal_completed(self):
        self._append_openclaude_terminal_output(
            "\n[fzastro] Embedded terminal closed. Press Start, Continue, Resume, or Prompt to recover.\n"
        )
        self._openclaude_launch_snapshot = None
        self._set_openclaude_terminal_running(False)
        self._set_agent_status("OpenClaude stopped")
        self._reset_progress_idle()
        self._log("Embedded OpenClaude terminal closed.")

    def _on_openclaude_prompt_started(self, message: str):
        self._log(str(message or "Project prompt started"))
        self._set_openclaude_prompt_running(True)
        self._set_agent_status("Project prompt running")
        self._set_progress(None, "project prompt running")
        try:
            self.openclaude_prompt_output.fit()
            self.openclaude_prompt_output.focus_terminal()
        except Exception:
            pass

    def _on_openclaude_prompt_failed(self, message: str):
        self._append_openclaude_prompt_output(f"\n[Prompt error] {message}\n")
        self._set_openclaude_prompt_running(False)
        self._set_agent_status("Project prompt error")
        self._set_progress(None, "prompt error")
        self._log(f"OpenClaude prompt tab error: {message}")

    def _on_openclaude_prompt_completed(self):
        self._append_openclaude_prompt_output(
            "\n[fzastro] Project prompt closed. Press Start Prompt to reopen it at the selected workspace.\n"
        )
        self._set_openclaude_prompt_running(False)
        self._set_agent_status("Project prompt stopped")
        self._reset_progress_idle()
        self._log("OpenClaude prompt tab closed.")

    def _clear_openclaude_terminal_thread(self):
        self.openclaude_thread = None
        self.openclaude_worker = None
        self._openclaude_launch_snapshot = None
        self._set_openclaude_terminal_running(False)

    def _clear_openclaude_prompt_thread(self):
        self.openclaude_prompt_thread = None
        self.openclaude_prompt_worker = None
        self._set_openclaude_prompt_running(False)

    def _is_raw_openclaude_command(self, text: str) -> bool:
        return str(text or "").lstrip().startswith("/")

    def _openclaude_terminal_payload(
        self, *, prompt: str, prompt_path: Path, user_text: str
    ) -> str:
        clean = str(user_text or "").strip()
        # With a real terminal frontend, behave like OpenClaude/Codex: send what
        # the user typed into the terminal.  The generated prompt/context file is
        # still written for audit/logging and the workspace AGENTS.md carries the
        # stable project rules, but it is no longer pasted into the TUI.
        self._prepare_openclaude_prompt_echo_filter(clean)
        return clean.rstrip("\r\n") + "\r"

    def send_embedded_openclaude_input(self):
        """Backward-compatible alias: the single composer is the terminal input."""
        self.send_openclaude_task_to_terminal()

    def send_openclaude_task_to_terminal(self):
        user_text = self.request_edit.toPlainText().strip()
        if not user_text:
            return
        prompt = self._openclaude_task_prompt()
        prompt_path = write_openclaude_task_prompt(prompt)
        try:
            config = self._openclaude_launch_config(install_if_missing=False)
            mode = str(self.mode_combo.currentText() or "plan")
            safety = str(self.safety_combo.currentText() or "ask-before-editing")
            ensure_openclaude_agents_file(config, mode=mode, safety=safety)
        except Exception:
            pass
        QGuiApplication.clipboard().setText(prompt)
        worker = self.openclaude_worker
        if worker is None:
            self._append_openclaude_terminal_output(
                f"fzastro$ task saved to {prompt_path}. Click Run to start OpenClaude.\n"
            )
            return
        if self._is_raw_openclaude_command(user_text):
            self._append_openclaude_terminal_output(f"\nfzastro$ {user_text}\n")
        else:
            self._append_openclaude_terminal_output(f"\nfzastro$ task sent\n")
        worker.send_input(
            self._openclaude_terminal_payload(
                prompt=prompt,
                prompt_path=prompt_path,
                user_text=user_text,
            )
        )
        self._mark_openclaude_submission_started()
        self._clear_openclaude_composer_after_submit()
        self._log("Sent compatibility OpenClaude input.")

    def stop_embedded_openclaude_terminal(self):
        worker = self.openclaude_worker
        if worker is not None:
            worker.request_stop()
        self._set_openclaude_terminal_running(False)
        self._set_agent_status("Stopping embedded OpenClaude")
        self._set_progress(None, "stopping embedded OpenClaude")
        self._append_openclaude_terminal_output("\n[Stop requested]\n")

    def stop_openclaude_prompt_terminal(self):
        worker = self.openclaude_prompt_worker
        if worker is not None:
            worker.request_stop()
        self._set_openclaude_prompt_running(False)
        self._set_agent_status("Stopping project prompt")
        self._set_progress(None, "stopping project prompt")
        self._append_openclaude_prompt_output("\n[Prompt stop requested]\n")

    def _stop_terminal_worker_for_close(
        self, worker_attr: str, thread_attr: str
    ) -> None:
        """Best-effort stop for an embedded PTY before the app/window exits.

        PyInstaller one-file cleanup can fail on Windows when a child terminal
        still has handles open against the temporary _MEI extraction directory.
        Closing the ConPTY before accepting the window close keeps shutdown
        deterministic and avoids the visible PyInstaller temp-dir warning.
        """

        worker = getattr(self, worker_attr, None)
        thread = getattr(self, thread_attr, None)
        if worker is not None:
            try:
                worker.request_stop()
            except Exception:
                pass

        if thread is None:
            return

        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2500):
                    try:
                        thread.terminate()
                        thread.wait(1000)
                    except Exception:
                        pass
        except RuntimeError:
            pass
        except Exception:
            pass

    def shutdown_embedded_terminals_for_close(self) -> None:
        """Stop Claude and Prompt PTYs before the workspace tab or app closes."""

        try:
            self._openclaude_terminal_output_timer.stop()
        except Exception:
            pass
        self._stop_terminal_worker_for_close("openclaude_worker", "openclaude_thread")
        self._stop_terminal_worker_for_close(
            "openclaude_prompt_worker", "openclaude_prompt_thread"
        )
        self.openclaude_worker = None
        self.openclaude_thread = None
        self.openclaude_prompt_worker = None
        self.openclaude_prompt_thread = None
        self._set_openclaude_terminal_running(False)
        self._set_openclaude_prompt_running(False)

    def prepare_for_app_shutdown(self) -> None:
        """Called by the main window before PyInstaller temp cleanup runs."""

        self.shutdown_embedded_terminals_for_close()

    def closeEvent(self, event):
        self.shutdown_embedded_terminals_for_close()
        super().closeEvent(event)

    def open_openclaude_external_terminal(self):
        self._refresh_root()
        config = self._openclaude_launch_config(install_if_missing=False)
        prompt = self._openclaude_task_prompt()
        try:
            result = launch_openclaude_companion(config, task_prompt=prompt)
        except OpenClaudeBridgeError as exc:
            QMessageBox.warning(self, "OpenClaude Companion", str(exc))
            self._append_workspace_card(
                "# OpenClaude Fallback Not Started\n\n"
                f"{exc}\n\n"
                "Review the Session tab diagnostics, or select the real source checkout in the Project field."
            )
            self._log(f"OpenClaude external terminal launch blocked: {exc}")
            return

        QGuiApplication.clipboard().setText(result.safe_prompt)
        prompt_path = result.prompt_path or write_openclaude_task_prompt(
            result.safe_prompt
        )
        self._append_workspace_card(
            "# OpenClaude Fallback Launched\n\n"
            f"**Script:** `{result.script_path}`\n\n"
            f"**Prompt file:** `{prompt_path}`\n\n"
            f"**Model:** `{config.model}`\n\n"
            f"**Endpoint:** `{config.base_url}`\n\n"
            "The structured FZAstro OpenClaude task prompt and project context were written under AppData. The prompt was copied to the clipboard for the external fallback."
        )
        self._log(
            "Launched OpenClaude external terminal and copied structured OpenClaude prompt."
        )

    def open_openclaude_companion(self):
        # Backward-compatible slot name retained for older tests/actions.
        self.open_openclaude_external_terminal()

    def refresh_telemetry_from_app(self):
        """Mirror main-window telemetry in the OpenClaude workspace.

        The OpenClaude panel should not start another telemetry worker. It only copies
        labels already maintained by the main app when they are available.
        """

        def _copy_label(source_name: str, target: QLabel, fallback: str):
            source = getattr(self._runtime_owner(), source_name, None)
            text = ""
            tooltip = ""
            try:
                text = source.text() if source is not None else ""
                tooltip = source.toolTip() if source is not None else ""
            except RuntimeError:
                text = ""
                tooltip = ""
            target.setText(str(text or "").strip() or fallback)
            target.setToolTip(str(tooltip or "").strip() or fallback)

        _copy_label("gpu_label", self.gpu_telemetry_label, "GPU telemetry unavailable")
        _copy_label(
            "system_label", self.system_telemetry_label, "CPU/RAM telemetry unavailable"
        )

    def _set_agent_status(self, text: str):
        try:
            self.agent_status_label.setText(str(text or "Agent idle"))
        except RuntimeError:
            pass

    def _set_openclaude_state_badge(self, state: str) -> None:
        """Show OpenClaude state on the Start/Restart button, not the telemetry strip."""

        hidden_label = getattr(self, "openclaude_state_label", None)
        if hidden_label is not None:
            try:
                hidden_label.setVisible(False)
            except RuntimeError:
                pass

        button = getattr(self, "openclaude_launch_button", None)
        if button is None:
            return

        normalized = (state or "idle").strip().lower()
        if any(
            token in normalized
            for token in ("error", "failed", "unavailable", "blocked", "stopped")
        ):
            text = "Start"
            background = "#111820"
            foreground = "#d6e4f5"
            border = "#2a3644"
            tooltip = "OpenClaude is stopped or unavailable. Click to start a new terminal session."
        elif any(token in normalized for token in ("start", "launch", "stopping")):
            text = "Starting..."
            background = "#332509"
            foreground = "#ffd479"
            border = "#8a6a1f"
            tooltip = "OpenClaude is starting."
        elif any(
            token in normalized
            for token in (
                "running",
                "ready",
                "thinking",
                "waiting",
                "executing",
                "reading",
                "sent",
                "complete",
                "done",
            )
        ):
            text = "Restart"
            background = "#0f2d1b"
            foreground = "#7ee787"
            border = "#267a3d"
            tooltip = (
                "OpenClaude is running. Click to restart the embedded terminal session."
            )
        else:
            text = "Start"
            background = "#111820"
            foreground = "#d6e4f5"
            border = "#2a3644"
            tooltip = "Start the embedded OpenClaude terminal session."

        try:
            button.setText(text)
            button.setToolTip(tooltip)
            button.setStyleSheet(
                "QPushButton {"
                f"color: {foreground};"
                f"background: {background};"
                f"border: 1px solid {border};"
                "border-radius: 8px;"
                "padding: 6px 12px;"
                "font-weight: 700;"
                "}"
                "QPushButton:hover { border-color: #4b80c9; }"
            )
        except RuntimeError:
            pass

    def _set_progress(self, value: int | None, text: str):
        """Update the compact OpenClaude state line.

        The OpenClaude terminal is a live interactive session, so percentages are
        misleading. Keep telemetry visible and show a clear running/stopped
        indicator instead of a progress bar.
        """

        del value
        status_text = str(text or "idle").strip() or "idle"
        try:
            self.progress_label.setText(f"State: {status_text}")
            self._set_openclaude_state_badge(status_text)
        except RuntimeError:
            pass

    def _reset_progress_idle(self):
        self._set_progress(0, "idle")

    def _selected_mode(self) -> AgentMode:
        return AgentMode(self.mode_combo.currentText())

    def _selected_safety_mode(self) -> SafetyMode:
        return SafetyMode(self.safety_combo.currentText())

    def _task_mode_for_request(self, request: str) -> str:
        """Return the classified task mode for the current request.

        The visible OpenClaude run button may be pressed before any internal context plan, or after the
        task text has changed.  Do not read a nonexistent ``session.task``
        attribute; classify the current request directly and fall back to the
        last built plan only when classification fails.
        """

        clean_request = str(request or "").strip()
        latest_task = getattr(self, "latest_task", None)
        if (
            latest_task is not None
            and getattr(latest_task, "request", "") == clean_request
        ):
            return str(getattr(latest_task, "mode", "ask") or "ask")
        try:
            return str(self.session.classify(clean_request).mode or "ask")
        except Exception:
            if latest_task is not None:
                return str(getattr(latest_task, "mode", "ask") or "ask")
            return "ask"

    def _update_mode_help(self):
        mode = self._selected_mode().value
        safety = self._selected_safety_mode().value
        self.mode_help_label.setText(
            "OpenClaude behavior is controlled by the terminal conversation and AGENTS.md."
        )

    def toggle_evidence_panel(self):
        self._set_evidence_visible(self._drawer_mode != "evidence")

    def toggle_advanced_panel(self):
        self._set_advanced_visible(self._drawer_mode != "advanced")

    def _current_drawer_width(self) -> int:
        try:
            sizes = self.workspace_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > 0:
                return max(320, min(820, int(sizes[1])))
        except Exception:
            pass
        return max(320, min(820, int(getattr(self, "_drawer_width", 460))))

    def _remember_workspace_drawer_width(self):
        if getattr(self, "_drawer_mode", "") and hasattr(self, "workspace_splitter"):
            self._drawer_width = self._current_drawer_width()

    def _restore_workspace_splitter_sizes(self):
        if not hasattr(self, "workspace_splitter"):
            return
        try:
            total = max(900, int(self.workspace_splitter.width() or self.width()))
            drawer_width = max(320, min(820, int(getattr(self, "_drawer_width", 460))))
            if self.drawer_frame.isVisible():
                self.workspace_splitter.setSizes(
                    [max(420, total - drawer_width), drawer_width]
                )
            else:
                self.workspace_splitter.setSizes([total, 0])
        except Exception:
            pass

    def close_workspace_drawer(self):
        if getattr(self, "_drawer_mode", ""):
            self._drawer_width = self._current_drawer_width()
        self._drawer_mode = ""
        self.evidence_panel.setVisible(False)
        self.advanced_panel.setVisible(False)
        self.drawer_frame.setVisible(False)
        self._restore_workspace_splitter_sizes()
        self._refresh_drawer_buttons()

    def _refresh_drawer_buttons(self):
        count = self.file_list.count() if hasattr(self, "file_list") else 0
        evidence_label = f"Internal files · {count}" if count else "Internal files"
        if self._drawer_mode == "evidence":
            self.evidence_toggle_button.setText(f"{evidence_label} ◂")
        else:
            self.evidence_toggle_button.setText(f"{evidence_label} ▸")
        self.advanced_toggle_button.setText(
            "Internal Details ◂"
            if self._drawer_mode == "advanced"
            else "Internal Details ▸"
        )

    def _open_workspace_drawer(self, mode: str):
        mode = "advanced" if mode == "advanced" else "evidence"
        if getattr(self, "_drawer_mode", "") and self.drawer_frame.isVisible():
            self._drawer_width = self._current_drawer_width()
        self._drawer_mode = mode
        self.evidence_panel.setVisible(mode == "evidence")
        self.advanced_panel.setVisible(mode == "advanced")
        self.drawer_title_label.setText(
            "Internal Files" if mode == "evidence" else "Internal Details"
        )
        self.drawer_frame.setVisible(True)
        QTimer.singleShot(0, self._restore_workspace_splitter_sizes)
        self._refresh_drawer_buttons()

    def _set_evidence_visible(self, visible: bool):
        if visible:
            self._open_workspace_drawer("evidence")
        elif self._drawer_mode == "evidence":
            self.close_workspace_drawer()
        else:
            self._refresh_drawer_buttons()

    def _set_advanced_visible(self, visible: bool):
        if visible:
            self._open_workspace_drawer("advanced")
        elif self._drawer_mode == "advanced":
            self.close_workspace_drawer()
        else:
            self._refresh_drawer_buttons()

    def _select_advanced_widget(self, widget, *, reveal: bool = False):
        try:
            self.tabs.setCurrentWidget(widget)
        except Exception:
            pass
        if reveal:
            self._set_advanced_visible(True)

    def _show_workspace(self):
        try:
            self.workspace_tabs.setCurrentWidget(self.openclaude_terminal_frame)
            self.openclaude_terminal_output.setFocus()
        except Exception:
            pass

    def _refresh_evidence_button(self):
        if hasattr(self, "evidence_panel"):
            self._set_evidence_visible(self.evidence_panel.isVisible())

    def _patch_card_markdown(
        self, proposal: PatchProposal, *, title: str = "Patch Proposal"
    ) -> str:
        changed = "\n".join(f"- `{path}`" for path in proposal.target_files) or "- None"
        return "\n".join(
            [
                f"# {title}",
                "",
                f"**Risk:** {proposal.risk_level.value}",
                "",
                "**Changed files:**",
                changed,
                "",
                "## Reason",
                proposal.reason,
                "",
                "## Unified diff",
                "```diff",
                proposal.unified_diff,
                "```",
                "",
                "**Next:** Preview this patch, then apply only if the diff is correct.",
            ]
        )

    def _append_workspace_card(self, markdown: str):
        current = str(
            self._agent_stream_markdown
            or self.agent_transcript_markdown
            or "# OpenClaude Workspace"
        ).rstrip()
        self._agent_stream_markdown = (
            current + "\n\n---\n\n" + str(markdown or "").strip() + "\n"
        )
        self.agent_transcript_markdown = self._agent_stream_markdown.rstrip()
        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._scroll_text_widget_to_end(self.plan_output)
        terminal_text = str(markdown or "").strip()
        if terminal_text:
            self._append_openclaude_terminal_output(
                "\n[fzastro status] " + terminal_text.replace("\n", "\n") + "\n"
            )
        self._show_workspace()

    def _refresh_root(self):
        self.project_root = Path(self.root_input.text().strip()).expanduser().resolve()
        self.session = DevAgentSession(
            self.project_root,
            mode=self._selected_mode(),
            safety_mode=self._selected_safety_mode(),
        )
        self._persist_project_root_if_valid()
        self._update_runtime_status()

    def _set_next_step(self, text: str):
        self.next_step_label.setText(text)
        self._update_action_buttons()

    @staticmethod
    def _format_duration(seconds: float | int | None) -> str:
        try:
            total = max(0, int(float(seconds or 0)))
        except Exception:
            total = 0
        minutes, secs = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _set_agent_activity(
        self,
        phase: str,
        detail: str = "",
        *,
        context_count: int | None = None,
        touch: bool = True,
    ) -> None:
        self._agent_activity_phase = str(phase or "working")
        self._agent_activity_detail = str(detail or "").strip()
        if context_count is not None:
            try:
                self._agent_activity_context_count = max(0, int(context_count))
            except Exception:
                self._agent_activity_context_count = 0
        now = time.monotonic()
        if touch:
            self._agent_last_activity_monotonic = now
        if self._agent_started_monotonic is None and self._agent_busy:
            self._agent_started_monotonic = now
        self._refresh_agent_activity_label()

    def _refresh_agent_activity_label(self) -> None:
        if not hasattr(self, "agent_activity_label"):
            return
        if (
            self._agent_busy
            or self.agent_thread is not None
            or self.agent_worker is not None
        ):
            now = time.monotonic()
            started = self._agent_started_monotonic or now
            last = self._agent_last_activity_monotonic or started
            detail = (
                f" · {self._agent_activity_detail}"
                if self._agent_activity_detail
                else ""
            )
            context_text = ""
            if self._agent_activity_context_count:
                context_text = (
                    f" · context {self._agent_activity_context_count} file(s)"
                )
            self.agent_activity_label.setText(
                "Activity: "
                f"{self._agent_activity_phase}{detail} · elapsed {self._format_duration(now - started)} "
                f"· last activity {self._format_duration(now - last)} ago{context_text}. "
                "Private reasoning is not shown; OpenClaude shows tool/model activity only."
            )
            return
        final_detail = (
            f" · {self._agent_activity_detail}" if self._agent_activity_detail else ""
        )
        self.agent_activity_label.setText(
            f"Activity: {self._agent_activity_phase}{final_detail}. "
            "Tool and model activity appears here while a run is active; private reasoning is not shown."
        )

    def _start_agent_activity_monitor(self, *, context_count: int = 0) -> None:
        now = time.monotonic()
        self._agent_started_monotonic = now
        self._agent_last_activity_monotonic = now
        self._agent_activity_context_count = max(0, int(context_count or 0))
        self._set_agent_activity(
            "starting", "preparing active model request", touch=False
        )
        if not self._agent_activity_timer.isActive():
            self._agent_activity_timer.start(1000)

    def _finish_agent_activity(self, phase: str, detail: str = "") -> None:
        if self._agent_activity_timer.isActive():
            self._agent_activity_timer.stop()
        self._set_agent_activity(phase, detail, touch=True)

    def _on_mode_or_safety_changed(self):
        self._update_mode_help()
        try:
            self.session.mode = self._selected_mode()
            self.session.safety_mode = self._selected_safety_mode()
        except Exception:
            pass
        self._update_action_buttons()

    def _has_patch_text(self) -> bool:
        try:
            text = self.patch_output.toPlainText().strip()
        except Exception:
            text = ""
        return bool(
            self.latest_proposal is not None
            or text.startswith("diff --git")
            or text.startswith("--- a/")
            or "\n+++ b/" in text
        )

    def _set_workflow_stage(self, stage: str, next_step: str | None = None):
        self._workflow_stage = str(stage or "start")
        if next_step is not None:
            self.next_step_label.setText(next_step)
        self._update_action_buttons()

    def _style_action_button(
        self, button: QPushButton, *, is_next: bool, is_blocked: bool = False
    ):
        if is_next:
            button.setStyleSheet(
                "font-weight: 700; border: 1px solid #4da3ff; padding: 5px 10px;"
            )
        elif is_blocked:
            button.setStyleSheet("color: #7c8796; padding: 5px 10px;")
        else:
            button.setStyleSheet("")

    def _update_action_buttons(self):
        if not hasattr(self, "_button_base_labels"):
            return
        busy = (
            bool(getattr(self, "_agent_busy", False))
            or self.agent_thread is not None
            or self.agent_worker is not None
        )
        has_scan = self.session.scan is not None
        has_context = bool(self.latest_prompt_package)
        has_patch = self._has_patch_text()
        has_validation = bool(self.latest_checks)
        request_ready = False
        openclaude_running = bool(
            getattr(self, "_openclaude_terminal_running", False)
            and self.openclaude_worker is not None
        )

        if busy:
            next_button = self.stop_agent_button
        elif has_patch and not self._patch_previewed:
            next_button = self.preview_patch_button
        elif self._patch_previewed and not self._patch_applied:
            next_button = self.apply_patch_button
        elif self._patch_applied and not has_validation:
            next_button = self.compile_button
        elif has_validation:
            next_button = self.final_report_button
        else:
            next_button = self.openclaude_launch_button

        enabled = {
            button: not busy
            for button in (*self.workflow_buttons, *self.utility_buttons)
        }
        if busy:
            for button in enabled:
                enabled[button] = False
            enabled[self.stop_agent_button] = True
            self.stop_agent_button.setText(
                "Stopping..." if self._agent_stop_requested else "Stop Agent"
            )
        else:
            enabled[self.stop_agent_button] = False
            self.stop_agent_button.setText("Stop Agent")
            # Step 4 stays clickable to show inline guidance when a diff does
            # not exist yet; Step 5 remains locked until preview succeeds.
            enabled[self.preview_patch_button] = True
            enabled[self.apply_patch_button] = bool(
                self._patch_previewed
                and self.latest_proposal is not None
                and self._selected_safety_mode() != SafetyMode.READ_ONLY
            )
            enabled[self.compile_button] = True
            enabled[self.openclaude_launch_button] = True
            enabled[self.openclaude_send_task_button] = False
            enabled[self.openclaude_stop_button] = bool(openclaude_running)
            enabled[self.openclaude_clear_button] = True
            enabled[self.openclaude_paste_button] = bool(openclaude_running)
            enabled[self.openclaude_help_button] = bool(openclaude_running)
            enabled[self.openclaude_ctx_button] = bool(openclaude_running)
            enabled[self.openclaude_slash_clear_button] = bool(openclaude_running)
            enabled[self.openclaude_config_button] = bool(openclaude_running)
            enabled[self.openclaude_buddy_button] = bool(openclaude_running)
            enabled[self.openclaude_page_up_button] = True
            enabled[self.openclaude_bottom_button] = True
            enabled[self.openclaude_screenshot_button] = True
            enabled[self.openclaude_paste_image_button] = True
            enabled[self.openclaude_attach_image_button] = True
            enabled[self.openclaude_send_screenshot_button] = True
            enabled[self.final_report_button] = bool(
                has_context
                or has_patch
                or has_validation
                or self.agent_transcript_markdown.strip()
            )

        tooltips = {
            self.openclaude_status_button: "Check Node.js, npm, OpenClaude, selected model, endpoint, project workspace, and embedded ConPTY backend.",
            getattr(
                self, "openclaude_save_api_button", None
            ): "Save the OpenClaude Git API token under FZAstro AppData. The value is hidden and not written to the project workspace.",
            getattr(
                self, "openclaude_clear_api_button", None
            ): "Remove the saved OpenClaude Git API token from FZAstro AppData.",
            self.openclaude_launch_button: "Start or restart the embedded OpenClaude terminal in the selected workspace.",
            self.openclaude_send_task_button: "Hidden compatibility action; normal OpenClaude input goes directly through the terminal.",
            self.openclaude_stop_button: "Stop the embedded OpenClaude terminal session.",
            self.openclaude_clear_button: "Clear the visible OpenClaude terminal output.",
            self.openclaude_paste_button: "Paste clipboard text directly into the running OpenClaude terminal.",
            self.openclaude_help_button: "Send /help to the running OpenClaude terminal.",
            self.openclaude_ctx_button: "Send /ctx to the running OpenClaude terminal.",
            self.openclaude_slash_clear_button: "Send /clear to the running OpenClaude terminal.",
            self.openclaude_config_button: "Send /config to the running OpenClaude terminal.",
            self.openclaude_buddy_button: "Send /buddy to the running OpenClaude terminal.",
            self.openclaude_page_up_button: "Scroll terminal history up without stopping live output.",
            self.openclaude_top_button: "Jump to the oldest retained OpenClaude terminal scrollback.",
            self.openclaude_bottom_button: "Return to the live terminal tail and resume follow mode.",
            self.openclaude_screenshot_button: "Save a PNG screenshot of the visible terminal and copy its path to the clipboard.",
            self.openclaude_paste_image_button: "Save a screenshot/image from the clipboard into the workspace and send its path to OpenClaude.",
            self.openclaude_attach_image_button: "Choose an image file, copy it into the workspace attachment folder, and hand its path to OpenClaude.",
            self.openclaude_send_screenshot_button: "Capture the visible terminal, save it into workspace attachments, and send that screenshot path to OpenClaude.",
            self.openclaude_prompt_button: "Copy the structured FZAstro OpenClaude task prompt without launching OpenClaude.",
            self.stop_agent_button: "Stop the visible agent run immediately and ignore late model output from the retired worker.",
            self.preview_patch_button: "Validate and review an existing unified diff. If none exists, this opens inline guidance.",
            self.apply_patch_button: "Apply the previewed patch after approval. Disabled until Step 4 succeeds.",
            self.compile_button: "Run project-aware compile validation from the selected project root.",
            self.final_report_button: "Build the final engineering report from visible evidence and validation output.",
        }

        for button in (*self.workflow_buttons, *self.utility_buttons):
            base = self._button_base_labels.get(button, button.text())
            suffix = ""
            blocked = False
            if button is self.preview_patch_button and not has_patch and not busy:
                suffix = " (needs diff)"
            elif (
                button is self.apply_patch_button
                and not enabled.get(button, False)
                and not busy
            ):
                suffix = " (after preview)"
                blocked = True
            label = base + suffix
            if button is next_button and enabled.get(button, False):
                label = base + suffix
            button.setText(label)
            button.setEnabled(bool(enabled.get(button, True)))
            button.setToolTip(tooltips.get(button, ""))
            self._style_action_button(
                button,
                is_next=(button is next_button and enabled.get(button, False)),
                is_blocked=blocked or not enabled.get(button, True),
            )
        self._update_openclaude_composer_buttons()

    def _log(self, text: str):
        self.action_log.appendPlainText(text.rstrip() + "\n")

    def _set_markdown_output(self, widget, markdown: str):
        """Render markdown where supported, with a plain-text fallback.

        The OpenClaude prompt asks models to return structured markdown.
        Rendering it avoids the unreadable raw-table/raw-heading blocks that
        made the plan tab hard to review.
        """
        text = str(markdown or "")
        try:
            widget.setMarkdown(text)
        except Exception:
            widget.setPlainText(text)

    def _scroll_text_widget_to_end(self, widget):
        try:
            widget.moveCursor(QTextCursor.End)
        except Exception:
            pass
        try:
            bar = widget.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception:
            pass

    def _show_agent_error(self, title: str, message: str):
        lines = [
            f"# {title}",
            "",
            message,
            "",
            "## What to check",
            "1. Confirm the model selected in the top bar is listed by the configured provider.",
            "2. Press the main app model refresh button if the model list is stale.",
            "3. For local Ollama, start Ollama from the main toolbar first; OpenClaude will not auto-start it.",
            "4. Use `Run`; if the embedded backend fails, fix setup/build/deploy before retrying.",
        ]
        self._agent_stream_markdown = "\n".join(lines)
        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._show_workspace()
        self._log(f"{title}: {message}")
        self._set_next_step(
            "Fix the active model/runtime selection, then restart the OpenClaude terminal."
        )

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def browse_root(self):
        selected = QFileDialog.getExistingDirectory(
            self, "Choose FZAstro AI project root", str(self.project_root)
        )
        if selected:
            self.root_input.setText(selected)
            self._refresh_root()
            self._log(f"Project root set: {self.project_root}")
            self._refresh_session_details()
            self._set_next_step(
                "Workspace selected. Start OpenClaude, then type directly in the terminal."
            )

    def scan_project(self):
        self._refresh_root()
        self._set_progress(10, "scanning project")
        QApplication.processEvents()
        try:
            scan = self.session.refresh_scan()
        except Exception as exc:
            self._set_progress(0, "scan failed")
            QMessageBox.critical(self, "Scan failed", str(exc))
            return
        self.summary_label.setText(
            f"Scanned {scan.file_count} files · {scan.python_count} Python · "
            f"{scan.test_count} tests · ignored {scan.ignored_count} · oversized {scan.oversized_count}."
        )
        self.file_list.clear()
        for file in scan.files[:300]:
            marker = " *modified" if file.modified else ""
            item = QListWidgetItem(f"{file.path}  [{file.role}]{marker}")
            item.setToolTip(
                f"{file.size} bytes\nSymbols: {', '.join(file.symbols[:12]) or 'none'}"
            )
            self.file_list.addItem(item)
        self._refresh_evidence_button()
        self._select_advanced_widget(self.action_log)
        scan_card = "\n".join(
            [
                "# Scan complete",
                "",
                f"Indexed **{scan.file_count} files** · **{scan.python_count} Python** · **{scan.test_count} tests**.",
                f"Ignored {scan.ignored_count} files · oversized {scan.oversized_count}.",
                "",
                "**Next:** enter or refine the task in the composer, then run In-App Claude.",
            ]
        )
        self._agent_stream_markdown = scan_card
        self.agent_transcript_markdown = scan_card
        self._set_markdown_output(self.plan_output, scan_card)
        self._scroll_text_widget_to_end(self.plan_output)
        self._show_workspace()
        self._log(self.summary_label.text())
        self._set_progress(100, "scan complete")
        self._set_workflow_stage(
            "scanned",
            "Enter a task if needed, then run In-App Claude.",
        )

    def build_context_plan(self):
        self._refresh_root()
        self._set_progress(15, "building context")
        QApplication.processEvents()
        request = self.request_edit.toPlainText().strip()
        if not request:
            self._reset_progress_idle()
            QMessageBox.information(
                self, "Task needed", "Enter a OpenClaude task first."
            )
            return
        self.latest_proposal = None
        self.latest_changed_paths = ()
        self._patch_previewed = False
        self._patch_applied = False
        self.patch_output.clear()
        try:
            result = self.session.prepare(request)
        except Exception as exc:
            self._set_progress(0, "context build failed")
            QMessageBox.critical(self, "Context build failed", str(exc))
            return

        self.latest_prompt_package = result.context.prompt_package
        self.latest_system_prompt = result.system_prompt
        self.latest_plan = result.plan_markdown
        self.latest_task = result.task
        self._agent_stream_markdown = result.plan_markdown
        self._set_markdown_output(self.plan_output, result.plan_markdown)
        self.context_output.setPlainText(
            result.system_prompt + "\n\n---\n\n" + result.context.prompt_package
        )
        self.summary_label.setText(result.context.summary.replace("\n", " · "))
        self.file_list.clear()
        for file in result.context.files:
            item = QListWidgetItem(f"{file.path}  score={file.score:g}  [{file.role}]")
            item.setToolTip(file.reason)
            self.file_list.addItem(item)
        self._refresh_evidence_button()
        self._show_workspace()
        self._log("Built OpenClaude context and visible plan. No files changed.")
        self._set_progress(100, "context ready")
        self._set_workflow_stage(
            "planned",
            "OpenClaude context is ready. Type the next task and run In-App Claude.",
        )

    def _next_agent_run_id(self) -> int:
        self._agent_run_id += 1
        return self._agent_run_id

    def _is_current_agent_run(self, run_id: int) -> bool:
        return (
            int(run_id) == int(getattr(self, "_agent_run_id", 0))
            and not self._agent_stop_requested
        )

    def _drop_retired_agent_run(self, run_id: int):
        self._retired_agent_runs = [
            item for item in self._retired_agent_runs if item[0] != int(run_id)
        ]

    def _detach_current_agent_run(self, run_id: int | None = None):
        thread = self.agent_thread
        worker = self.agent_worker
        retired_run_id = int(self._agent_run_id if run_id is None else run_id)
        if thread is not None and worker is not None:
            self._retired_agent_runs.append((retired_run_id, thread, worker))
        self.agent_thread = None
        self.agent_worker = None

    def run_local_agent(self):
        self._refresh_root()
        request = self.request_edit.toPlainText().strip()
        if not request:
            QMessageBox.information(
                self, "Task needed", "Enter a OpenClaude task first."
            )
            return
        if self.agent_thread is not None:
            QMessageBox.information(
                self,
                "Agent already running",
                "Wait for the current OpenClaude request to finish before starting another one.",
            )
            return

        run_id = self._next_agent_run_id()
        config = self._main_app_runtime_config()
        self._update_runtime_status()
        self._log(
            f"Using active FZAstro model runtime: {config.model} @ {config.normalized_base_url}"
        )
        steering = self._current_steering_text()
        if steering:
            self._log("Using OpenClaude steering guidance for this turn.")

        self._agent_active_request = request
        self.request_edit.clear()
        self._agent_stop_requested = False
        self._agent_is_followup = bool(self.agent_conversation_messages)
        conversation_messages = None
        if self._agent_is_followup:
            conversation_messages = list(self.agent_conversation_messages)
            followup_content = "OpenClaude follow-up from the user:\n" + request
            conversation_messages.append(
                {
                    "role": "user",
                    "content": followup_content,
                }
            )
            if self.agent_transcript_markdown.strip():
                self._agent_stream_markdown = (
                    self.agent_transcript_markdown.rstrip()
                    + "\n\n---\n\n## You\n"
                    + request
                    + "\n\n## Agent\n"
                )
            else:
                self._agent_stream_markdown = (
                    "# OpenClaude Chat\n\n## You\n" + request + "\n\n## Agent\n"
                )
            self._log("Continuing existing OpenClaude conversation.")
        else:
            self._agent_stream_markdown = (
                "# OpenClaude Chat\n\n" "## You\n" + request + "\n\n## Agent\n"
            )
            self._log("Starting new OpenClaude conversation.")

        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._show_workspace()
        if (
            self._selected_mode() == AgentMode.REVIEW_ONLY
            and self._task_mode_for_request(request) == "patch"
        ):
            self._set_next_step(
                "This task asks for a patch, but mode is Review Only. The agent can inspect and propose direction only; switch to Patch Files or Patch + Run Tests to generate a patch proposal."
            )
        else:
            self._set_next_step(
                "Agent is working. Use Stop Agent if it keeps inspecting too long. When it asks a question, type your reply and click 3 again."
            )
        self._set_agent_status(
            "Agent working · fast patch context enabled · Stop Agent cancels the visible run"
        )
        self._set_progress(None, "agent running")
        self._set_workflow_stage("running")
        self._set_agent_busy(True)
        self._start_agent_activity_monitor(context_count=self.file_list.count())
        self._start_agent_timeout_timer_if_configured()

        thread = QThread(self)
        worker = _DevAgentWorker(
            run_id=run_id,
            project_root=self.project_root,
            request=request,
            config=config,
            mode=self._selected_mode(),
            safety_mode=self._selected_safety_mode(),
            max_steps=8,
            conversation_messages=conversation_messages,
            steering=steering,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.stream_delta.connect(self._append_agent_stream_delta_for_run)
        worker.event.connect(self._handle_agent_event_for_run)
        worker.finished.connect(self._handle_agent_result_for_run)
        worker.failed.connect(self._handle_agent_error_for_run)
        worker.completed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda rid=run_id: self._clear_agent_worker(rid))
        thread.finished.connect(lambda rid=run_id: self._drop_retired_agent_run(rid))
        self.agent_thread = thread
        self.agent_worker = worker
        thread.start()

    def _set_agent_busy(self, busy: bool):
        self._agent_busy = bool(busy)
        if not busy and not self._agent_stop_requested:
            self._set_agent_status("Agent idle")
        self._update_action_buttons()

    def _current_steering_text(self) -> str:
        # Steering is internal-only. User-visible task/reply text lives in the
        # main composer; queued internal notes can still be applied by tests or
        # future non-visible controls.
        notes = [note for note in self.agent_steering_notes if str(note).strip()]
        return "\n".join(f"- {note}" for note in notes)

    def add_agent_steering(self):
        note = self.steering_input.text().strip()
        if not note:
            QMessageBox.information(
                self,
                "Steering needed",
                "No internal guidance note is queued.",
            )
            return
        if self.agent_worker is not None:
            try:
                self.agent_worker.add_steering_note(note)
            except RuntimeError:
                self.agent_steering_notes.append(note)
            self._log(f"Queued OpenClaude steering: {note}")
            self._agent_stream_markdown += (
                "\n\n> Steering queued for next agent step: " + note + "\n"
            )
            self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
            self._set_agent_status("Internal guidance queued")
            self._set_next_step(
                "Internal guidance queued. It applies before the next tool/model step."
            )
        else:
            self.agent_steering_notes.append(note)
            self._log(f"Saved OpenClaude steering for next Ask/Reply: {note}")
            self._set_next_step("Internal guidance saved for the next OpenClaude task.")
        self.steering_input.clear()

    def _start_agent_timeout_timer_if_configured(self):
        """Start the optional hard-run timeout only when explicitly configured.

        Local coding-agent jobs can legitimately spend several minutes in
        evidence review or patch generation. By default FZAstro no longer uses
        a wall-clock kill timer for OpenClaude runs; Stop Agent is the
        cancellation mechanism. Keeping this helper allows a future settings UI
        or tests to enable a hard limit deliberately without reintroducing an
        unconditional timeout.
        """
        if self._agent_timeout_timer.isActive():
            self._agent_timeout_timer.stop()
        timeout_ms = self._agent_timeout_ms
        if isinstance(timeout_ms, int) and timeout_ms > 0:
            self._agent_timeout_timer.start(timeout_ms)

    def stop_agent(self):
        if self.agent_thread is None and self.agent_worker is None:
            self._set_agent_status("Agent idle")
            return
        self._agent_stop_requested = True
        if self._agent_timeout_timer.isActive():
            self._agent_timeout_timer.stop()
        try:
            if self.agent_worker is not None:
                self.agent_worker.request_stop()
        except RuntimeError:
            pass
        try:
            if self.agent_thread is not None:
                self.agent_thread.requestInterruption()
        except RuntimeError:
            pass

        # Hard-cancel the visible run immediately. The provider request may still
        # drain in its worker thread, but every late signal is ignored because
        # the run id is invalidated and the old thread is retired.
        cancelled_run_id = int(self._agent_run_id)
        self._detach_current_agent_run(cancelled_run_id)
        self._agent_run_id += 1
        self._set_agent_busy(False)
        if self._agent_render_timer.isActive():
            self._agent_render_timer.stop()
            self._flush_agent_stream_markdown()
        if self._agent_activity_timer.isActive():
            self._agent_activity_timer.stop()
        self.stop_agent_button.setText("Stop Agent")
        self._set_agent_status("Agent stopped by user")
        self._finish_agent_activity(
            "stopped", "visible run cancelled; late model output ignored"
        )
        self._set_progress(0, "agent stopped")
        self._set_workflow_stage(
            "stopped",
            "Stopped by user. Revise the task and run In-App Claude to start again.",
        )
        self._log("OpenClaude stopped by user; retired worker output will be ignored.")

    def _handle_agent_timeout(self):
        if self.agent_thread is None:
            return
        self._agent_stop_requested = True
        try:
            if self.agent_worker is not None:
                self.agent_worker.request_stop()
        except RuntimeError:
            pass
        self.stop_agent_button.setText("Stopping...")
        self._set_agent_status("Run timeout reached · stopping agent")
        self._set_agent_activity("timeout requested", "waiting for model read to yield")
        self._set_progress(5, "timeout stop requested")
        self._set_next_step(
            "Optional hard timeout reached. Stop was requested; use a narrower task or continue from loaded evidence if the model keeps looping."
        )
        self._log("OpenClaude optional timeout reached; stop requested.")

    def _append_agent_stream_delta(self, delta: str):
        self._agent_stream_markdown += str(delta or "")
        if str(delta or "").strip():
            self._set_agent_activity("model streaming", "receiving visible output")
        if not self._agent_render_timer.isActive():
            self._agent_render_timer.start(80)

    def _append_agent_stream_delta_for_run(self, run_id: int, delta: str):
        if not self._is_current_agent_run(run_id):
            return
        self._append_agent_stream_delta(delta)

    def _handle_agent_event_for_run(self, run_id: int, event: object):
        if not self._is_current_agent_run(run_id):
            return
        self._handle_agent_event(event)

    def _handle_agent_result_for_run(self, run_id: int, result: object):
        if not self._is_current_agent_run(run_id):
            return
        self._handle_agent_result(result)

    def _handle_agent_error_for_run(self, run_id: int, title: str, message: str):
        if not self._is_current_agent_run(run_id):
            return
        self._handle_agent_error(title, message)

    def _flush_agent_stream_markdown(self):
        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._scroll_text_widget_to_end(self.plan_output)

    def _handle_agent_event(self, event):
        kind = getattr(event, "kind", "event")
        message = getattr(event, "message", str(event))
        data = getattr(event, "data", {}) or {}
        self._log(f"[{kind}] {message}")

        step = data.get("step") if isinstance(data, dict) else None
        max_steps = data.get("max_steps") if isinstance(data, dict) else None
        path = data.get("path") if isinstance(data, dict) else None
        tool_args = data.get("args") if isinstance(data, dict) else None
        tool_name = str(message or "")
        if isinstance(tool_args, dict):
            path = path or tool_args.get("path")
            tool_name = str(data.get("reason") or tool_name)

        if kind == "context_sanity":
            self._set_agent_status(str(message))
            self._set_agent_activity("context sanity", str(message))
            self._set_progress(24, "fast context ready")
            return
        if kind == "patch_preflight":
            self._set_agent_status(str(message))
            self._set_agent_activity("reading patch evidence", str(message))
            self._set_progress(18, "reading patch evidence")
            return
        if kind == "audit_coverage":
            self._set_agent_status(str(message))
            self._set_agent_activity("reading audit evidence", str(message))
            self._set_progress(18, "reading audit evidence")
            return
        if kind == "steering":
            self._set_agent_status("Internal guidance applied")
            return
        if kind == "tool_request":
            detail = f" `{path}`" if path else ""
            self._set_agent_status(f"Executing tool · {tool_name}{detail}")
            self._set_agent_activity("executing tool", f"{tool_name}{detail}")
            if step and max_steps:
                self._set_progress(
                    int(10 + (int(step) / max(1, int(max_steps))) * 80),
                    f"executing tool {step}/{max_steps}",
                )
            else:
                self._set_progress(None, "executing tool")
            return
        if kind == "tool_result":
            state = (
                "ok"
                if isinstance(data, dict) and data.get("ok")
                else "blocked" if isinstance(data, dict) else "done"
            )
            detail = f" `{path}`" if path else ""
            self._set_agent_status(f"Tool result · {state}{detail}")
            self._set_agent_activity("tool result", f"{state}{detail}")
            if path:
                self._set_progress(None, f"read {Path(str(path)).name}")
            return
        if kind == "model":
            if step and max_steps:
                self._set_agent_status(
                    f"Waiting for active model · step {step}/{max_steps}"
                )
                self._set_agent_activity(
                    "waiting for active model",
                    f"step {step}/{max_steps}; waiting for visible output or tool action",
                    touch=True,
                )
                try:
                    self._set_progress(
                        int(10 + (int(step) / max(1, int(max_steps))) * 80),
                        f"waiting for model {step}/{max_steps}",
                    )
                except Exception:
                    self._set_progress(None, "waiting for model")
            else:
                self._set_agent_status("Waiting for active model")
                self._set_agent_activity(
                    "waiting for active model",
                    "waiting for visible output or tool action",
                    touch=True,
                )
                self._set_progress(None, "waiting for model")
            return
        if kind == "final":
            self._set_agent_status("Agent finalizing answer")
            self._set_agent_activity("finalizing answer", "preparing visible result")
            self._set_progress(95, "finalizing answer")
            return
        if kind == "stop":
            self._set_agent_status("Agent stopped")
            self._finish_agent_activity("stopped", "run was cancelled")
            self._set_progress(0, "agent stopped")

    def _handle_agent_error(self, title: str, message: str):
        if self._agent_timeout_timer.isActive():
            self._agent_timeout_timer.stop()
        if self._agent_render_timer.isActive():
            self._agent_render_timer.stop()
        self._show_agent_error(title, message)
        self._set_agent_status("Agent error")
        self._finish_agent_activity("error", str(title or "agent error"))
        self._set_progress(0, "agent error")
        self._set_agent_busy(False)

    def _remember_agent_conversation(self, result) -> None:
        messages = getattr(result, "messages", ()) or ()
        if messages:
            self.agent_conversation_messages = [dict(message) for message in messages]
        if self._agent_stream_markdown.strip():
            self.agent_transcript_markdown = self._agent_stream_markdown.rstrip()

    def reset_agent_chat(self):
        if self.agent_thread is not None:
            QMessageBox.information(
                self,
                "Agent running",
                "Wait for the current OpenClaude request to finish before starting a new chat.",
            )
            return
        self.agent_conversation_messages = []
        self.agent_transcript_markdown = ""
        self.agent_steering_notes = []
        self.latest_proposal = None
        self.latest_changed_paths = ()
        self._patch_previewed = False
        self._patch_applied = False
        self._agent_stream_markdown = ""
        self._agent_active_request = ""
        self._agent_is_followup = False
        self.plan_output.clear()
        self.patch_output.clear()
        self._log("OpenClaude chat reset. Context scan is kept; no files changed.")
        self._set_next_step(
            "New OpenClaude session started. Enter one task, then run In-App Claude."
        )

    def _handle_agent_result(self, result):
        if self._agent_timeout_timer.isActive():
            self._agent_timeout_timer.stop()
        self.latest_prompt_package = result.prompt_package
        self.latest_system_prompt = result.system_prompt
        self.context_output.setPlainText(
            result.system_prompt + "\n\n---\n\n" + result.prompt_package
        )
        if self._agent_render_timer.isActive():
            self._agent_render_timer.stop()
            self._flush_agent_stream_markdown()

        self._remember_agent_conversation(result)

        if result.patch_proposal is not None:
            self.latest_proposal = result.patch_proposal
            self.latest_changed_paths = result.patch_proposal.target_files
            self._patch_previewed = False
            self._patch_applied = False
            header = [
                "# Agent Patch Proposal",
                f"Risk: {result.patch_proposal.risk_level.value}",
                "Changed files:",
                *(f"- {path}" for path in result.patch_proposal.target_files),
                "",
                "## Reason",
                result.patch_proposal.reason,
                "",
                "## Unified diff",
                result.patch_proposal.unified_diff,
            ]
            self.patch_output.setPlainText("\n".join(header))
            self._append_workspace_card(
                self._patch_card_markdown(
                    result.patch_proposal,
                    title="Agent Patch Proposal",
                )
            )
            self._select_advanced_widget(self.patch_output)
            self._log("Active model prepared a patch proposal. No files changed.")
            self._set_agent_status("Agent done · patch proposal ready")
            self._finish_agent_activity(
                "patch proposal ready",
                f"{result.patch_proposal.changed_file_count} changed file(s)",
            )
            self._set_progress(100, "patch proposal ready")
            self._set_workflow_stage(
                "patch_ready",
                "Step 4: review the inline patch proposal, then Preview Patch. You can ask a follow-up in the task box and click 3.",
            )
        else:
            if self._agent_render_timer.isActive():
                self._agent_render_timer.stop()
            final_markdown = str(
                self._agent_stream_markdown or result.final_text or ""
            ).strip()
            self._agent_stream_markdown = final_markdown
            self.agent_transcript_markdown = final_markdown
            self._set_markdown_output(self.plan_output, final_markdown)
            self._scroll_text_widget_to_end(self.plan_output)
            self._show_workspace()
            self._log("Active model returned plan/text. No files changed.")
            if self._agent_stop_requested:
                self._set_agent_status("Agent stopped")
                self._finish_agent_activity("stopped", "run was cancelled")
                self._set_progress(0, "agent stopped")
                self._set_workflow_stage(
                    "stopped",
                    "Continue the session: type your answer or next instruction in the task box, then run In-App Claude.",
                )
            else:
                self._set_agent_status("Agent done")
                self._finish_agent_activity("done", "visible answer ready")
                self._set_progress(100, "agent done")
                self._set_workflow_stage(
                    "answered",
                    "Continue the session: type your answer or next instruction in the task box, then run In-App Claude.",
                )
        self._set_agent_busy(False)

    def _clear_agent_worker(self, run_id: int | None = None):
        if run_id is not None and int(run_id) != int(getattr(self, "_agent_run_id", 0)):
            self._drop_retired_agent_run(int(run_id))
            return
        if self._agent_timeout_timer.isActive():
            self._agent_timeout_timer.stop()
        if self._agent_render_timer.isActive():
            self._agent_render_timer.stop()
            self._flush_agent_stream_markdown()
        if self._agent_activity_timer.isActive():
            self._agent_activity_timer.stop()
        self.agent_thread = None
        self.agent_worker = None
        self._set_agent_busy(False)

    def copy_system_prompt(self):
        if not self.latest_system_prompt:
            self.build_context_plan()
        if self.latest_system_prompt:
            QGuiApplication.clipboard().setText(self.latest_system_prompt)
            self._log("System prompt copied to clipboard.")

    def copy_context_package(self):
        if not self.latest_prompt_package:
            self.build_context_plan()
        if self.latest_prompt_package:
            QGuiApplication.clipboard().setText(self.latest_prompt_package)
            self._log("Context package copied to clipboard.")

    def _patch_preview_guidance(self) -> str:
        mode = self._selected_mode()
        safety = self._selected_safety_mode()
        if mode in {AgentMode.REVIEW_ONLY, AgentMode.PLAN_ONLY}:
            return (
                "# No Patch Proposal Yet\n\n"
                f"Current mode is **{mode.value}**, so Step 4 cannot preview a patch until one exists.\n\n"
                "What to do next:\n"
                "1. Keep this mode if you only want review/analysis.\n"
                "2. Switch **Mode** to **Patch Files** or **Patch + Run Tests** when you want a diff.\n"
                "3. Ask the agent: `Propose a safe patch for <issue>. Do not apply it yet.`\n"
                "4. After the workspace shows a unified diff, use **4 · Preview Patch**.\n\n"
                f"Safety is currently **{safety.value}**; file writes still require explicit approval."
            )
        return (
            "# No Patch Proposal Yet\n\n"
            "Step 4 previews an existing unified diff. No diff is available yet.\n\n"
            "What to do next:\n"
            "1. In the task box, ask: `Propose a safe patch for <issue>. Do not apply it yet.`\n"
            "2. Click **Run** and wait for OpenClaude output.\n"
            "3. Review the generated diff in the workspace.\n"
            "4. Click **4 · Preview Patch** to validate paths and risk before applying."
        )

    def _render_patch_preview(self, proposal: PatchProposal) -> None:
        header = [
            "# Patch Proposal",
            f"Risk: {proposal.risk_level.value}",
            "Changed files:",
            *(f"- {path}" for path in proposal.target_files),
            "",
            "## Unified diff",
            proposal.unified_diff,
        ]
        self.patch_output.setPlainText("\n".join(header))
        self._append_workspace_card(
            self._patch_card_markdown(proposal, title="Patch Preview Ready")
        )
        self._select_advanced_widget(self.patch_output)

    def preview_patch(self):
        self._refresh_root()
        self._set_progress(20, "previewing patch")
        QApplication.processEvents()
        diff = self.patch_output.toPlainText().strip()
        if self.latest_proposal is not None and (
            not diff
            or diff == self.latest_proposal.unified_diff.strip()
            or not (
                diff.startswith("diff --git")
                or diff.startswith("--- a/")
                or diff.startswith("--- /dev/null")
            )
        ):
            preflight = preflight_patch_with_git(
                self.project_root, self.latest_proposal.unified_diff
            )
            if not preflight.ok:
                self._patch_previewed = False
                self._set_progress(0, "patch preflight failed")
                guidance = "\n".join(
                    [
                        "# Patch Diff Rejected",
                        "",
                        preflight.message,
                        "",
                        "Ask the agent to regenerate the same patch as a valid unified diff before applying.",
                    ]
                )
                self._append_workspace_card(guidance)
                self.patch_output.setPlainText(
                    guidance + "\n\n" + self.latest_proposal.unified_diff
                )
                self._select_advanced_widget(self.patch_output)
                self._log("Patch preflight failed: " + preflight.message)
                self._set_workflow_stage(
                    "patch_ready",
                    "Patch diff is malformed or stale. Ask OpenClaude to regenerate a valid unified diff.",
                )
                return
            self._render_patch_preview(self.latest_proposal)
            self._patch_previewed = True
            self._set_progress(100, "patch preview ready")
            self._set_workflow_stage(
                "previewed",
                "Step 5: if the diff is correct and safety mode allows edits, click Apply Patch.",
            )
            return
        if not diff:
            guidance = self._patch_preview_guidance()
            self.patch_output.setPlainText(guidance)
            self._append_workspace_card(guidance)
            self._select_advanced_widget(self.patch_output)
            self._log(
                "Patch preview unavailable: no unified diff has been generated or pasted."
            )
            self._set_progress(0, "no patch to preview")
            self._set_next_step(
                "No patch exists yet. Ask OpenClaude to propose a patch first, or stay in Review Only for analysis."
            )
            return
        try:
            proposal = make_patch_proposal(
                diff,
                reason=self.request_edit.toPlainText().strip()
                or "manual patch proposal",
                suggested_tests=("Compile Only", "Feature Tests"),
            )
        except (PatchPathError, ValueError) as exc:
            self._set_progress(0, "patch rejected")
            QMessageBox.critical(self, "Patch rejected", str(exc))
            self._log(f"Patch rejected: {exc}")
            return
        preflight = preflight_patch_with_git(self.project_root, proposal.unified_diff)
        if not preflight.ok:
            self._patch_previewed = False
            self._set_progress(0, "patch preflight failed")
            guidance = "\n".join(
                [
                    "# Patch Diff Rejected",
                    "",
                    preflight.message,
                    "",
                    "Ask the agent to regenerate the same patch as a valid unified diff before applying.",
                ]
            )
            self._append_workspace_card(guidance)
            self.patch_output.setPlainText(guidance + "\n\n" + proposal.unified_diff)
            self._select_advanced_widget(self.patch_output)
            self._log("Patch preflight failed: " + preflight.message)
            self._set_workflow_stage(
                "patch_ready",
                "Patch diff is malformed or stale. Ask OpenClaude to regenerate a valid unified diff.",
            )
            return
        self.latest_proposal = proposal
        self.latest_changed_paths = proposal.target_files
        self._render_patch_preview(proposal)
        self._log(
            f"Patch preview accepted for {proposal.changed_file_count} file(s). No files changed."
        )
        self._patch_previewed = True
        self._set_progress(100, "patch preview ready")
        self._set_workflow_stage(
            "previewed",
            "Step 5: if the diff is correct and safety mode allows edits, click Apply Patch.",
        )

    def apply_patch(self):
        self._refresh_root()
        self._set_progress(20, "applying patch")
        QApplication.processEvents()
        if self._selected_safety_mode() == SafetyMode.READ_ONLY:
            self._set_progress(0, "apply blocked")
            QMessageBox.warning(
                self,
                "Read-only safety mode",
                "Switch safety mode away from Read-only before applying a patch.",
            )
            return
        if self.latest_proposal is None:
            self.preview_patch()
        if self.latest_proposal is None:
            return
        preflight = preflight_patch_with_git(
            self.project_root, self.latest_proposal.unified_diff
        )
        if not preflight.ok:
            self._patch_previewed = False
            self._set_progress(0, "patch preflight failed")
            details = preflight.message
            if (
                preflight.stderr
                and preflight.stderr.strip()
                and preflight.stderr.strip() not in details
            ):
                details += "\n\nDetails:\n" + preflight.stderr.strip()
            QMessageBox.warning(self, "Patch preflight failed", details)
            self._append_workspace_card(
                "# Patch Diff Rejected\n\n"
                + details
                + "\n\nAsk the agent to regenerate a valid unified diff before applying."
            )
            return
        answer = QMessageBox.question(
            self,
            "Apply approved patch?",
            "Apply this unified diff inside the selected project root? A rollback snapshot will be created first.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._log("Patch apply cancelled by user.")
            self._set_progress(0, "apply cancelled")
            return
        result = apply_patch_proposal(
            self.project_root,
            self.latest_proposal,
            approved=True,
            label="developer_agent",
        )
        self._log(result.message)
        if result.applied_paths:
            self._log("Applied path(s): " + ", ".join(result.applied_paths))
        if result.skipped_paths:
            self._log(
                "Already-applied path(s) skipped: " + ", ".join(result.skipped_paths)
            )
        if result.failed_paths:
            self._log("Failed path(s): " + ", ".join(result.failed_paths))
        if result.stdout:
            self._log(result.stdout)
        if result.stderr:
            self._log(result.stderr)
        if result.ok:
            if result.applied_paths:
                self._log("Patch applied. Run Compile next for Python changes.")
                self._patch_applied = True
                self._set_progress(100, "patch applied")
                self._set_workflow_stage(
                    "applied", "Step 6: run Compile, then Fast/Feature tests as needed."
                )
            else:
                self._log(
                    "Patch was already applied. Run Compile if you need validation."
                )
                self._patch_applied = True
                self._set_progress(100, "patch already applied")
                self._set_workflow_stage(
                    "applied",
                    "Patch was already applied; Step 6 can validate the current project state.",
                )
        else:
            self._set_progress(0, "patch not applied")
            details = result.message
            if (
                result.stderr
                and result.stderr.strip()
                and result.stderr.strip() not in details
            ):
                details = details + "\n\nDetails:\n" + result.stderr.strip()
            QMessageBox.warning(self, "Patch not applied", details)

    def export_patch(self):
        if self.latest_proposal is None:
            self.preview_patch()
        if self.latest_proposal is None:
            return
        try:
            paths = save_patch_exports(
                self.project_root,
                self.latest_proposal,
                label="developer_agent_export",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._log("Patch export saved:")
        for label, path in paths.items():
            self._log(f"- {label}: {path}")

    def _record_validation_result(self, result, profile) -> None:
        self.latest_checks.append(
            f"{result.command_text} -> {'PASS' if result.ok else 'FAIL'} ({result.returncode})"
        )
        formatted = self._format_check_result(result)
        self.test_output.appendPlainText(formatted)
        status = "PASS" if result.ok else "FAIL"
        validation_card = "\n".join(
            [
                "# Validation Result",
                "",
                f"**Status:** {status}",
                f"**Profile:** {profile.name} — {profile.reason}",
                f"**Project:** `{self.project_root}`",
                f"**Command:** `{result.command_text}`",
                f"**Return code:** {result.returncode}",
                f"**Elapsed:** {result.elapsed_seconds}s",
                "",
                f"**Summary:** {result.failure_summary().headline}",
                "",
                "Detailed output was captured in the internal validation buffer and summarized here.",
            ]
        )
        self._append_workspace_card(validation_card)
        self._log(self.latest_checks[-1])

    def _validation_presets_for_click(
        self, preset: ValidationPreset, profile
    ) -> tuple[ValidationPreset, ...]:
        if preset == ValidationPreset.COMPILE_ONLY and profile.kind != "fzastro":
            return (ValidationPreset.COMPILE_ONLY, ValidationPreset.FULL_PYTEST)
        return (preset,)

    def run_validation(self, preset: ValidationPreset):
        self._refresh_root()
        profile = detect_validation_profile(self.project_root)
        presets = self._validation_presets_for_click(preset, profile)
        self._set_progress(None, f"running {preset.value}")
        self._append_workspace_card(
            "\n".join(
                [
                    "# Validation Started",
                    "",
                    f"**Profile:** {profile.name}",
                    f"**Project:** `{self.project_root}`",
                    f"**Preset:** {preset.value}",
                    f"**Commands:** {', '.join(item.value for item in presets)}",
                    "",
                    "OpenClaude selected safe validation command(s) for this project automatically.",
                ]
            )
        )
        QApplication.processEvents()
        results = []
        for selected_preset in presets:
            try:
                result = run_validation_preset(
                    self.project_root,
                    selected_preset,
                    changed_paths=self.latest_changed_paths,
                    approved=False,
                )
            except Exception as exc:
                self._set_progress(0, "validation blocked")
                self._append_workspace_card(
                    "\n".join(
                        [
                            "# Validation Blocked",
                            "",
                            f"**Profile:** {profile.name}",
                            f"**Project:** `{self.project_root}`",
                            f"**Preset:** {selected_preset.value}",
                            "",
                            str(exc),
                        ]
                    )
                )
                self._log(f"Validation blocked: {exc}")
                return
            results.append(result)
            self._record_validation_result(result, profile)
            if not result.ok:
                break
        self._select_advanced_widget(self.test_output)
        all_ok = bool(results) and all(result.ok for result in results)
        self._set_progress(
            100 if all_ok else 0,
            "validation passed" if all_ok else "validation failed",
        )
        self._set_workflow_stage(
            "validated",
            "Step 7: build the final report, or ask for a follow-up patch if validation failed.",
        )

    def build_final_report(self):
        self._set_progress(20, "building final report")
        QApplication.processEvents()
        profile = detect_validation_profile(self.project_root)
        python_changed = any(path.endswith(".py") for path in self.latest_changed_paths)
        exe_rebuild_required = profile.kind == "fzastro" and python_changed
        task_text = (
            self._agent_active_request or self.request_edit.toPlainText().strip()
        )
        lines = [
            "# OpenClaude Final Report",
            "",
            "## Task",
            task_text or "(no task text)",
            "",
            "## Changed files",
        ]
        if self.latest_changed_paths:
            lines.extend(f"- `{path}`" for path in self.latest_changed_paths)
        else:
            lines.append("- None applied or previewed.")
        lines.extend(
            [
                "",
                "## Validation commands",
                *(f"- {item}" for item in self.latest_checks),
                "",
                "## Project profile",
                f"{profile.name} — {profile.reason}",
                "",
                "## Active runtime",
                self._runtime_summary(),
                "",
                "## Known limitations",
                "- Agent generation is wired for inspect/plan/patch proposal. Apply, Build EXE, Release Validation, and unsafe commands remain approval-gated.",
                "- OpenClaude uses the main app runtime and does not auto-start Ollama.",
                "",
                "## EXE rebuild required",
                (
                    "Yes"
                    if exe_rebuild_required
                    else (
                        "No — selected project is not the FZAstro application repo."
                        if profile.kind != "fzastro"
                        else "No Python changes detected from current patch preview."
                    )
                ),
            ]
        )
        report = "\n".join(lines)
        self._set_markdown_output(self.final_output, report)
        self._append_workspace_card(report)
        self._select_advanced_widget(self.final_output)
        self._log("Final report generated from visible state.")
        self._set_progress(100, "report ready")
        self._set_workflow_stage(
            "reported",
            "Workflow complete. Review Report and exported patch/ZIP if needed.",
        )

    def _format_check_result(self, result) -> str:
        status = "PASS" if result.ok else "FAIL"
        output = result.combined_output.strip() or "(no output)"
        summary = result.failure_summary()
        return (
            f"[{status}] {result.command_text}\n"
            f"Return code: {result.returncode} · elapsed: {result.elapsed_seconds}s\n"
            f"Summary: {summary.headline}\n"
            f"Files: {', '.join(summary.files) or 'n/a'}\n\n"
            f"{output}\n\n"
        )


def open_dev_workbench_dialog(parent=None):
    if parent is not None and hasattr(parent, "open_workspace_tab"):

        def _clear_reference(_widget=None):
            try:
                if getattr(parent, "dev_workbench_dialog", None) is _widget:
                    setattr(parent, "dev_workbench_dialog", None)
            except Exception:
                pass

        def _create_dev_tab():
            dialog = DevWorkbenchDialog(parent)
            dialog.app_window = parent
            setattr(parent, "dev_workbench_dialog", dialog)
            try:
                dialog.destroyed.connect(lambda *_args: _clear_reference(dialog))
            except Exception:
                pass
            return dialog

        return parent.open_workspace_tab(
            "dev.agent",
            "OpenClaude",
            _create_dev_tab,
            tooltip="FZAstro AI OpenClaude",
            on_close=_clear_reference,
        )

    dialog = DevWorkbenchDialog(parent)
    dialog.show()
    if parent is not None:
        setattr(parent, "dev_workbench_dialog", dialog)
    return dialog

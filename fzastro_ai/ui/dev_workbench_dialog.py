from __future__ import annotations

from pathlib import Path
from typing import Any
import threading
import time

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
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
    QProgressBar,
    QScrollArea,
    QTextBrowser,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import API_KEY, BASE_URL, DEFAULT_MODEL_NAME
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


class _DevAgentWorker(QObject):
    """Run the Developer Agent loop away from the Qt UI thread."""

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
                    "The active FZAstro model endpoint is not reachable. Developer Agent Mode did not auto-start Ollama.",
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
    """Step-based FZAstro AI Developer Agent cockpit.

    The dialog is intentionally preview-first: it scans, prepares context, asks
    the active app model to inspect/plan/propose patches, applies only after
    visible approval, and records real validation output.
    """

    def __init__(self, parent=None, project_root: Path | str | None = None):
        super().__init__(parent, Qt.Window)
        self.app_window = self._find_runtime_owner(parent)
        self.setWindowTitle("FZAstro AI Developer Agent Mode")
        self.resize(1360, 860)
        self.setMinimumSize(1040, 700)
        apply_window_defaults(self)

        self.project_root = self._initial_project_root(project_root)
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
        self._agent_run_id = 0
        self._retired_agent_runs: list[tuple[int, QThread, _DevAgentWorker]] = []
        self._agent_stop_requested = False
        # Developer Agent runs should behave like local coding-agent sessions:
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
        self._log("Developer Agent Mode ready. Start at Step 1: scan the project.")
        self._set_next_step(
            "Step 1: enter a task, then click Scan Project. After an answer, use the same box as your reply field."
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
            self._log(f"Could not save Developer Agent project root: {exc}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(8)

        title = QLabel("Developer Agent Mode")
        title.setObjectName("settingsCardTitle")
        root_layout.addWidget(title)

        subtitle = QLabel(
            "Step-based coding workflow: scan -> plan -> ask/reply with the active model -> review patch -> apply -> validate -> report. Nothing edits files until you approve a patch."
        )
        subtitle.setObjectName("settingsCardSubtitle")
        subtitle.setWordWrap(True)
        root_layout.addWidget(subtitle)

        config_box = QFrame()
        config_box.setObjectName("settingsCard")
        config_layout = QVBoxLayout(config_box)
        config_layout.setContentsMargins(12, 10, 12, 10)
        config_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Project:"))
        self.root_input = QLineEdit(str(self.project_root))
        self.root_input.setMinimumWidth(320)
        top_row.addWidget(self.root_input, 3)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_root)
        top_row.addWidget(browse_button)
        top_row.addSpacing(8)
        top_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in AgentMode])
        self.mode_combo.setMinimumWidth(145)
        self.mode_combo.currentTextChanged.connect(
            lambda *_: self._on_mode_or_safety_changed()
        )
        top_row.addWidget(self.mode_combo)
        top_row.addSpacing(8)
        top_row.addWidget(QLabel("Safety:"))
        self.safety_combo = QComboBox()
        self.safety_combo.addItems([mode.value for mode in SafetyMode])
        self.safety_combo.setCurrentText(SafetyMode.ASK_BEFORE_EDITING.value)
        self.safety_combo.setMinimumWidth(210)
        self.safety_combo.currentTextChanged.connect(
            lambda *_: self._on_mode_or_safety_changed()
        )
        top_row.addWidget(self.safety_combo)
        top_row.addStretch(1)
        config_layout.addLayout(top_row)

        # Runtime/model details are owned by the main FZAstro top bar. DEV keeps
        # them out of the normal and advanced UI so diagnostics stay focused on
        # the selected project, tools, patch, and validation results.
        self.runtime_status_label = QLabel("")
        self.runtime_status_label.setVisible(False)
        self.runtime_status_label.setObjectName("sidebarFooter")
        self.runtime_status_label.setWordWrap(True)

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
        config_layout.addLayout(telemetry_row)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress_label = QLabel("Progress: idle")
        self.progress_label.setObjectName("settingsCardSubtitle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_row.addWidget(self.progress_label)
        progress_row.addWidget(self.progress_bar, 1)
        config_layout.addLayout(progress_row)

        self.mode_help_label = QLabel("")
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

        # The task/reply composer lives in the Agent Workspace so the top
        # control panel stays compact and the flow feels like the main chat.
        self.request_edit = QPlainTextEdit()
        self.request_edit.setPlaceholderText(
            "Describe the task, or reply to the agent here. The DEV agent will plan, propose, preview, apply, and validate from this project."
        )
        self.request_edit.setFixedHeight(78)

        # Steering/guidance is now internal prompt context. The normal UI keeps a
        # single composer so users do not have to decide between task text and a
        # separate steering prompt. These hidden controls keep older queued-note
        # plumbing safe without exposing it as a second input.
        self.steering_input = QLineEdit()
        self.steering_input.setVisible(False)
        self.steer_button = QPushButton("Steer Next Step")
        self.steer_button.setVisible(False)
        self.steer_button.clicked.connect(self.add_agent_steering)

        workflow_row = QHBoxLayout()
        self.scan_button = QPushButton("1 · Scan Project")
        self.scan_button.clicked.connect(self.scan_project)
        self.plan_button = QPushButton("2 · Build Plan")
        self.plan_button.clicked.connect(self.build_context_plan)
        self.local_agent_button = QPushButton("3 · Ask / Reply")
        self.local_agent_button.clicked.connect(self.run_local_agent)
        self.stop_agent_button = QPushButton("Stop Agent")
        self.stop_agent_button.clicked.connect(self.stop_agent)
        self.stop_agent_button.setEnabled(False)
        self.preview_patch_button = QPushButton("4 · Preview Patch")
        self.preview_patch_button.clicked.connect(self.preview_patch)
        self.apply_patch_button = QPushButton("5 · Apply Patch")
        self.apply_patch_button.clicked.connect(self.apply_patch)
        self.compile_button = QPushButton("6 · Compile")
        self.compile_button.clicked.connect(
            lambda: self.run_validation(ValidationPreset.COMPILE_ONLY)
        )
        self.final_report_button = QPushButton("7 · Final Report")
        self.final_report_button.clicked.connect(self.build_final_report)

        for button in (
            self.scan_button,
            self.plan_button,
            self.local_agent_button,
            self.stop_agent_button,
            self.preview_patch_button,
            self.apply_patch_button,
            self.compile_button,
            self.final_report_button,
        ):
            button.setCursor(Qt.PointingHandCursor)
            workflow_row.addWidget(button)
        workflow_row.addStretch(1)
        config_layout.addLayout(workflow_row)

        utility_row = QHBoxLayout()
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
        self.copy_prompt_button = QPushButton("Copy Prompt")
        self.copy_prompt_button.clicked.connect(self.copy_system_prompt)
        self.copy_context_button = QPushButton("Copy Context")
        self.copy_context_button.clicked.connect(self.copy_context_package)
        self.export_patch_button = QPushButton("Save Patch ZIP")
        self.export_patch_button.clicked.connect(self.export_patch)
        self.reset_chat_button = QPushButton("New Chat")
        self.reset_chat_button.clicked.connect(self.reset_agent_chat)
        for button in (
            self.fast_tests_button,
            self.feature_tests_button,
            self.full_pytest_button,
            self.copy_prompt_button,
            self.copy_context_button,
            self.export_patch_button,
            self.reset_chat_button,
        ):
            button.setCursor(Qt.PointingHandCursor)
            utility_row.addWidget(button)
        utility_row.addStretch(1)
        config_layout.addLayout(utility_row)

        self.workflow_buttons = (
            self.scan_button,
            self.plan_button,
            self.local_agent_button,
            self.stop_agent_button,
            self.preview_patch_button,
            self.apply_patch_button,
            self.compile_button,
            self.final_report_button,
        )
        self.utility_buttons = (
            self.fast_tests_button,
            self.feature_tests_button,
            self.full_pytest_button,
            self.copy_prompt_button,
            self.copy_context_button,
            self.export_patch_button,
            self.reset_chat_button,
        )
        self._button_base_labels = {
            button: button.text()
            for button in (*self.workflow_buttons, *self.utility_buttons)
        }

        self.next_step_label = QLabel("")
        self.next_step_label.setObjectName("settingsCardSubtitle")
        self.next_step_label.setWordWrap(True)
        config_layout.addWidget(self.next_step_label)

        root_layout.addWidget(config_box)

        workspace_box = QFrame()
        workspace_box.setObjectName("settingsCard")
        workspace_layout = QVBoxLayout(workspace_box)
        workspace_layout.setContentsMargins(12, 10, 12, 10)
        workspace_layout.setSpacing(8)
        root_layout.addWidget(workspace_box, 1)

        workspace_header = QHBoxLayout()
        workspace_title = QLabel("Agent Workspace")
        workspace_title.setObjectName("settingsCardTitle")
        workspace_header.addWidget(workspace_title)
        workspace_header.addStretch(1)
        self.evidence_toggle_button = QPushButton("Evidence · minimized")
        self.evidence_toggle_button.setCursor(Qt.PointingHandCursor)
        self.evidence_toggle_button.clicked.connect(self.toggle_evidence_panel)
        workspace_header.addWidget(self.evidence_toggle_button)
        self.advanced_toggle_button = QPushButton("Advanced Diagnostics ▸")
        self.advanced_toggle_button.setCursor(Qt.PointingHandCursor)
        self.advanced_toggle_button.clicked.connect(self.toggle_advanced_panel)
        workspace_header.addWidget(self.advanced_toggle_button)
        workspace_layout.addLayout(workspace_header)

        workspace_hint = QLabel(
            "One-flow agent timeline. Plans, evidence summaries, patch proposals, previews, validation, and reports appear here; technical trace panels stay minimized unless needed."
        )
        workspace_hint.setObjectName("settingsCardSubtitle")
        workspace_hint.setWordWrap(True)
        workspace_layout.addWidget(workspace_hint)

        self.agent_activity_label = QLabel(
            "Activity: idle. Tool and model activity appears here while a run is active; private reasoning is not shown."
        )
        self.agent_activity_label.setObjectName("sidebarFooter")
        self.agent_activity_label.setWordWrap(True)
        workspace_layout.addWidget(self.agent_activity_label)

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(8)
        workspace_layout.addWidget(self.workspace_splitter, 1)

        workspace_main_widget = QWidget()
        workspace_main = QVBoxLayout(workspace_main_widget)
        workspace_main.setContentsMargins(0, 0, 0, 0)
        workspace_main.setSpacing(8)
        self.workspace_splitter.addWidget(workspace_main_widget)

        self.plan_output = QTextBrowser()
        self.plan_output.setReadOnly(True)
        self.plan_output.setOpenExternalLinks(True)
        self.plan_output.setPlaceholderText(
            "Agent timeline appears here. Start with Scan Project, Build Plan, then Ask / Reply."
        )
        workspace_main.addWidget(self.plan_output, 1)

        composer_frame = QFrame()
        composer_frame.setObjectName("settingsCard")
        composer_layout = QVBoxLayout(composer_frame)
        composer_layout.setContentsMargins(10, 8, 10, 8)
        composer_layout.setSpacing(6)
        composer_label = QLabel("Task / reply")
        composer_label.setObjectName("settingsCardSubtitle")
        composer_layout.addWidget(composer_label)
        composer_layout.addWidget(self.request_edit)
        composer_hint = QLabel(
            "Type once, then use the numbered workflow buttons. Follow-ups go in the same box after the agent answers."
        )
        composer_hint.setObjectName("sidebarFooter")
        composer_hint.setWordWrap(True)
        composer_layout.addWidget(composer_hint)
        workspace_main.addWidget(composer_frame)

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
        evidence_title = QLabel("Evidence / Files")
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
        advanced_title = QLabel("Advanced Diagnostics")
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

        footer = QLabel(
            "Hard boundary: no hidden edits, no fake test claims, no dangerous commands, and no hardware or N.I.N.A. sequence actions from this mode."
        )
        footer.setObjectName("sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        root_layout.addWidget(footer)
        self._update_mode_help()

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

    def _main_app_runtime_config(self) -> RuntimeAgentConfig:
        return RuntimeAgentConfig(
            model=self._model_from_runtime_owner(),
            base_url=str(
                self._call_runtime(
                    "current_base_url", self.base_url_input.text().strip() or BASE_URL
                )
            ),
            api_key=str(self._call_runtime("current_api_key", API_KEY)),
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

    def _update_runtime_status(self):
        try:
            self.runtime_status_label.setText(self._runtime_summary())
        except Exception as exc:
            self.runtime_status_label.setText(f"Runtime unavailable ({exc})")

    def refresh_telemetry_from_app(self):
        """Mirror main-window telemetry in the Developer Agent cockpit.

        The DEV panel should not start another telemetry worker. It only copies
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

    def _set_progress(self, value: int | None, text: str):
        """Update the Developer Agent progress bar.

        Use ``value=None`` for indeterminate work such as a streaming model
        request where token count and tool-loop length are not known ahead of
        time.
        """

        try:
            self.progress_label.setText(f"Progress: {text}")
            if value is None:
                self.progress_bar.setRange(0, 0)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(max(0, min(100, int(value))))
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

        The visible run button may be pressed before Build Plan, or after the
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
            f"Current behavior: {mode}. Safety: {safety}. The model may inspect and propose; file writes still require patch preview and approval."
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
        evidence_label = (
            f"Evidence · {count} files" if count else "Evidence · minimized"
        )
        if self._drawer_mode == "evidence":
            self.evidence_toggle_button.setText(f"{evidence_label} ◂")
        else:
            self.evidence_toggle_button.setText(f"{evidence_label} ▸")
        self.advanced_toggle_button.setText(
            "Advanced Diagnostics ◂"
            if self._drawer_mode == "advanced"
            else "Advanced Diagnostics ▸"
        )

    def _open_workspace_drawer(self, mode: str):
        mode = "advanced" if mode == "advanced" else "evidence"
        if getattr(self, "_drawer_mode", "") and self.drawer_frame.isVisible():
            self._drawer_width = self._current_drawer_width()
        self._drawer_mode = mode
        self.evidence_panel.setVisible(mode == "evidence")
        self.advanced_panel.setVisible(mode == "advanced")
        self.drawer_title_label.setText(
            "Evidence / Files" if mode == "evidence" else "Advanced Diagnostics"
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
            self.plan_output.setFocus()
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
            or "# Developer Agent Workspace"
        ).rstrip()
        self._agent_stream_markdown = (
            current + "\n\n---\n\n" + str(markdown or "").strip() + "\n"
        )
        self.agent_transcript_markdown = self._agent_stream_markdown.rstrip()
        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._scroll_text_widget_to_end(self.plan_output)
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
                "Private reasoning is not shown; DEV shows tool/model activity only."
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
        request_ready = bool(self.request_edit.toPlainText().strip())

        if busy:
            next_button = self.stop_agent_button
        elif not has_scan:
            next_button = self.scan_button
        elif request_ready and not has_context:
            next_button = self.plan_button
        elif request_ready and not has_patch:
            next_button = self.local_agent_button
        elif has_patch and not self._patch_previewed:
            next_button = self.preview_patch_button
        elif self._patch_previewed and not self._patch_applied:
            next_button = self.apply_patch_button
        elif self._patch_applied and not has_validation:
            next_button = self.compile_button
        elif has_validation:
            next_button = self.final_report_button
        else:
            next_button = self.scan_button

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
            self.local_agent_button.setText("3 · Streaming...")
        else:
            enabled[self.stop_agent_button] = False
            self.stop_agent_button.setText("Stop Agent")
            self.local_agent_button.setText(
                self._button_base_labels.get(self.local_agent_button, "3 · Ask / Reply")
            )
            enabled[self.local_agent_button] = request_ready
            enabled[self.plan_button] = request_ready
            # Step 4 stays clickable to show inline guidance when a diff does
            # not exist yet; Step 5 remains locked until preview succeeds.
            enabled[self.preview_patch_button] = True
            enabled[self.apply_patch_button] = bool(
                self._patch_previewed
                and self.latest_proposal is not None
                and self._selected_safety_mode() != SafetyMode.READ_ONLY
            )
            enabled[self.compile_button] = True
            enabled[self.final_report_button] = bool(
                has_context
                or has_patch
                or has_validation
                or self.agent_transcript_markdown.strip()
            )

        tooltips = {
            self.scan_button: "Scan the selected project root and refresh the file index.",
            self.plan_button: "Build an evidence-ranked context plan for the current task.",
            self.local_agent_button: "Ask the active model to inspect, answer, or propose a patch from the current context.",
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
            elif button is self.local_agent_button and not request_ready and not busy:
                suffix = " (needs task)"
                blocked = True
            label = base + suffix
            if button is next_button and enabled.get(button, False):
                label = "NEXT · " + base + suffix
            button.setText(label)
            button.setEnabled(bool(enabled.get(button, True)))
            button.setToolTip(tooltips.get(button, ""))
            self._style_action_button(
                button,
                is_next=(button is next_button and enabled.get(button, False)),
                is_blocked=blocked or not enabled.get(button, True),
            )

    def _log(self, text: str):
        self.action_log.appendPlainText(text.rstrip() + "\n")

    def _set_markdown_output(self, widget, markdown: str):
        """Render markdown where supported, with a plain-text fallback.

        The Developer Agent prompt asks models to return structured markdown.
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
            "3. For local Ollama, start Ollama from the main toolbar first; Developer Agent Mode will not auto-start it.",
            "4. Then click `3 · Ask / Reply` again.",
        ]
        self._agent_stream_markdown = "\n".join(lines)
        self._set_markdown_output(self.plan_output, self._agent_stream_markdown)
        self._show_workspace()
        self._log(f"{title}: {message}")
        self._set_next_step(
            "Fix the active model/runtime selection, then run Step 3 again."
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
            self._set_next_step("Step 1: scan the selected project.")

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
                "**Next:** enter or refine the task in the composer, then click `2 · Build Plan`.",
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
            "Step 2: enter a task if needed, then click Build Plan to choose focused files or build a broad audit index.",
        )

    def build_context_plan(self):
        self._refresh_root()
        self._set_progress(15, "building context")
        QApplication.processEvents()
        request = self.request_edit.toPlainText().strip()
        if not request:
            self._reset_progress_idle()
            QMessageBox.information(
                self, "Task needed", "Enter a Developer Agent task first."
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
        self._log("Built Developer Agent context and visible plan. No files changed.")
        self._set_progress(100, "context ready")
        self._set_workflow_stage(
            "planned",
            "Step 3: click Ask / Reply. If the agent asks a question, type the answer in the task box and click 3 again.",
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
                self, "Task needed", "Enter a Developer Agent task first."
            )
            return
        if self.agent_thread is not None:
            QMessageBox.information(
                self,
                "Agent already running",
                "Wait for the current Developer Agent request to finish before starting another one.",
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
            self._log("Using Developer Agent steering guidance for this turn.")

        self._agent_active_request = request
        self.request_edit.clear()
        self._agent_stop_requested = False
        self._agent_is_followup = bool(self.agent_conversation_messages)
        conversation_messages = None
        if self._agent_is_followup:
            conversation_messages = list(self.agent_conversation_messages)
            followup_content = "Developer Agent follow-up from the user:\n" + request
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
                    "# Developer Agent Chat\n\n## You\n" + request + "\n\n## Agent\n"
                )
            self._log("Continuing existing Developer Agent conversation.")
        else:
            self._agent_stream_markdown = (
                "# Developer Agent Chat\n\n" "## You\n" + request + "\n\n## Agent\n"
            )
            self._log("Starting new Developer Agent conversation.")

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
            self._log(f"Queued Developer Agent steering: {note}")
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
            self._log(f"Saved Developer Agent steering for next Ask/Reply: {note}")
            self._set_next_step(
                "Internal guidance saved. Click 3 · Ask / Reply to apply it to the next agent turn."
            )
        self.steering_input.clear()

    def _start_agent_timeout_timer_if_configured(self):
        """Start the optional hard-run timeout only when explicitly configured.

        Local coding-agent jobs can legitimately spend several minutes in
        evidence review or patch generation. By default FZAstro no longer uses
        a wall-clock kill timer for Developer Agent runs; Stop Agent is the
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
            "Stopped by user. You can revise the task and click 3 · Ask / Reply to start a fresh run.",
        )
        self._log(
            "Developer Agent stopped by user; retired worker output will be ignored."
        )

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
        self._log("Developer Agent optional timeout reached; stop requested.")

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
                "Wait for the current Developer Agent request to finish before starting a new chat.",
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
        self._log("Developer Agent chat reset. Context scan is kept; no files changed.")
        self._set_next_step(
            "New chat started. Enter a task, then click 2 Build Plan or 3 Ask / Reply."
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
                    "Continue the chat: type your answer or next instruction in the task box, then click 3 · Ask / Reply.",
                )
            else:
                self._set_agent_status("Agent done")
                self._finish_agent_activity("done", "visible answer ready")
                self._set_progress(100, "agent done")
                self._set_workflow_stage(
                    "answered",
                    "Continue the chat: type your answer or next instruction in the task box, then click 3 · Ask / Reply.",
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
            "2. Click **3 · Ask / Reply** and wait for a patch proposal.\n"
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
                    "Patch diff is malformed or stale. Ask Step 3 to regenerate a valid unified diff.",
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
                "No patch exists yet. Ask Step 3 to propose a patch first, or stay in Review Only for analysis."
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
                "Patch diff is malformed or stale. Ask Step 3 to regenerate a valid unified diff.",
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
                "Detailed output is available under **Advanced Diagnostics -> Validation**.",
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
                    "DEV selected safe validation command(s) for this project automatically.",
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
            "# Developer Agent Final Report",
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
                "- Developer Agent Mode uses the main app runtime and does not auto-start Ollama.",
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
            "DEV",
            _create_dev_tab,
            tooltip="FZAstro AI Developer Agent Mode",
            on_close=_clear_reference,
        )

    dialog = DevWorkbenchDialog(parent)
    dialog.show()
    if parent is not None:
        setattr(parent, "dev_workbench_dialog", dialog)
    return dialog

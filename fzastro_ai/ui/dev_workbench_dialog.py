from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..dev_agent import DevAgentSession
from ..dev_agent.test_runner import run_compileall, run_pytest
from .window_utils import apply_window_defaults


def _project_root_from_package() -> Path:
    return Path(__file__).resolve().parents[2]


class DevWorkbenchDialog(QWidget):
    """Developer-workbench preview UI.

    This first-stage workbench builds the same kind of focused coding context a
    careful ChatGPT-style coding assistant needs: project scan, relevant files,
    visible plan, and test/check output.  It intentionally does not auto-edit
    files; patch generation and safe apply are separate backend capabilities.
    """

    def __init__(self, parent=None, project_root: Path | str | None = None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("FZAstro AI Developer Workbench")
        self.resize(1180, 780)
        self.setMinimumSize(900, 620)
        apply_window_defaults(self)

        self.project_root = Path(project_root or _project_root_from_package()).resolve()
        self.session = DevAgentSession(self.project_root)
        self.latest_prompt_package = ""
        self.latest_plan = ""

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        title = QLabel("AI Developer Workbench")
        title.setObjectName("settingsCardTitle")
        root_layout.addWidget(title)

        subtitle = QLabel(
            "Scan the project, select relevant files, create a visible coding plan, "
            "and run compile/test checks before applying patches."
        )
        subtitle.setObjectName("settingsCardSubtitle")
        subtitle.setWordWrap(True)
        root_layout.addWidget(subtitle)

        root_row = QHBoxLayout()
        root_row.addWidget(QLabel("Project root:"))
        self.root_input = QLineEdit(str(self.project_root))
        root_row.addWidget(self.root_input, 1)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_root)
        root_row.addWidget(browse_button)
        root_layout.addLayout(root_row)

        request_box = QFrame()
        request_box.setObjectName("settingsCard")
        request_layout = QVBoxLayout(request_box)
        request_layout.setContentsMargins(12, 12, 12, 12)
        request_layout.setSpacing(8)
        request_layout.addWidget(QLabel("Developer request:"))
        self.request_edit = QPlainTextEdit()
        self.request_edit.setPlaceholderText(
            "Example: Fix the SEEING planner scoring bug and update tests."
        )
        self.request_edit.setFixedHeight(90)
        request_layout.addWidget(self.request_edit)

        button_row = QHBoxLayout()
        self.scan_button = QPushButton("Scan Project")
        self.scan_button.clicked.connect(self.scan_project)
        self.context_button = QPushButton("Build Context + Plan")
        self.context_button.clicked.connect(self.build_context_plan)
        self.copy_context_button = QPushButton("Copy Context Package")
        self.copy_context_button.clicked.connect(self.copy_context_package)
        self.copy_plan_button = QPushButton("Copy Plan")
        self.copy_plan_button.clicked.connect(self.copy_plan)
        self.compile_button = QPushButton("Run Compile Check")
        self.compile_button.clicked.connect(self.run_compile_check)
        self.pytest_button = QPushButton("Run Pytest")
        self.pytest_button.clicked.connect(self.run_pytest_check)

        for button in (
            self.scan_button,
            self.context_button,
            self.copy_context_button,
            self.copy_plan_button,
            self.compile_button,
            self.pytest_button,
        ):
            button.setCursor(Qt.PointingHandCursor)
            button_row.addWidget(button)

        button_row.addStretch(1)
        request_layout.addLayout(button_row)
        root_layout.addWidget(request_box)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(QLabel("Selected files:"))
        self.file_list = QListWidget()
        left_layout.addWidget(self.file_list, 1)
        self.summary_label = QLabel("No project scan yet.")
        self.summary_label.setWordWrap(True)
        left_layout.addWidget(self.summary_label)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.plan_output = QPlainTextEdit()
        self.plan_output.setReadOnly(True)
        self.context_output = QPlainTextEdit()
        self.context_output.setReadOnly(True)
        self.check_output = QPlainTextEdit()
        self.check_output.setReadOnly(True)
        self.tabs.addTab(self.plan_output, "Plan")
        self.tabs.addTab(self.context_output, "Context Package")
        self.tabs.addTab(self.check_output, "Checks")
        splitter.addWidget(self.tabs)
        splitter.setSizes([360, 800])

        footer = QLabel(
            "Stage 1 is preview-first: it prepares code context and validation. "
            "Patch apply should remain reviewable and backed up."
        )
        footer.setObjectName("sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(footer)

    def _refresh_root(self):
        self.project_root = Path(self.root_input.text().strip()).expanduser().resolve()
        self.session = DevAgentSession(self.project_root)

    def browse_root(self):
        selected = QFileDialog.getExistingDirectory(
            self, "Choose FZAstro AI project root", str(self.project_root)
        )
        if selected:
            self.root_input.setText(selected)
            self._refresh_root()

    def scan_project(self):
        self._refresh_root()
        try:
            scan = self.session.refresh_scan()
        except Exception as exc:
            QMessageBox.critical(self, "Scan failed", str(exc))
            return
        self.summary_label.setText(
            f"Scanned {scan.file_count} files · {scan.python_count} Python · "
            f"{scan.test_count} tests · ignored {scan.ignored_count}."
        )
        self.file_list.clear()
        for file in scan.files[:250]:
            item = QListWidgetItem(f"{file.path}  [{file.role}]")
            item.setToolTip(
                f"{file.size} bytes\nSymbols: {', '.join(file.symbols[:12]) or 'none'}"
            )
            self.file_list.addItem(item)

    def build_context_plan(self):
        self._refresh_root()
        request = self.request_edit.toPlainText().strip()
        if not request:
            QMessageBox.information(
                self, "Developer request needed", "Enter a coding request first."
            )
            return
        try:
            result = self.session.prepare(request)
        except Exception as exc:
            QMessageBox.critical(self, "Context build failed", str(exc))
            return

        self.latest_prompt_package = result.context.prompt_package
        self.latest_plan = result.plan_markdown
        self.plan_output.setPlainText(result.plan_markdown)
        self.context_output.setPlainText(result.context.prompt_package)
        self.summary_label.setText(result.context.summary.replace("\n", " · "))
        self.file_list.clear()
        for file in result.context.files:
            item = QListWidgetItem(f"{file.path}  score={file.score:g}  [{file.role}]")
            item.setToolTip(file.reason)
            self.file_list.addItem(item)
        self.tabs.setCurrentWidget(self.plan_output)

    def copy_context_package(self):
        if not self.latest_prompt_package:
            self.build_context_plan()
        if self.latest_prompt_package:
            QGuiApplication.clipboard().setText(self.latest_prompt_package)
            self.check_output.appendPlainText("Context package copied to clipboard.\n")

    def copy_plan(self):
        if not self.latest_plan:
            self.build_context_plan()
        if self.latest_plan:
            QGuiApplication.clipboard().setText(self.latest_plan)
            self.check_output.appendPlainText("Plan copied to clipboard.\n")

    def run_compile_check(self):
        self._refresh_root()
        self.check_output.appendPlainText("Running compileall...\n")
        result = run_compileall(self.project_root)
        self.check_output.appendPlainText(self._format_check_result(result))
        self.tabs.setCurrentWidget(self.check_output)

    def run_pytest_check(self):
        self._refresh_root()
        self.check_output.appendPlainText("Running pytest -q...\n")
        result = run_pytest(self.project_root)
        self.check_output.appendPlainText(self._format_check_result(result))
        self.tabs.setCurrentWidget(self.check_output)

    def _format_check_result(self, result) -> str:
        status = "PASS" if result.ok else "FAIL"
        output = result.combined_output.strip() or "(no output)"
        summary = result.failure_summary()
        return (
            f"[{status}] {' '.join(result.command)}\n"
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
            setattr(parent, "dev_workbench_dialog", dialog)
            try:
                dialog.destroyed.connect(lambda *_args: _clear_reference(dialog))
            except Exception:
                pass
            return dialog

        return parent.open_workspace_tab(
            "dev.workbench",
            "DEV",
            _create_dev_tab,
            tooltip="AI Developer Workbench",
            on_close=_clear_reference,
        )

    dialog = DevWorkbenchDialog(parent)
    dialog.show()
    # Keep the window alive when opened from a transient local variable.
    if parent is not None:
        setattr(parent, "dev_workbench_dialog", dialog)
    return dialog

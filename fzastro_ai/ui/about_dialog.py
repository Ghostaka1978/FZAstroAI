from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..config import (
    APP_DIR,
    APP_MILESTONE,
    APP_NAME,
    APP_VERSION,
    APP_VERSION_LABEL,
    LOG_FILE,
)
from ..logging_utils import log_exception
from .window_utils import apply_window_defaults


def open_about_window(parent):
    """Open a compact app/version/about dialog."""
    try:
        if parent is not None and hasattr(parent, "focus_workspace_tab"):
            if parent.focus_workspace_tab("system.about"):
                return None

        dialog = QDialog(parent)
        apply_window_defaults(dialog)
        dialog.setObjectName("helpDialog")
        dialog.setWindowTitle(f"About {APP_NAME}")
        dialog.resize(980, 700)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(APP_VERSION_LABEL)
        title.setObjectName("helpDialogTitle")

        subtitle = QLabel(
            "Imaging Production local AI workstation for chat, documents, web "
            "research, Python execution, memory, LLM benchmarking, the Astro Tools "
            "Suite, FZAstro Imaging/N.I.N.A. planning, Web Companion, and Developer Agent Mode."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)

        details = QTextBrowser()
        details.setObjectName("helpCheatSheetBrowser")
        details.setOpenExternalLinks(False)
        details.setReadOnly(True)
        details.setPlainText(
            f"""FZAstro AI
Version: {APP_VERSION}
Release: {APP_MILESTONE}

Imaging Production scope:
- Version 2.3 tabbed workspace: Chat, LOOKUP, SEEING, SUN NOW, N.I.N.A., TARGETS, Help/About, and system panels open as main-window tabs
- Workspace Apps launcher keeps astronomy and system tools available from every tab
- Root deploy button: DEPLOY.bat runs validation and local Git release commit/tag automation
- Optional deploy push: DEPLOY.bat -GitPush pushes the current branch and release tag
- Local AI workstation built around Ollama/OpenAI-compatible chat
- Clean project layout with application modules under fzastro_ai/
- Consolidated docs under docs/ with one primary root README.md
- Document Knowledge Library for PDFs, text, code, and Excel files
- Exact PDF page text retrieval and real PDF page/image rendering
- Optional OCR support for scanned documents
- Web search, Daily News, market, gold, and crude-oil actions with provider-timeout hardening
- Web Companion for local/LAN/iPad browser access
- Integrated Astro Tools Suite: SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP
- FZAstro Imaging / N.I.N.A. bundle launcher with quiet build/deploy support
- Safe `/nina-plan` and `/imaging-plan` commands for review-only target planning
- Real N.I.N.A. Advanced Sequencer JSON generation from SITE, IMAGING, SEEING, and TARGETS context
- Plan exports under Documents/FZAstroAI/Imaging Plans with Markdown, JSON, XML, CSV, and review metadata
- Auto-launch/open handoff for generated sequences without slewing, guiding, capture, or sequence execution
- SEEING Astro Night Planner with cloud-aware scoring, astronomical-dark prioritization, Moon periods, and Bortle-aware top-bar tint
- LOOKUP distance-ladder details for parallax, Gaia proxy, NED-D, and Hubble estimates where available
- Optional distance-ladder calculation visibility via FZASTRO_USE_DISTANCE_LADDER=1
- Developer Agent Mode for project scanning, focused coding context, safety modes, patch preview/apply, compile/pytest presets, and final engineering reports
- LLM Benchmark Dashboard with telemetry, Run All Presets, Delete Selected, history, compare, and persona/calibration controls
- Source tags that identify whether answers come from local knowledge, web, files, Python, memory, app actions, or model reasoning
- Persistent memory with review/search tools
- Python code-block Run support through a real local Python interpreter
- Repeatable EXE build tooling and release validation for Windows builds

Runtime storage:
App data: {APP_DIR}
Log file: {LOG_FILE}

External runtime notes:
- Ollama or another OpenAI-compatible endpoint must be available for local chat.
- Set FZASTRO_AUTO_START_OLLAMA=0 to disable default local Ollama auto-start.
- Set FZASTRO_STOP_OLLAMA_ON_EXIT=1 to stop only the app-started Ollama process on exit.
- Set FZASTRO_PYTHON when using the EXE Python runner.
- Set FZASTRO_APP_DIR to override the runtime data folder for testing or portable runs.
- Tesseract OCR is optional and only required for OCR/scanned-page workflows.
- Playwright browser files are optional and only required for browser-backed web capture.
"""
        )

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        open_app_dir_button = QPushButton("Open App Data")
        open_log_button = QPushButton("Open Log")
        close_button = QPushButton("Close")
        close_button.setObjectName("primaryActionButton")

        open_app_dir_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR)))
        )
        open_log_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))
        )
        close_button.clicked.connect(dialog.accept)
        if parent is not None and hasattr(parent, "open_workspace_tab"):
            close_button.setVisible(False)

        button_row.addStretch(1)
        button_row.addWidget(open_app_dir_button)
        button_row.addWidget(open_log_button)
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(details, 1)
        layout.addLayout(button_row)

        if parent is not None and hasattr(parent, "open_workspace_tab"):
            return parent.open_workspace_tab(
                "system.about",
                "ABOUT",
                lambda: dialog,
                tooltip="Version and release information",
            )

        dialog.exec()
    except Exception as exc:
        log_exception("open_about_window", exc)

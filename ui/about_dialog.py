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


def open_about_window(parent):
    """Open a compact app/version/about dialog."""
    try:
        dialog = QDialog(parent)
        dialog.setObjectName("helpDialog")
        dialog.setWindowTitle(f"About {APP_NAME}")
        dialog.resize(720, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(APP_VERSION_LABEL)
        title.setObjectName("helpDialogTitle")

        subtitle = QLabel(
            "Version 1 local AI workstation for chat, documents, web research, Python execution, memory, and astrophotography workflows, including transparent LOOKUP distance estimates."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)

        details = QTextBrowser()
        details.setObjectName("helpCheatSheetBrowser")
        details.setOpenExternalLinks(False)
        details.setReadOnly(True)
        details.setPlainText(
            "FZAstro AI\n"
            f"Version: {APP_VERSION}\n"
            f"Release: {APP_MILESTONE}\n\n"
            "Version 1 release-candidate 2 scope:\n"
            "- Local AI workstation built around Ollama/OpenAI-compatible chat\n"
            "- Modular PySide6 desktop interface\n"
            "- Document Knowledge Library for PDFs, text, code, and Excel files\n"
            "- Exact PDF page text retrieval when requested\n"
            "- Real PDF page/image rendering when the user asks for visuals\n"
            "- Optional OCR support for scanned documents\n"
            "- Web search, Daily News, market, gold, and crude-oil actions\n"
            "- Integrated FZASTRO tools: SITE, IMAGING, LOOKUP, SEEING, TARGETS, and SOLAR MAP\n"
            "- LOOKUP distance-ladder details for parallax, Gaia proxy, NED-D, and Hubble-law style estimates where available\n"
            "- Optional distance-ladder calculation visibility via FZASTRO_USE_DISTANCE_LADDER=1\n"
            "- Source tags that identify whether answers come from local knowledge, web, files, Python, or model reasoning\n"
            "- Persistent memory with review/search tools\n"
            "- Calibration profiles and model/profile controls\n"
            "- Bottom-row hardware telemetry for GPU/VRAM, CPU and RAM, with best-effort temperatures\n"
            "- Skills, Knowledge, Code Lab, Model Lab, Context, and Persona menus for common app workflows\n"
            "- Clear Library compacts document_knowledge.sqlite3 after removing document assets\n"
            "- Python code-block Run support through a real local Python interpreter\n"
            "- Repeatable EXE build tooling for Windows release builds\n"
            "- Starter automated test suite for routing, memory, documentation, and version checks\n\n"
            "Runtime storage:\n"
            f"App data: {APP_DIR}\n"
            f"Log file: {LOG_FILE}\n\n"
            "External runtime notes:\n"
            "- Ollama or another OpenAI-compatible endpoint must be available for local chat.\n"
            "- Installed local Ollama can be auto-started for the default local endpoint; set FZASTRO_AUTO_START_OLLAMA=0 to disable.\n- Auto-started Ollama is left running by default; set FZASTRO_STOP_OLLAMA_ON_EXIT=1 to stop only the app-started process.\n"
            "- Set FZASTRO_PYTHON when using the EXE Python runner.\n"
            "- Set FZASTRO_APP_DIR to override the runtime data folder for testing or portable runs.\n"
            "- Tesseract OCR is optional and only required for OCR/scanned-page workflows.\n"
            "- Playwright browser files are optional and only required for browser-backed web capture.\n"
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

        button_row.addStretch(1)
        button_row.addWidget(open_app_dir_button)
        button_row.addWidget(open_log_button)
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(details, 1)
        layout.addLayout(button_row)

        dialog.exec()
    except Exception as exc:
        log_exception("open_about_window", exc)

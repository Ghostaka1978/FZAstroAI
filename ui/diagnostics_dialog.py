import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..config import (
    APP_DIR,
    APP_VERSION_LABEL,
    CALIBRATION_PROFILES_FILE,
    HISTORY_FILE,
    KNOWLEDGE_ASSET_DIR,
    KNOWLEDGE_DB_FILE,
    LOG_DIR,
    LOG_FILE,
    MEMORY_FILE,
)
from ..logging_utils import log_exception
from ..runtime import BASE_URL, is_ollama_base_url


def format_path_for_diagnostics(path_value):
    """Return a readable path line with an existence flag."""
    try:
        path = Path(path_value)
        exists_text = "yes" if path.exists() else "no"
        return f"{path}  (exists: {exists_text})"
    except Exception as exc:
        log_exception("format_path_for_diagnostics", exc)
        return str(path_value)


def read_recent_log_lines(max_lines=80):
    """Read the tail of the app log for the diagnostics window."""
    try:
        if not LOG_FILE.exists():
            return "Log file has not been created yet."

        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max(1, int(max_lines)) :]
        return "\n".join(tail).strip() or "Log file is empty."
    except Exception as exc:
        log_exception("read_recent_log_lines", exc)
        return f"Could not read log file: {exc}"


def open_local_path(parent, path_value):
    """Open a file or folder with the operating system default handler."""
    try:
        path = Path(path_value)

        if path == LOG_FILE:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            LOG_FILE.touch(exist_ok=True)

        if not path.exists():
            QMessageBox.warning(
                parent, "Path not found", f"This path does not exist:\n{path}"
            )
            return

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        if not opened:
            QMessageBox.warning(parent, "Open failed", f"Could not open:\n{path}")
    except Exception as exc:
        log_exception("open_local_path", exc)
        QMessageBox.warning(parent, "Open failed", f"Could not open path:\n{exc}")


def build_diagnostics_report(parent):
    """Build a copyable runtime diagnostics report for support/debugging."""
    try:
        base_url = (
            parent.current_base_url() if hasattr(parent, "server_url") else BASE_URL
        )
        api_provider = (
            "Ollama" if is_ollama_base_url(base_url) else "OpenAI-compatible API"
        )
        active_model = (
            parent.current_model_name()
            if hasattr(parent, "model_box")
            else "Unavailable"
        )
        web_mode = (
            parent.web_box.currentText().strip()
            if hasattr(parent, "web_box")
            else "Unavailable"
        )
        runtime_base = getattr(sys, "_MEIPASS", os.path.abspath("."))
        pyinstaller_mode = "yes" if getattr(sys, "frozen", False) else "no"
        fzastro_python = os.environ.get("FZASTRO_PYTHON", "not set")

        optional_modules = {
            "PyMuPDF / fitz": getattr(parent, "fitz", None) is not None,
            "Pillow / PIL": getattr(parent, "Image", None) is not None,
            "pytesseract": getattr(parent, "pytesseract", None) is not None,
        }

        # Fall back to imported module globals when the parent does not expose them.
        try:
            import fitz as _fitz  # noqa: F401

            optional_modules["PyMuPDF / fitz"] = True
        except Exception:
            optional_modules["PyMuPDF / fitz"] = optional_modules["PyMuPDF / fitz"]

        try:
            from PIL import Image as _Image  # noqa: F401

            optional_modules["Pillow / PIL"] = True
        except Exception:
            optional_modules["Pillow / PIL"] = optional_modules["Pillow / PIL"]

        try:
            import pytesseract as _pytesseract  # noqa: F401

            optional_modules["pytesseract"] = True
        except Exception:
            optional_modules["pytesseract"] = optional_modules["pytesseract"]

        module_lines = [
            f"{name}: {'available' if available else 'not available'}"
            for name, available in optional_modules.items()
        ]

        lines = [
            "FZASTRO AI DIAGNOSTICS",
            APP_VERSION_LABEL,
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "Runtime",
            f"Python executable: {sys.executable}",
            f"FZASTRO_PYTHON: {fzastro_python}",
            f"PyInstaller bundle: {pyinstaller_mode}",
            f"Resource base: {runtime_base}",
            "",
            "Model / API",
            f"Active model: {active_model}",
            f"Web mode: {web_mode}",
            f"API provider: {api_provider}",
            f"Base URL: {base_url}",
            "",
            "Storage",
            f"App dir: {format_path_for_diagnostics(APP_DIR)}",
            f"Log file: {format_path_for_diagnostics(LOG_FILE)}",
            f"History file: {format_path_for_diagnostics(HISTORY_FILE)}",
            f"Memory file: {format_path_for_diagnostics(MEMORY_FILE)}",
            f"Calibration profiles: {format_path_for_diagnostics(CALIBRATION_PROFILES_FILE)}",
            f"Knowledge DB: {format_path_for_diagnostics(KNOWLEDGE_DB_FILE)}",
            f"Knowledge assets: {format_path_for_diagnostics(KNOWLEDGE_ASSET_DIR)}",
            "",
            "Optional modules",
            *module_lines,
            "",
            "Recent log tail",
            read_recent_log_lines(max_lines=80),
        ]

        return "\n".join(lines)
    except Exception as exc:
        log_exception("build_diagnostics_report", exc)
        return f"Diagnostics failed: {exc}"


def open_diagnostics_window(parent):
    """Open runtime diagnostics and log access."""
    dialog = QDialog(parent)
    dialog.setObjectName("helpDialog")
    dialog.setWindowTitle("FZAstro AI Diagnostics")
    dialog.resize(980, 760)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("FZAstro AI Diagnostics")
    title.setObjectName("helpDialogTitle")

    subtitle = QLabel(
        "Runtime paths, model/API settings, optional dependencies, and the latest app log entries."
    )
    subtitle.setObjectName("helpDialogSubtitle")
    subtitle.setWordWrap(True)

    diagnostics_view = QTextBrowser()
    diagnostics_view.setObjectName("helpCheatSheetBrowser")
    diagnostics_view.setOpenExternalLinks(False)
    diagnostics_view.setReadOnly(True)
    diagnostics_view.setPlainText(build_diagnostics_report(parent))

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 0, 0, 0)
    button_row.setSpacing(8)

    refresh_button = QPushButton("Refresh")
    refresh_button.setToolTip("Reload diagnostics and latest log entries")

    copy_button = QPushButton("Copy Diagnostics")
    copy_button.setObjectName("primaryActionButton")
    copy_button.setToolTip("Copy the full diagnostics report")

    open_log_button = QPushButton("Open Log")
    open_log_button.setToolTip("Open fzastroai.log")

    open_log_folder_button = QPushButton("Open Log Folder")
    open_log_folder_button.setToolTip("Open the logs folder")

    clear_log_button = QPushButton("Clear Log")
    clear_log_button.setToolTip("Clear fzastroai.log and refresh diagnostics")

    close_button = QPushButton("Close")
    close_button.setToolTip("Close diagnostics")

    def refresh_report():
        diagnostics_view.setPlainText(build_diagnostics_report(parent))

    def copy_report():
        QApplication.clipboard().setText(diagnostics_view.toPlainText())
        copy_button.setText("Copied")
        QTimer.singleShot(1600, lambda: copy_button.setText("Copy Diagnostics"))

    def clear_log():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text("", encoding="utf-8")
            refresh_report()
        except Exception as exc:
            log_exception("diagnostics_clear_log", exc)
            QMessageBox.warning(
                parent, "Clear log failed", f"Could not clear log:\n{exc}"
            )

    refresh_button.clicked.connect(refresh_report)
    copy_button.clicked.connect(copy_report)
    open_log_button.clicked.connect(lambda: open_local_path(parent, LOG_FILE))
    open_log_folder_button.clicked.connect(lambda: open_local_path(parent, LOG_DIR))
    clear_log_button.clicked.connect(clear_log)
    close_button.clicked.connect(dialog.accept)

    button_row.addWidget(refresh_button)
    button_row.addStretch(1)
    button_row.addWidget(copy_button)
    button_row.addWidget(open_log_button)
    button_row.addWidget(open_log_folder_button)
    button_row.addWidget(clear_log_button)
    button_row.addWidget(close_button)

    layout.addWidget(title)
    layout.addWidget(subtitle)
    layout.addWidget(diagnostics_view, 1)
    layout.addLayout(button_row)

    dialog.exec()

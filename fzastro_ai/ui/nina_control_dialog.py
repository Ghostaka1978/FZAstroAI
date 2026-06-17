from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QInputDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..nina.imaging_plan import IMAGING_PLAN_DIR
from ..nina.nina_bridge import (
    NinaUpdateInfo,
    bundle_root,
    check_for_update,
    download_update,
    find_default_executable,
    is_process_running,
    latest_sequence_file,
    launch_executable,
    launch_sequence_file,
    load_settings,
    project_root,
    save_settings,
)
from .window_utils import apply_window_defaults


class NinaControlDialog(QWidget):
    """First-stage launcher and updater for the bundled N.I.N.A. app.

    The bundled imaging app is intentionally treated as a separate executable.
    FZAstro AI launches it, stores the path, checks an update feed, and downloads
    updates for review.  It never overwrites a running equipment-control app.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("FZASTRO IMAGING CONTROL")
        self.resize(860, 640)
        self.setMinimumSize(740, 520)
        apply_window_defaults(self)

        self.settings = load_settings()
        self.latest_update: NinaUpdateInfo | None = None
        self._build_ui()
        self._load_settings_into_ui()
        QTimer.singleShot(0, self.refresh_status)
        if self.auto_check_updates_checkbox.isChecked():
            QTimer.singleShot(900, self.check_for_updates_silent)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        title = QLabel("FZASTRO IMAGING CONTROL")
        title.setObjectName("settingsCardTitle")
        root_layout.addWidget(title)

        subtitle = QLabel(
            "Safe review bridge for the bundled FZAstro Imaging/N.I.N.A. app. Create "
            "Advanced Sequencer plans from SITE, IMAGING, SEEING, and TARGETS, then "
            "launch/open them for review without starting hardware actions."
        )
        subtitle.setObjectName("settingsCardSubtitle")
        subtitle.setWordWrap(True)
        root_layout.addWidget(subtitle)

        safety_banner = QLabel(
            "SAFE REVIEW ONLY · NO SLEW · NO GUIDING START · NO CAPTURE START · NO SEQUENCE EXECUTION"
        )
        safety_banner.setObjectName("sidebarFooter")
        safety_banner.setAlignment(Qt.AlignCenter)
        safety_banner.setWordWrap(True)
        root_layout.addWidget(safety_banner)

        launcher_card = self._card("Launcher")
        launcher_layout = QGridLayout(launcher_card)
        launcher_layout.setContentsMargins(12, 12, 12, 12)
        launcher_layout.setHorizontalSpacing(8)
        launcher_layout.setVerticalSpacing(8)

        launcher_header = QLabel("LAUNCHER")
        launcher_header.setObjectName("settingsCardTitle")
        launcher_layout.addWidget(launcher_header, 0, 0, 1, 7)

        launcher_layout.addWidget(QLabel("Executable:"), 1, 0)
        self.executable_input = QLineEdit()
        self.executable_input.setPlaceholderText(
            "bundled_apps/FZAstroImaging/FZAstroImaging.exe"
        )
        self.executable_input.editingFinished.connect(self.save_from_ui)
        launcher_layout.addWidget(self.executable_input, 1, 1, 1, 4)

        self.browse_executable_button = QPushButton("BROWSE")
        self.browse_executable_button.clicked.connect(self.browse_executable)
        launcher_layout.addWidget(self.browse_executable_button, 1, 5)

        self.find_executable_button = QPushButton("FIND BUNDLE")
        self.find_executable_button.clicked.connect(self.find_executable)
        launcher_layout.addWidget(self.find_executable_button, 1, 6)

        launcher_layout.addWidget(QLabel("API host:"), 2, 0)
        self.api_host_input = QLineEdit()
        self.api_host_input.setPlaceholderText("127.0.0.1")
        self.api_host_input.editingFinished.connect(self.save_from_ui)
        launcher_layout.addWidget(self.api_host_input, 2, 1)

        launcher_layout.addWidget(QLabel("API port:"), 2, 2)
        self.api_port_input = QSpinBox()
        self.api_port_input.setRange(1, 65535)
        self.api_port_input.setValue(1888)
        self.api_port_input.valueChanged.connect(self.save_from_ui)
        launcher_layout.addWidget(self.api_port_input, 2, 3)

        self.status_label = QLabel("Status: not checked")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("webArticleBody")
        launcher_layout.addWidget(self.status_label, 2, 4, 1, 3)

        launcher_actions = QHBoxLayout()
        launcher_actions.setContentsMargins(0, 0, 0, 0)
        launcher_actions.setSpacing(7)
        self.launch_button = QPushButton("LAUNCH FZASTRO IMAGING")
        self.launch_button.setObjectName("primaryActionButton")
        self.launch_button.clicked.connect(self.launch_imaging_app)
        self.refresh_status_button = QPushButton("REFRESH STATUS")
        self.refresh_status_button.clicked.connect(self.refresh_status)
        self.open_bundle_folder_button = QPushButton("OPEN BUNDLE FOLDER")
        self.open_bundle_folder_button.clicked.connect(self.open_bundle_folder)
        self.open_build_guide_button = QPushButton("BUILD GUIDE")
        self.open_build_guide_button.clicked.connect(self.open_build_guide)
        launcher_actions.addWidget(self.launch_button)
        launcher_actions.addWidget(self.refresh_status_button)
        launcher_actions.addWidget(self.open_bundle_folder_button)
        launcher_actions.addWidget(self.open_build_guide_button)
        launcher_actions.addStretch(1)
        launcher_layout.addLayout(launcher_actions, 3, 0, 1, 7)

        root_layout.addWidget(launcher_card)

        planning_card = self._card("Planning")
        planning_layout = QGridLayout(planning_card)
        planning_layout.setContentsMargins(12, 12, 12, 12)
        planning_layout.setHorizontalSpacing(8)
        planning_layout.setVerticalSpacing(8)

        planning_header = QLabel("SAFE IMAGING PLANS")
        planning_header.setObjectName("settingsCardTitle")
        planning_layout.addWidget(planning_header, 0, 0, 1, 5)

        planning_intro = QLabel(
            "Create safe review-only FZAstro Imaging/N.I.N.A. plans from your current "
            "SITE, IMAGING, SEEING, and TARGETS context. Plans now include a real "
            "Advanced Sequencer JSON file plus XML/CSV review helpers. These buttons do "
            "not slew, guide, capture, schedule, or start a sequence."
        )
        planning_intro.setObjectName("webArticleBody")
        planning_intro.setWordWrap(True)
        planning_layout.addWidget(planning_intro, 1, 0, 1, 5)

        self.plan_folder_label = QLabel(f"Plans folder: {IMAGING_PLAN_DIR}")
        self.plan_folder_label.setObjectName("sidebarFooter")
        self.plan_folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        planning_layout.addWidget(self.plan_folder_label, 2, 0, 1, 5)

        self.plan_next_target_button = QPushButton("PLAN NEXT TARGET")
        self.plan_next_target_button.setObjectName("primaryActionButton")
        self.plan_next_target_button.setToolTip(
            "Create a safe review-only plan for the next best practical target. Does not control hardware."
        )
        self.plan_next_target_button.clicked.connect(self.plan_next_target)

        self.plan_specific_target_button = QPushButton("PLAN SPECIFIC TARGET")
        self.plan_specific_target_button.setToolTip(
            "Choose a target name and create a safe review-only imaging plan."
        )
        self.plan_specific_target_button.clicked.connect(self.plan_specific_target)

        self.open_latest_sequence_button = QPushButton("OPEN LATEST PLAN IN IMAGING")
        self.open_latest_sequence_button.setToolTip(
            "Launch FZAstro Imaging and attempt to open the newest generated .nina-sequence.json file. Does not start the sequence."
        )
        self.open_latest_sequence_button.clicked.connect(
            self.open_latest_sequence_in_imaging
        )

        self.open_plans_folder_button = QPushButton("OPEN PLANS FOLDER")
        self.open_plans_folder_button.setToolTip(
            "Open generated Markdown, Advanced Sequencer JSON, XML, CSV, and review metadata files."
        )
        self.open_plans_folder_button.clicked.connect(self.open_plans_folder)

        self.plan_help_button = QPushButton("COMMAND HELP")
        self.plan_help_button.setToolTip(
            "Show supported safe imaging-plan text commands."
        )
        self.plan_help_button.clicked.connect(self.show_planning_help)

        planning_layout.addWidget(self.plan_next_target_button, 3, 0)
        planning_layout.addWidget(self.plan_specific_target_button, 3, 1)
        planning_layout.addWidget(self.open_latest_sequence_button, 3, 2)
        planning_layout.addWidget(self.open_plans_folder_button, 3, 3)
        planning_layout.addWidget(self.plan_help_button, 3, 4)

        root_layout.addWidget(planning_card)

        updater_card = self._card("Updates")
        updater_layout = QGridLayout(updater_card)
        updater_layout.setContentsMargins(12, 12, 12, 12)
        updater_layout.setHorizontalSpacing(8)
        updater_layout.setVerticalSpacing(8)

        updates_header = QLabel("UPDATES")
        updates_header.setObjectName("settingsCardTitle")
        updater_layout.addWidget(updates_header, 0, 0, 1, 5)

        updater_layout.addWidget(QLabel("Installed version:"), 1, 0)
        self.installed_version_input = QLineEdit()
        self.installed_version_input.setPlaceholderText("Optional, example: 3.2.1")
        self.installed_version_input.editingFinished.connect(self.save_from_ui)
        updater_layout.addWidget(self.installed_version_input, 1, 1)

        updater_layout.addWidget(QLabel("Update feed:"), 2, 0)
        self.update_url_input = QLineEdit()
        self.update_url_input.setPlaceholderText(
            "Manifest JSON or GitHub latest-release API URL for your FZAstro Imaging build"
        )
        self.update_url_input.editingFinished.connect(self.save_from_ui)
        updater_layout.addWidget(self.update_url_input, 2, 1, 1, 4)

        self.auto_check_updates_checkbox = QCheckBox(
            "Check for updates when this panel opens"
        )
        self.auto_check_updates_checkbox.stateChanged.connect(self.save_from_ui)
        updater_layout.addWidget(self.auto_check_updates_checkbox, 3, 1, 1, 2)

        self.auto_download_updates_checkbox = QCheckBox(
            "Auto-download update package after confirmation"
        )
        self.auto_download_updates_checkbox.stateChanged.connect(self.save_from_ui)
        updater_layout.addWidget(self.auto_download_updates_checkbox, 3, 3, 1, 2)

        update_actions = QHBoxLayout()
        update_actions.setContentsMargins(0, 0, 0, 0)
        update_actions.setSpacing(7)
        self.check_update_button = QPushButton("CHECK FOR UPDATES")
        self.check_update_button.clicked.connect(self.check_for_updates)
        self.download_update_button = QPushButton("DOWNLOAD UPDATE")
        self.download_update_button.setEnabled(False)
        self.download_update_button.clicked.connect(self.download_latest_update)
        self.open_download_folder_button = QPushButton("OPEN DOWNLOADS")
        self.open_download_folder_button.clicked.connect(self.open_download_folder)
        update_actions.addWidget(self.check_update_button)
        update_actions.addWidget(self.download_update_button)
        update_actions.addWidget(self.open_download_folder_button)
        update_actions.addStretch(1)
        updater_layout.addLayout(update_actions, 4, 0, 1, 5)

        self.update_status_label = QLabel("Updates: no check yet")
        self.update_status_label.setObjectName("webArticleBody")
        self.update_status_label.setWordWrap(True)
        updater_layout.addWidget(self.update_status_label, 5, 0, 1, 5)

        root_layout.addWidget(updater_card)

        notes_card = self._card("Notes")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(12, 12, 12, 12)
        notes_layout.setSpacing(8)
        notes_header = QLabel("REVIEW NOTES")
        notes_header.setObjectName("settingsCardTitle")
        notes_layout.addWidget(notes_header)
        self.notes_output = QPlainTextEdit()
        self.notes_output.setReadOnly(True)
        self.notes_output.setPlaceholderText(
            "Update notes and integration status will appear here."
        )
        self.notes_output.setFixedHeight(150)
        notes_layout.addWidget(self.notes_output)
        root_layout.addWidget(notes_card, 1)

        footer = QLabel(
            "Safety rule: FZAstro AI may build, launch, open, and download for review, but it does not overwrite a running imaging app or start equipment-control actions automatically."
        )
        footer.setObjectName("sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        root_layout.addWidget(footer)

    def _card(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsCard")
        frame.setToolTip(title)
        return frame

    def _load_settings_into_ui(self):
        self.executable_input.setText(str(self.settings.get("executable_path") or ""))
        self.api_host_input.setText(str(self.settings.get("api_host") or "127.0.0.1"))
        self.api_port_input.setValue(int(self.settings.get("api_port") or 1888))
        self.installed_version_input.setText(
            str(self.settings.get("installed_version") or "")
        )
        self.update_url_input.setText(
            str(self.settings.get("update_manifest_url") or "")
        )
        self.auto_check_updates_checkbox.setChecked(
            bool(self.settings.get("auto_check_updates"))
        )
        self.auto_download_updates_checkbox.setChecked(
            bool(self.settings.get("auto_download_updates"))
        )

    def _settings_from_ui(self) -> dict:
        data = dict(self.settings)
        data.update(
            {
                "executable_path": self.executable_input.text().strip(),
                "api_host": self.api_host_input.text().strip() or "127.0.0.1",
                "api_port": int(self.api_port_input.value()),
                "installed_version": self.installed_version_input.text().strip(),
                "update_manifest_url": self.update_url_input.text().strip(),
                "auto_check_updates": self.auto_check_updates_checkbox.isChecked(),
                "auto_download_updates": self.auto_download_updates_checkbox.isChecked(),
            }
        )
        return data

    def save_from_ui(self):
        self.settings = save_settings(self._settings_from_ui())

    def browse_executable(self):
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose bundled FZAstro Imaging executable",
            str(Path(self.executable_input.text() or ".").expanduser()),
            "Executables (*.exe);;All files (*.*)",
        )
        if selected:
            self.executable_input.setText(selected)
            self.save_from_ui()
            self.refresh_status()

    def find_executable(self):
        found = find_default_executable(self._settings_from_ui())
        if found:
            self.executable_input.setText(found)
            self.save_from_ui()
            self.refresh_status()
            return
        QMessageBox.information(
            self,
            "Executable not found",
            "No bundled FZAstro Imaging executable was found yet. Build or copy FZAstroImaging.exe into bundled_apps/FZAstroImaging, then click Find Bundle again.",
        )

    def refresh_status(self):
        raw_path = self.executable_input.text().strip()
        path = (
            Path(raw_path).expanduser()
            if raw_path
            else bundle_root(self._settings_from_ui()) / "FZAstroImaging.exe"
        )
        exists = path.exists() and path.is_file()
        running = is_process_running()
        bundle_hint = "" if exists else f" · expected at {path}"
        self.status_label.setText(
            f"Status: {'running' if running else 'not running'} · bundle executable {'found' if exists else 'missing'}{bundle_hint}"
        )

    def launch_imaging_app(self):
        self.save_from_ui()
        executable = self.executable_input.text().strip() or str(
            bundle_root(self.settings) / "FZAstroImaging.exe"
        )
        try:
            launch_executable(executable)
        except Exception as exc:
            QMessageBox.critical(self, "Launch failed", str(exc))
            return
        self.status_label.setText("Status: launch requested")
        QTimer.singleShot(1200, self.refresh_status)

    def _main_window_parent(self):
        parent = self.parent()
        if parent is not None and hasattr(
            parent, "try_handle_predefined_imaging_plan_command"
        ):
            return parent
        return None

    def _run_imaging_plan_command(self, command: str):
        main_window = self._main_window_parent()
        if main_window is None:
            QMessageBox.information(
                self,
                "FZAstro Imaging plan",
                "Open this panel from the main FZAstro AI window to create plans from SITE/SEEING/TARGETS context.",
            )
            return
        main_window.try_handle_predefined_imaging_plan_command(command)
        self.notes_output.setPlainText(
            "Requested safe review-only imaging plan from chat context.\n\n"
            "No telescope movement, capture start, or N.I.N.A. sequence execution was requested.\n\n"
            "Advanced Sequencer JSON plus XML/CSV exports are saved in your Documents\\FZAstroAI\\Imaging Plans folder."
        )

    def plan_next_target(self):
        self._run_imaging_plan_command("/nina-plan next 60s gain 200")

    def plan_specific_target(self):
        target, accepted = QInputDialog.getText(
            self,
            "Plan Specific Target",
            "Target name, for example M13, NGC 7000, M31:",
        )
        if not accepted:
            return
        target = str(target or "").strip()
        if not target:
            QMessageBox.information(
                self, "Plan Specific Target", "Enter a target name first."
            )
            return
        exposure, accepted = QInputDialog.getInt(
            self,
            "Plan Specific Target",
            "Exposure seconds:",
            60,
            1,
            3600,
        )
        if not accepted:
            return
        gain, accepted = QInputDialog.getInt(
            self,
            "Plan Specific Target",
            "Gain:",
            200,
            0,
            10000,
        )
        if not accepted:
            return
        self._run_imaging_plan_command(
            f"/nina-plan target {target} exposure {int(exposure)}s gain {int(gain)}"
        )

    def open_latest_sequence_in_imaging(self):
        self.save_from_ui()
        sequence = latest_sequence_file(IMAGING_PLAN_DIR)
        if sequence is None:
            QMessageBox.information(
                self,
                "Open latest imaging plan",
                "No generated .nina-sequence.json file was found yet. Create a plan first.",
            )
            return
        try:
            result = launch_sequence_file(sequence, self.settings)
        except Exception as exc:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(sequence.parent)))
            QMessageBox.warning(
                self,
                "Open latest imaging plan",
                f"Could not launch/open the sequence automatically:\n\n{exc}\n\nThe plan folder was opened instead.",
            )
            return
        self.status_label.setText(
            "Status: launch/open requested for latest generated sequence"
        )
        self.notes_output.setPlainText(
            "Launch/open request sent for generated N.I.N.A. Advanced Sequencer file:\n\n"
            f"{result.sequence_path}\n\n"
            "Review the loaded sequence in FZAstro Imaging/N.I.N.A. before starting anything. "
            "No slew, guiding, capture, or sequence start was requested."
        )
        QTimer.singleShot(1200, self.refresh_status)

    def open_plans_folder(self):
        IMAGING_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(IMAGING_PLAN_DIR)))

    def show_planning_help(self):
        QMessageBox.information(
            self,
            "Safe imaging-plan commands",
            "Supported safe commands:\n\n"
            "- /nina-plan next\n"
            "- /nina-plan next 60s gain 200\n"
            "- /nina-plan target M13 60s gain 200\n"
            "- /imaging-plan target NGC 7000 exposure 120s gain 100 frames 80\n\n"
            "These commands create review-only Markdown, N.I.N.A. Advanced Sequencer JSON, XML, CSV, and metadata files in your Documents/FZAstroAI/Imaging Plans folder. FZAstro attempts to launch/open the generated sequence for review, but does not slew, guide, capture, schedule, or start N.I.N.A. sequences.",
        )

    def check_for_updates_silent(self):
        if not self.update_url_input.text().strip():
            self.update_status_label.setText(
                "Updates: auto-check is enabled, but no update feed is configured yet."
            )
            return
        self.check_for_updates(show_no_update=False)

    def check_for_updates(self, show_no_update: bool = True):
        self.save_from_ui()
        if not self.update_url_input.text().strip():
            QMessageBox.information(
                self,
                "Update feed needed",
                "Enter your FZAstro Imaging update manifest URL first. This can also be a GitHub latest-release API URL.",
            )
            return
        self.check_update_button.setEnabled(False)
        self.update_status_label.setText("Updates: checking…")
        try:
            info = check_for_update(self.settings)
        except Exception as exc:
            self.update_status_label.setText(f"Updates: check failed · {exc}")
            self.check_update_button.setEnabled(True)
            return
        self.latest_update = info
        self.check_update_button.setEnabled(True)
        self.download_update_button.setEnabled(bool(info and info.has_download))
        self._render_update_info(info, show_no_update=show_no_update)
        if (
            info
            and info.is_newer
            and info.has_download
            and self.auto_download_updates_checkbox.isChecked()
        ):
            answer = QMessageBox.question(
                self,
                "Download update?",
                f"Version {info.version} is available. Download the update package now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self.download_latest_update()

    def _render_update_info(
        self, info: NinaUpdateInfo | None, *, show_no_update: bool = True
    ):
        if info is None:
            self.update_status_label.setText("Updates: no update feed configured.")
            return
        if info.is_newer:
            status = f"Updates: version {info.version} is available"
        else:
            status = f"Updates: no newer version found ({info.version or 'unknown'})"
        if info.published_at:
            status += f" · published {info.published_at}"
        if not info.has_download:
            status += " · no downloadable asset found"
        self.update_status_label.setText(status)
        notes = [
            f"Source: {info.source_url}",
            f"Current: {info.current_version or 'unknown'}",
            f"Available: {info.version or 'unknown'}",
            f"Download: {info.download_url or 'n/a'}",
            "",
            info.release_notes or "No release notes returned by the update feed.",
        ]
        self.notes_output.setPlainText("\n".join(notes))
        if show_no_update and not info.is_newer:
            QMessageBox.information(
                self, "No newer update", self.update_status_label.text()
            )

    def download_latest_update(self):
        if self.latest_update is None:
            QMessageBox.information(
                self, "No update selected", "Check for updates first."
            )
            return
        if not self.latest_update.has_download:
            QMessageBox.information(
                self,
                "No download",
                "The update feed did not provide a downloadable asset.",
            )
            return
        self.download_update_button.setEnabled(False)
        self.update_status_label.setText("Updates: downloading package…")
        try:
            path = download_update(self.latest_update)
        except Exception as exc:
            self.update_status_label.setText(f"Updates: download failed · {exc}")
            self.download_update_button.setEnabled(True)
            return
        self.settings["last_download_path"] = str(path)
        self.settings["last_available_version"] = self.latest_update.version
        self.settings = save_settings(self.settings)
        self.update_status_label.setText(f"Updates: downloaded to {path}")
        self.download_update_button.setEnabled(True)
        QMessageBox.information(
            self,
            "Update downloaded",
            "The update package was downloaded. Close the imaging app before installing or replacing files.",
        )

    def open_bundle_folder(self):
        folder = bundle_root(self._settings_from_ui())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_build_guide(self):
        guide = project_root() / "docs" / "NINA_BUNDLE_INTEGRATION.md"
        if guide.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(project_root() / "docs")))

    def open_download_folder(self):
        path = Path(self.settings.get("last_download_path") or "")
        folder = path.parent if path else Path.home()
        if not folder.exists():
            folder = Path.home()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_nina_control_dialog(parent=None):
    dialog = NinaControlDialog(parent)
    dialog.show()
    if parent is not None:
        setattr(parent, "nina_control_dialog", dialog)
    return dialog

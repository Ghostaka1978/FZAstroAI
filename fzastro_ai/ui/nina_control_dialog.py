from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..nina.imaging_plan import (
    IMAGING_PLAN_DIR,
    calculate_framing_details,
    confirm_imaging_plan_for_nina,
)
from ..nina.session_report import create_session_report
from ..nina.nina_bridge import (
    NinaUpdateInfo,
    bundle_root,
    check_for_update,
    download_update,
    find_default_executable,
    is_process_running,
    latest_sequence_file,
    latest_nina_image_file,
    count_nina_image_files_since,
    latest_nina_image_session_count,
    latest_nina_image_session_files,
    nina_filename_frame_count,
    launch_executable,
    launch_sequence_file,
    list_available_sequences,
    load_confirmed_sequence_via_api,
    load_settings,
    project_root,
    save_settings,
    start_sequence_via_api,
    stop_sequence_via_api,
    test_nina_api,
    get_sequence_state,
    ensure_nina_api_ready,
)
from .astro_lookup_dialog import CAMERA_PRESETS, normalise_astro_imaging
from .window_utils import apply_window_defaults


class NinaControlDialog(QWidget):
    """FZASTRO IMAGING confirmation/control panel.

    Draft plans are created from SITE/SEEING/TARGETS context first.  The real
    `.nina-sequence.json` is generated only after the user confirms target,
    framing, focal length, exposure, gain, and frame count here.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("FZASTRO IMAGING CONTROL")
        self.resize(1040, 720)
        self.setMinimumSize(860, 600)
        apply_window_defaults(self)

        self.settings = load_settings()
        self.latest_update: NinaUpdateInfo | None = None
        self.current_plan_json: Path | None = None
        self.current_plan_data: dict | None = None
        self._side_panel_hidden = True
        self._draft_poll_started_at: float = 0.0
        self._draft_poll_deadline: float = 0.0
        self._draft_poll_timer = QTimer(self)
        self._draft_poll_timer.setInterval(700)
        self._draft_poll_timer.timeout.connect(self._poll_latest_draft_after_prepare)
        self._continue_confirm_load_after_prepare = False
        self._live_status_refresh_busy = False
        self._live_status_refresh_timer = QTimer(self)
        self._live_status_refresh_timer.setInterval(15000)
        # Regression anchor: the live session timer must call refresh_live_session_status directly.
        # self._live_status_refresh_timer.timeout.connect(self.refresh_live_session_status)
        self._live_status_refresh_timer.timeout.connect(
            self.refresh_live_session_status
        )
        self.execution_armed = False
        self.api_sequence_loaded = False
        self.api_loaded_sequence_name = ""
        self.api_last_state: dict | None = None
        self.session_started_at: float | None = None
        self._last_status_frame_count: int | None = None
        self._last_status_image_path = ""
        self._last_status_image_changed_at: float = 0.0
        self._last_image_preview_path = ""
        self._build_ui()
        self._load_settings_into_ui()
        QTimer.singleShot(0, self.refresh_status)
        QTimer.singleShot(100, self.load_latest_draft_if_available)
        self._live_status_refresh_timer.start()
        if self.auto_check_updates_checkbox.isChecked():
            QTimer.singleShot(900, self.check_for_updates_silent)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("FZASTRO IMAGING CONTROL")
        title.setObjectName("settingsCardTitle")
        self.show_side_button = QPushButton("SHOW SIDE PANEL")
        self.show_side_button.setVisible(False)
        self.show_side_button.clicked.connect(self.toggle_side_panel)
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(self.show_side_button)
        root_layout.addLayout(header_row)

        subtitle = QLabel(
            "Select a target, confirm + load the N.I.N.A. sequence, then start or stop the session from one clean cockpit."
        )
        subtitle.setObjectName("settingsCardSubtitle")
        subtitle.setWordWrap(True)
        root_layout.addWidget(subtitle)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, 1)

        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setObjectName("seeingPlannerScroll")
        main_holder = QWidget()
        main_layout = QVBoxLayout(main_holder)
        main_layout.setContentsMargins(0, 0, 8, 0)
        main_layout.setSpacing(10)
        main_scroll.setWidget(main_holder)
        self.splitter.addWidget(main_scroll)

        workflow_card = self._card("Simple imaging session workflow")
        workflow_layout = QGridLayout(workflow_card)
        workflow_layout.setContentsMargins(14, 14, 14, 14)
        workflow_layout.setHorizontalSpacing(12)
        workflow_layout.setVerticalSpacing(10)
        for column in range(3):
            workflow_layout.setColumnStretch(column, 1)
        workflow_header = QLabel("N.I.N.A. SESSION")
        workflow_header.setObjectName("ninaSectionTitle")
        workflow_layout.addWidget(workflow_header, 0, 0, 1, 3)

        workflow_intro = QLabel(
            "Simple 1 â†’ 2 â†’ 3 flow. Diagnostics stay in the side panel."
        )
        workflow_intro.setObjectName("webArticleBody")
        workflow_intro.setWordWrap(True)
        workflow_layout.addWidget(workflow_intro, 1, 0, 1, 3)

        self.open_targets_button = QPushButton("1\nOPEN TARGETS")
        self.open_targets_button.setObjectName("workflowStepButton")
        self.open_targets_button.setMinimumHeight(78)
        self.open_targets_button.setToolTip(
            "Open TARGETS and send one target to FZASTRO IMAGING."
        )
        self.open_targets_button.clicked.connect(self.open_targets)
        self.confirm_load_api_button = QPushButton("2\nCONFIRM + LOAD")
        self.confirm_load_api_button.setObjectName("workflowStepButton")
        self.confirm_load_api_button.setMinimumHeight(78)
        self.confirm_load_api_button.setToolTip(
            "Generate the confirmed N.I.N.A. sequence, copy it to N.I.N.A., load by API, and verify state. Does not start."
        )
        self.confirm_load_api_button.clicked.connect(
            self.confirm_generate_and_load_via_api
        )
        self.start_session_button = QPushButton("3\nSTART SESSION")
        self.start_session_button.setObjectName("workflowStepButton")
        self.start_session_button.setMinimumHeight(78)
        self.start_session_button.setToolTip(
            "Final confirmation, then send GET /sequence/start to N.I.N.A. This is the only start action."
        )
        self.start_session_button.clicked.connect(self.start_armed_session_via_api)
        self.stop_session_button = QPushButton("STOP / ABORT")
        self.stop_session_button.setObjectName("dangerActionButton")
        self.stop_session_button.setMinimumHeight(46)
        self.stop_session_button.setToolTip("Send stop/abort to N.I.N.A. API.")
        self.stop_session_button.clicked.connect(self.stop_session_via_api)
        self.generate_report_button = QPushButton("SESSION REPORT")
        self.generate_report_button.setObjectName("workflowToolButton")
        self.generate_report_button.setMinimumHeight(46)
        self.generate_report_button.setToolTip(
            "Write the session report and show highlights in this panel."
        )
        self.generate_report_button.clicked.connect(self.generate_session_report)

        workflow_layout.addWidget(self.open_targets_button, 2, 0)
        workflow_layout.addWidget(self.confirm_load_api_button, 2, 1)
        workflow_layout.addWidget(self.start_session_button, 2, 2)

        workflow_tools_widget = QWidget()
        workflow_tools_layout = QHBoxLayout(workflow_tools_widget)
        workflow_tools_layout.setContentsMargins(0, 0, 0, 0)
        workflow_tools_layout.setSpacing(12)
        workflow_tools_layout.addWidget(self.stop_session_button, 1)
        workflow_tools_layout.addWidget(self.generate_report_button, 1)
        workflow_layout.addWidget(workflow_tools_widget, 3, 0, 1, 3)

        self.workflow_status_strip = QLabel(
            "API: â€” Â· Target: â€” Â· Loaded: â€” Â· Images: â€”"
        )
        self.workflow_status_strip.setObjectName("workflowStatusStrip")
        self.workflow_status_strip.setWordWrap(True)
        workflow_layout.addWidget(self.workflow_status_strip, 4, 0, 1, 3)

        self.execution_status_label = QLabel(
            "Ready. 1 picks the target, 2 loads the confirmed N.I.N.A. sequence, 3 starts only after final confirmation."
        )
        self.execution_status_label.setObjectName("workflowHintText")
        self.execution_status_label.setWordWrap(True)
        workflow_layout.addWidget(self.execution_status_label, 5, 0, 1, 3)

        self.plan_progress_label = QLabel("Ready")
        self.plan_progress_label.setObjectName("astroLookupStatusLabel")
        self.plan_progress_label.setVisible(False)
        self.plan_progress_bar = QProgressBar()
        self.plan_progress_bar.setObjectName("astroLookupProgress")
        self.plan_progress_bar.setRange(0, 100)
        self.plan_progress_bar.setValue(0)
        self.plan_progress_bar.setTextVisible(False)
        self.plan_progress_bar.setVisible(False)
        workflow_layout.addWidget(self.plan_progress_label, 6, 0, 1, 1)
        workflow_layout.addWidget(self.plan_progress_bar, 6, 1, 1, 2)
        main_layout.addWidget(workflow_card)

        status_card = self._card("Live session status")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_layout.setSpacing(8)
        status_header = QLabel("LIVE SESSION STATUS")
        status_header.setObjectName("ninaSectionTitle")
        status_layout.addWidget(status_header)

        live_status_row = QHBoxLayout()
        live_status_row.setContentsMargins(0, 0, 0, 0)
        live_status_row.setSpacing(10)

        preview_column = QVBoxLayout()
        preview_column.setContentsMargins(0, 0, 0, 0)
        preview_column.setSpacing(6)
        preview_header = QLabel("LAST IMAGE PREVIEW")
        preview_header.setObjectName("ninaSectionTitle")
        preview_column.addWidget(preview_header)

        self.last_image_preview_label = QLabel("No preview loaded.")
        self.last_image_preview_label.setObjectName("astroLookupImagePreview")
        self.last_image_preview_label.setAlignment(Qt.AlignCenter)
        self.last_image_preview_label.setWordWrap(True)
        self.last_image_preview_label.setMinimumSize(220, 120)
        self.last_image_preview_label.setMaximumSize(300, 180)
        self.last_image_preview_label.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        preview_column.addWidget(self.last_image_preview_label, 0, Qt.AlignTop)
        preview_column.addStretch(1)

        status_details_widget = QWidget()
        status_details_layout = QGridLayout(status_details_widget)
        status_details_layout.setContentsMargins(0, 0, 0, 0)
        status_details_layout.setHorizontalSpacing(8)
        status_details_layout.setVerticalSpacing(8)

        self.status_api_value = self._status_value_label("API: not checked")
        self.status_sequence_value = self._status_value_label("Loaded sequence: â€”")
        self.status_target_value = self._status_value_label("Target: â€”")
        self.status_session_value = self._status_value_label("Session: idle")
        self.status_step_value = self._status_value_label("Current step: â€”")
        self.status_frames_value = self._status_value_label("Frames: â€”")
        self.status_capture_value = self._status_value_label("Capture: â€”")
        self.status_devices_value = self._status_value_label("Devices: â€”")
        self.status_last_image_value = self._status_value_label(
            "Last image: configure N.I.N.A. image folder"
        )
        status_items = [
            self.status_api_value,
            self.status_sequence_value,
            self.status_target_value,
            self.status_session_value,
            self.status_step_value,
            self.status_frames_value,
            self.status_capture_value,
            self.status_devices_value,
            self.status_last_image_value,
        ]
        for index, label in enumerate(status_items):
            row = index // 2
            col = (index % 2) * 2
            status_details_layout.addWidget(label, row, col, 1, 2)

        self.last_image_preview_details_label = QLabel(
            "No last-image preview yet. FITS files will be stretched for display when astropy is available."
        )
        self.last_image_preview_details_label.setObjectName("webArticleBody")
        self.last_image_preview_details_label.setWordWrap(True)
        self.last_image_preview_details_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        detail_row = (len(status_items) + 1) // 2
        status_details_layout.addWidget(
            self.last_image_preview_details_label, detail_row, 0, 1, 4
        )

        last_image_button_row = QWidget()
        last_image_button_layout = QHBoxLayout(last_image_button_row)
        last_image_button_layout.setContentsMargins(0, 0, 0, 0)
        self.open_last_image_button = QPushButton("OPEN LAST IMAGE")
        self.open_last_image_button.clicked.connect(self.open_last_image)
        self.open_image_folder_button = QPushButton("OPEN IMAGE FOLDER")
        self.open_image_folder_button.clicked.connect(self.open_nina_image_folder)
        self.refresh_preview_button = QPushButton("REFRESH PREVIEW")
        self.refresh_preview_button.clicked.connect(
            lambda: self.refresh_last_image_preview(force=True)
        )
        last_image_button_layout.addWidget(self.open_last_image_button)
        last_image_button_layout.addWidget(self.open_image_folder_button)
        last_image_button_layout.addWidget(self.refresh_preview_button)
        last_image_button_layout.addStretch(1)
        status_details_layout.addWidget(last_image_button_row, detail_row + 1, 0, 1, 4)
        status_details_layout.setRowStretch(detail_row + 2, 1)

        live_status_row.addLayout(preview_column, 0)
        live_status_row.addWidget(status_details_widget, 1)
        status_layout.addLayout(live_status_row)
        main_layout.addWidget(status_card)

        target_card = self._card("Target details")
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(12, 12, 12, 12)
        target_layout.setSpacing(8)
        target_header = QLabel("TARGET + LOOKUP DETAILS")
        target_header.setObjectName("ninaSectionTitle")
        target_layout.addWidget(target_header)

        target_preview_row = QHBoxLayout()
        self.target_preview_label = QLabel("No frame preview loaded.")
        self.target_preview_label.setObjectName("astroLookupImagePreview")
        self.target_preview_label.setAlignment(Qt.AlignCenter)
        self.target_preview_label.setWordWrap(True)
        self.target_preview_label.setMinimumSize(220, 120)
        self.target_preview_label.setMaximumHeight(180)
        self.target_summary_label = QLabel("No draft loaded yet.")
        self.target_summary_label.setObjectName("webArticleBody")
        self.target_summary_label.setWordWrap(True)
        self.target_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        target_preview_row.addWidget(self.target_preview_label, 0)
        target_preview_row.addWidget(self.target_summary_label, 1)
        target_layout.addLayout(target_preview_row)
        self.window_summary_label = QLabel("SEEING/TARGETS window will appear here.")
        self.window_summary_label.setObjectName("webArticleBody")
        self.window_summary_label.setWordWrap(True)
        self.window_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        target_layout.addWidget(self.window_summary_label)
        self.lookup_summary_label = QLabel(
            "Lookup metadata comes from structured TARGETS/LOOKUP data, not rendered HTML."
        )
        self.lookup_summary_label.setObjectName("sidebarFooter")
        self.lookup_summary_label.setWordWrap(True)
        target_layout.addWidget(self.lookup_summary_label)
        self.lookup_details_browser = QTextBrowser()
        self.lookup_details_browser.setObjectName("astroLookupResultBrowser")
        self.lookup_details_browser.setOpenExternalLinks(True)
        self.lookup_details_browser.setMinimumHeight(120)
        self.lookup_details_browser.setHtml(
            "<html><body style='background:#0f1318;color:#9ca8b4;font-family:Segoe UI;font-size:10px;'>"
            "Select a target in TARGETS and send it here to review LOOKUP details and distance when available."
            "</body></html>"
        )
        target_layout.addWidget(self.lookup_details_browser)
        main_layout.addWidget(target_card)

        framing_card = self._card("Framing")
        framing_layout = QGridLayout(framing_card)
        framing_layout.setContentsMargins(12, 12, 12, 12)
        framing_layout.setHorizontalSpacing(8)
        framing_layout.setVerticalSpacing(8)
        framing_header = QLabel("FRAMING + CAPTURE CONFIRMATION")
        framing_header.setObjectName("ninaSectionTitle")
        framing_layout.addWidget(framing_header, 0, 0, 1, 6)

        self.camera_combo = QComboBox()
        self.camera_combo.setObjectName("astroLookupCombo")
        for preset_key, preset in CAMERA_PRESETS.items():
            self.camera_combo.addItem(
                str(preset.get("label") or preset.get("name") or preset_key),
                str(preset_key),
            )
        self.focal_spin = QDoubleSpinBox()
        self.focal_spin.setRange(1.0, 20000.0)
        self.focal_spin.setDecimals(1)
        self.focal_spin.setSuffix(" mm")
        self.focal_spin.setValue(700.0)
        self.exposure_spin = QSpinBox()
        self.exposure_spin.setRange(1, 86400)
        self.exposure_spin.setSuffix(" s")
        self.exposure_spin.setValue(60)
        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 10000)
        self.gain_spin.setValue(200)
        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(1, 10000)
        self.frames_spin.setValue(1)
        self.frames_spin.setEnabled(False)
        self.frames_spin.setToolTip(
            "Frames are calculated automatically from the selected SEEING imaging window and exposure time."
        )

        fields = [
            ("Camera", self.camera_combo),
            ("Focal", self.focal_spin),
            ("Exposure", self.exposure_spin),
            ("Gain", self.gain_spin),
            ("Auto frames", self.frames_spin),
        ]
        for index, (label, widget) in enumerate(fields):
            framing_layout.addWidget(
                QLabel(label + ":"), 1 + index // 3, (index % 3) * 2
            )
            framing_layout.addWidget(widget, 1 + index // 3, (index % 3) * 2 + 1)
        self.framing_result_label = QLabel(
            "Load a draft to calculate FOV, image scale, target fit, and integration time."
        )
        self.framing_result_label.setObjectName("sidebarFooter")
        self.framing_result_label.setWordWrap(True)
        framing_layout.addWidget(self.framing_result_label, 3, 0, 1, 6)
        main_layout.addWidget(framing_card)

        self.camera_combo.currentIndexChanged.connect(self.refresh_framing_preview)
        for widget in (
            self.focal_spin,
            self.exposure_spin,
            self.gain_spin,
        ):
            signal = getattr(widget, "valueChanged", None) or getattr(
                widget, "textChanged", None
            )
            if signal is not None:
                signal.connect(self.refresh_framing_preview)

        notes_card = self._card("Notes")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(12, 12, 12, 12)
        notes_layout.setSpacing(8)
        notes_header = QLabel("REVIEW NOTES")
        notes_header.setObjectName("ninaSectionTitle")
        notes_layout.addWidget(notes_header)
        self.notes_output = QPlainTextEdit()
        self.notes_output.setReadOnly(True)
        self.notes_output.setPlaceholderText(
            "Draft, framing, confirmation, and update notes will appear here."
        )
        self.notes_output.setMinimumHeight(150)
        notes_layout.addWidget(self.notes_output)
        main_layout.addWidget(notes_card, 1)

        self.side_drawer = QFrame()
        self.side_drawer.setObjectName("settingsCard")
        self.side_drawer.setMinimumWidth(310)
        self.side_drawer.setMaximumWidth(430)
        side_layout = QVBoxLayout(self.side_drawer)
        side_layout.setContentsMargins(10, 10, 10, 10)
        side_layout.setSpacing(8)
        side_header_row = QHBoxLayout()
        side_title = QLabel("SETTINGS / TOOLS")
        side_title.setObjectName("ninaSectionTitle")
        self.hide_side_button = QPushButton("HIDE SIDE PANEL")
        self.hide_side_button.clicked.connect(self.toggle_side_panel)
        side_header_row.addWidget(side_title)
        side_header_row.addStretch(1)
        side_header_row.addWidget(self.hide_side_button)
        side_layout.addLayout(side_header_row)

        config_panel, config_body = self._collapsible_panel("CONFIG", expanded=True)
        self._populate_config_body(config_body)
        side_layout.addWidget(config_panel)

        tools_panel, tools_body = self._collapsible_panel(
            "TOOLS / DIAGNOSTICS", expanded=False
        )
        self._populate_tools_body(tools_body)
        side_layout.addWidget(tools_panel)

        updates_panel, updates_body = self._collapsible_panel("UPDATES", expanded=False)
        self._populate_updates_body(updates_body)
        side_layout.addWidget(updates_panel)
        side_layout.addStretch(1)
        footer = QLabel(
            "Safety rule: FZAstro may build, launch, open, and download for review, but it does not start equipment-control actions automatically."
        )
        footer.setObjectName("sidebarFooter")
        footer.setWordWrap(True)
        side_layout.addWidget(footer)
        self.splitter.addWidget(self.side_drawer)
        self.splitter.setSizes([980, 0])
        self._apply_side_panel_state()

    def _populate_config_body(self, body: QFrame):
        layout = QGridLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(7)
        layout.addWidget(QLabel("Executable:"), 0, 0)
        self.executable_input = QLineEdit()
        self.executable_input.setPlaceholderText(
            "bundled_apps/FZAstroImaging/FZAstroImaging.exe"
        )
        self.executable_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.executable_input, 0, 1, 1, 2)
        self.browse_executable_button = QPushButton("BROWSE")
        self.browse_executable_button.clicked.connect(self.browse_executable)
        self.find_executable_button = QPushButton("FIND")
        self.find_executable_button.clicked.connect(self.find_executable)
        layout.addWidget(self.browse_executable_button, 1, 1)
        layout.addWidget(self.find_executable_button, 1, 2)
        layout.addWidget(QLabel("API host:"), 2, 0)
        self.api_host_input = QLineEdit()
        self.api_host_input.setPlaceholderText("127.0.0.1")
        self.api_host_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.api_host_input, 2, 1)
        layout.addWidget(QLabel("Port:"), 2, 2)
        self.api_port_input = QSpinBox()
        self.api_port_input.setRange(1, 65535)
        self.api_port_input.setValue(1888)
        self.api_port_input.valueChanged.connect(self.save_from_ui)
        layout.addWidget(self.api_port_input, 2, 3)
        layout.addWidget(QLabel("N.I.N.A. sequence folder:"), 3, 0)
        self.nina_sequence_dir_input = QLineEdit()
        self.nina_sequence_dir_input.setPlaceholderText(
            "Folder visible in N.I.N.A. Advanced Sequencer"
        )
        self.nina_sequence_dir_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.nina_sequence_dir_input, 3, 1, 1, 2)
        self.browse_nina_sequence_dir_button = QPushButton("BROWSE")
        self.browse_nina_sequence_dir_button.clicked.connect(
            self.browse_nina_sequence_dir
        )
        layout.addWidget(self.browse_nina_sequence_dir_button, 3, 3)

        layout.addWidget(QLabel("N.I.N.A. image folder:"), 4, 0)
        self.nina_image_dir_input = QLineEdit()
        self.nina_image_dir_input.setPlaceholderText(
            "Folder where N.I.N.A. saves captured images"
        )
        self.nina_image_dir_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.nina_image_dir_input, 4, 1, 1, 2)
        self.browse_nina_image_dir_button = QPushButton("BROWSE")
        self.browse_nina_image_dir_button.clicked.connect(self.browse_nina_image_dir)
        layout.addWidget(self.browse_nina_image_dir_button, 4, 3)

        layout.addWidget(QLabel("Equipment prep sample:"), 5, 0)
        self.equipment_prep_template_input = QLineEdit()
        self.equipment_prep_template_input.setPlaceholderText(
            r"D:\Dropbox\N.I.N.A\FZAstro_EquipmentPrepSample.json"
        )
        self.equipment_prep_template_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.equipment_prep_template_input, 5, 1, 1, 2)
        self.browse_equipment_prep_button = QPushButton("BROWSE")
        self.browse_equipment_prep_button.clicked.connect(
            self.browse_equipment_prep_template
        )
        layout.addWidget(self.browse_equipment_prep_button, 5, 3)

        self.status_label = QLabel("Status: not checked")
        self.status_label.setObjectName("webArticleBody")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 6, 0, 1, 4)
        self.launch_button = QPushButton("LAUNCH FZASTRO IMAGING")
        self.launch_button.setObjectName("primaryActionButton")
        self.launch_button.clicked.connect(self.launch_imaging_app)
        self.refresh_status_button = QPushButton("REFRESH")
        self.refresh_status_button.clicked.connect(self.refresh_status)
        self.open_bundle_folder_button = QPushButton("OPEN BUNDLE")
        self.open_bundle_folder_button.clicked.connect(self.open_bundle_folder)
        self.open_build_guide_button = QPushButton("BUILD GUIDE")
        self.open_build_guide_button.clicked.connect(self.open_build_guide)
        layout.addWidget(self.launch_button, 7, 0, 1, 2)
        layout.addWidget(self.refresh_status_button, 7, 2)
        layout.addWidget(self.open_bundle_folder_button, 8, 0, 1, 2)
        layout.addWidget(self.open_build_guide_button, 8, 2)

    def _populate_tools_body(self, body: QFrame):
        layout = QGridLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(7)

        layout.addWidget(QLabel("Manual plan tools:"), 0, 0, 1, 3)
        self.load_latest_draft_button = QPushButton("LOAD LATEST DRAFT")
        self.load_latest_draft_button.clicked.connect(self.load_latest_draft)
        self.confirm_sequence_button = QPushButton("GENERATE JSON ONLY")
        self.confirm_sequence_button.clicked.connect(self.confirm_generate_nina_json)
        self.open_latest_sequence_button = QPushButton("OPEN LATEST PLAN")
        self.open_latest_sequence_button.clicked.connect(
            self.open_latest_sequence_in_imaging
        )
        self.open_plans_folder_button = QPushButton("OPEN PLANS FOLDER")
        self.open_plans_folder_button.clicked.connect(self.open_plans_folder)
        self.plan_help_button = QPushButton("HELP")
        self.plan_help_button.clicked.connect(self.show_planning_help)
        layout.addWidget(self.load_latest_draft_button, 1, 0)
        layout.addWidget(self.confirm_sequence_button, 1, 1)
        layout.addWidget(self.open_latest_sequence_button, 1, 2)
        layout.addWidget(self.open_plans_folder_button, 2, 0)
        layout.addWidget(self.plan_help_button, 2, 1)

        layout.addWidget(QLabel("N.I.N.A. API diagnostics:"), 3, 0, 1, 3)
        self.test_api_button = QPushButton("TEST API")
        self.test_api_button.clicked.connect(self.test_nina_api_connection)
        self.list_api_sequences_button = QPushButton("LIST SEQUENCES")
        self.list_api_sequences_button.clicked.connect(self.list_nina_api_sequences)
        self.check_api_state_button = QPushButton("CHECK STATE")
        self.check_api_state_button.clicked.connect(self.check_nina_api_state)
        self.load_api_sequence_button = QPushButton("LOAD VIA API ONLY")
        self.load_api_sequence_button.clicked.connect(self.load_confirmed_plan_via_api)
        layout.addWidget(self.test_api_button, 4, 0)
        layout.addWidget(self.list_api_sequences_button, 4, 1)
        layout.addWidget(self.check_api_state_button, 4, 2)
        layout.addWidget(self.load_api_sequence_button, 5, 0, 1, 2)

        self.open_session_folder_button = QPushButton("OPEN SESSION REPORT FOLDER")
        self.open_session_folder_button.clicked.connect(
            self.open_latest_session_report_folder
        )
        layout.addWidget(self.open_session_folder_button, 6, 0, 1, 3)

        self.plan_folder_label = QLabel(f"Plans folder: {IMAGING_PLAN_DIR}")
        self.plan_folder_label.setObjectName("sidebarFooter")
        self.plan_folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.plan_folder_label.setWordWrap(True)
        layout.addWidget(self.plan_folder_label, 7, 0, 1, 3)

    def _populate_updates_body(self, body: QFrame):
        layout = QGridLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(7)
        layout.addWidget(QLabel("Installed:"), 0, 0)
        self.installed_version_input = QLineEdit()
        self.installed_version_input.setPlaceholderText("Optional, example: 3.2.1")
        self.installed_version_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.installed_version_input, 0, 1, 1, 2)
        layout.addWidget(QLabel("Feed:"), 1, 0)
        self.update_url_input = QLineEdit()
        self.update_url_input.setPlaceholderText(
            "Manifest JSON or GitHub latest-release API URL"
        )
        self.update_url_input.editingFinished.connect(self.save_from_ui)
        layout.addWidget(self.update_url_input, 1, 1, 1, 3)
        self.auto_check_updates_checkbox = QCheckBox("Check when panel opens")
        self.auto_check_updates_checkbox.stateChanged.connect(self.save_from_ui)
        layout.addWidget(self.auto_check_updates_checkbox, 2, 1, 1, 2)
        self.auto_download_updates_checkbox = QCheckBox(
            "Auto-download after confirmation"
        )
        self.auto_download_updates_checkbox.stateChanged.connect(self.save_from_ui)
        layout.addWidget(self.auto_download_updates_checkbox, 3, 1, 1, 2)
        self.check_update_button = QPushButton("CHECK")
        self.check_update_button.clicked.connect(self.check_for_updates)
        self.download_update_button = QPushButton("DOWNLOAD")
        self.download_update_button.setEnabled(False)
        self.download_update_button.clicked.connect(self.download_latest_update)
        self.open_download_folder_button = QPushButton("OPEN DOWNLOADS")
        self.open_download_folder_button.clicked.connect(self.open_download_folder)
        layout.addWidget(self.check_update_button, 4, 0)
        layout.addWidget(self.download_update_button, 4, 1)
        layout.addWidget(self.open_download_folder_button, 4, 2, 1, 2)
        self.update_status_label = QLabel("Updates: no check yet")
        self.update_status_label.setObjectName("webArticleBody")
        self.update_status_label.setWordWrap(True)
        layout.addWidget(self.update_status_label, 5, 0, 1, 4)

    def _card(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("settingsCard")
        frame.setToolTip(title)
        return frame

    def _status_value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sidebarFooter")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _state_first_value_any(self, node, keys: tuple[str, ...]):
        wanted = {str(key).casefold() for key in keys}
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).casefold() in wanted and value not in (None, ""):
                    return value
            for value in node.values():
                found = self._state_first_value_any(value, keys)
                if found not in (None, ""):
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._state_first_value_any(value, keys)
                if found not in (None, ""):
                    return found
        return None

    def _state_values_any(self, node, keys: tuple[str, ...]) -> list:
        wanted = {str(key).casefold() for key in keys}
        values = []
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).casefold() in wanted and value not in (None, ""):
                    values.append(value)
                values.extend(self._state_values_any(value, keys))
        elif isinstance(node, list):
            for value in node:
                values.extend(self._state_values_any(value, keys))
        return values

    def _format_target_status(self, api_state: dict | None) -> str:
        target = str((self.current_plan_data or {}).get("target_name") or "â€”")
        raw_target = (
            self._state_first_value_any(
                api_state, ("TargetName", "Target", "TargetNameString")
            )
            if api_state
            else None
        )
        if isinstance(raw_target, dict):
            name = raw_target.get("TargetName") or raw_target.get("Name") or target
            coords = (
                raw_target.get("InputCoordinates")
                or raw_target.get("Coordinates")
                or {}
            )
            if isinstance(coords, dict):
                ra_h = coords.get("RAHours")
                ra_m = coords.get("RAMinutes")
                dec_d = coords.get("DecDegrees")
                dec_m = coords.get("DecMinutes")
                if ra_h is not None and dec_d is not None:
                    return (
                        f"{name} Â· RA {ra_h}:{ra_m or 0} Â· Dec {dec_d}:{dec_m or 0}"
                    )
            return str(name)
        if raw_target not in (None, ""):
            return str(raw_target)
        return target

    def _planned_frame_number(self) -> int | None:
        if not self.current_plan_data:
            return None
        for key in ("frames", "frame_count"):
            try:
                value = self.current_plan_data.get(key)
                if value not in (None, ""):
                    return max(0, int(float(str(value))))
            except Exception:
                continue
        return None

    def _display_session_state(
        self,
        api_state: dict | None,
        raw_state,
        latest_image: Path | None,
        captured_count: int | None,
        planned_count: int | None,
    ) -> str:
        values = (
            self._state_values_any(
                api_state, ("Status", "State", "SequenceStatus", "RunState")
            )
            if api_state
            else []
        )
        normalized_values = {
            str(value).strip().upper() for value in values if value not in (None, "")
        }
        running_tokens = {
            "RUNNING",
            "STARTED",
            "EXECUTING",
            "INPROGRESS",
            "IN_PROGRESS",
            "BUSY",
            "EXPOSING",
            "CAPTURING",
        }
        if normalized_values & running_tokens:
            return "CAPTURING"

        latest_text = str(latest_image or "")
        if latest_text and latest_text != self._last_status_image_path:
            self._last_status_image_path = latest_text
            self._last_status_image_changed_at = time.time()

        if captured_count is not None:
            previous = self._last_status_frame_count
            self._last_status_frame_count = captured_count
            if previous is not None and captured_count > previous:
                return "CAPTURING"

        raw = str(raw_state or "").strip()
        raw_upper = raw.upper()
        maybe_stale_finished = raw_upper in {
            "CREATED",
            "FINISHED",
            "COMPLETE",
            "COMPLETED",
            "IDLE",
        }
        image_changed_recently = bool(
            self._last_status_image_changed_at
            and time.time() - self._last_status_image_changed_at <= 180.0
        )
        plan_not_complete = (
            captured_count is not None
            and planned_count is not None
            and captured_count < planned_count
        )
        if (
            self.session_started_at
            and maybe_stale_finished
            and image_changed_recently
            and plan_not_complete
        ):
            return f"CAPTURING (N.I.N.A. raw: {raw})" if raw else "CAPTURING"
        if self.session_started_at and not raw:
            return "running/started"
        return raw or "idle"

    def _summarize_device_status(self, api_state: dict | None) -> str:
        if not api_state:
            return "Devices: â€”"
        parts = []
        for label, keys in (
            ("Camera", ("CameraConnected", "CameraStatus", "CameraState")),
            (
                "Mount",
                (
                    "TelescopeConnected",
                    "MountStatus",
                    "TelescopeStatus",
                    "TelescopeState",
                ),
            ),
            ("Guider", ("GuiderConnected", "GuiderStatus", "GuidingState")),
            ("Focuser", ("FocuserConnected", "FocuserStatus", "FocuserState")),
        ):
            value = self._state_first_value_any(api_state, keys)
            if value not in (None, ""):
                parts.append(f"{label} {value}")
        return "Devices: " + (
            " Â· ".join(parts) if parts else "check N.I.N.A. device panels"
        )

    def _captured_frame_number(
        self,
        api_captured,
        fallback_count: int | None,
        session_folder_count: int | None = None,
        filename_count: int | None = None,
    ) -> int | None:
        counts: list[int] = []
        try:
            if api_captured not in (None, ""):
                counts.append(max(0, int(float(str(api_captured).strip()))))
        except Exception:
            pass
        for value in (fallback_count, session_folder_count, filename_count):
            try:
                if value is not None:
                    counts.append(max(0, int(value)))
            except Exception:
                continue
        if not counts:
            return None
        # N.I.N.A. can report 0 completed while saved FITS files exist.  Real
        # saved-file counts and filename counters are stronger live evidence.
        return max(counts)

    def _captured_frame_text(
        self,
        api_captured,
        fallback_count: int | None,
        session_folder_count: int | None = None,
        filename_count: int | None = None,
    ) -> str:
        captured = self._captured_frame_number(
            api_captured, fallback_count, session_folder_count, filename_count
        )
        return str(captured) if captured is not None else "â€”"

    def _image_capture_counts(
        self, since_epoch: float | None = None
    ) -> tuple[int | None, int | None, int | None]:
        since_epoch = self.session_started_at if since_epoch is None else since_epoch
        session_files = latest_nina_image_session_files(self.settings, since_epoch)
        session_folder_count = (
            len(session_files)
            if session_files
            else latest_nina_image_session_count(self.settings, since_epoch)
        )
        # Keep the older root-wide count available as a weak fallback only.  The
        # session-folder count is preferred because a N.I.N.A. image root can hold
        # many date/LIGHT folders from unrelated targets.
        saved_since_count = (
            session_folder_count
            if session_folder_count
            else count_nina_image_files_since(self.settings, since_epoch)
        )
        latest = (
            session_files[-1]
            if session_files
            else latest_nina_image_file(self.settings, since_epoch)
        )
        if latest is None and since_epoch is not None:
            latest = latest_nina_image_file(self.settings)
        filename_count = nina_filename_frame_count(latest)
        return saved_since_count, session_folder_count, filename_count

    def _latest_image_for_status(self, since_epoch: float | None = None) -> Path | None:
        session_files = latest_nina_image_session_files(self.settings, since_epoch)
        if session_files:
            return session_files[-1]
        latest = latest_nina_image_file(self.settings, since_epoch)
        if latest is None and since_epoch is not None:
            latest = latest_nina_image_file(self.settings)
        return latest

    def _format_latest_image_text(
        self, since_epoch: float | None = None, latest: Path | None = None
    ) -> str:
        latest = (
            latest if latest is not None else self._latest_image_for_status(since_epoch)
        )
        if latest is None:
            if str(self.settings.get("nina_image_dir") or "").strip():
                return "Last image: no saved image found yet"
            return "Last image: configure N.I.N.A. image folder"
        try:
            stamp = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            stamp = "timestamp unavailable"
        return f"Last image: {latest.name} Â· {stamp} Â· {latest}"

    def _fits_preview_pixmap(self, path: Path) -> tuple[QPixmap | None, str]:
        """Render a small stretched grayscale preview for a FITS frame.

        FITS files are not displayable by Qt directly.  This uses astropy only
        when a FITS preview is requested, applies a conservative percentile
        stretch, and returns a QPixmap safe for display in the live cockpit.
        """

        try:
            from astropy.io import fits
            import numpy as np
        except Exception as exc:
            return (
                None,
                f"FITS preview unavailable: astropy/numpy not available ({exc})\n{path}",
            )

        try:
            with fits.open(path, memmap=False) as hdul:
                data = None
                for hdu in hdul:
                    if getattr(hdu, "data", None) is not None:
                        data = hdu.data
                        break
            if data is None:
                return None, f"FITS preview unavailable: no image data found\n{path}"
            array = np.asarray(data, dtype=np.float32)
            while array.ndim > 2:
                array = array[0]
            if array.ndim != 2:
                return (
                    None,
                    f"FITS preview unavailable: unsupported data shape {array.shape}\n{path}",
                )
            finite = np.isfinite(array)
            if not finite.any():
                return None, f"FITS preview unavailable: no finite pixel values\n{path}"

            # Keep the preview responsive for large camera frames.
            max_source_dim = max(array.shape)
            step = max(1, int(max_source_dim // 1600))
            preview_array = array[::step, ::step] if step > 1 else array
            sample = preview_array[np.isfinite(preview_array)]
            low, high = np.percentile(sample, (0.5, 99.5))
            if not np.isfinite(low) or not np.isfinite(high) or high <= low:
                low = float(np.nanmin(sample))
                high = float(np.nanmax(sample))
            if high <= low:
                high = low + 1.0
            scaled = np.clip((preview_array - low) / (high - low) * 255.0, 0, 255)
            scaled = np.nan_to_num(scaled, nan=0.0, posinf=255.0, neginf=0.0).astype(
                np.uint8
            )
            if not scaled.flags["C_CONTIGUOUS"]:
                scaled = np.ascontiguousarray(scaled)
            height, width = scaled.shape
            image_format = getattr(QImage, "Format_Grayscale8", None)
            if image_format is None:
                image_format = QImage.Format.Format_Grayscale8
            image = QImage(scaled.data, width, height, width, image_format).copy()
            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                return (
                    None,
                    f"FITS preview unavailable: could not create Qt image\n{path}",
                )
            return pixmap, ""
        except Exception as exc:
            return None, f"FITS preview failed: {exc}\n{path}"

    def _last_image_pixmap_for_path(self, path: Path) -> tuple[QPixmap | None, str]:
        suffix = path.suffix.lower()
        if suffix in {".fit", ".fits", ".fts"}:
            return self._fits_preview_pixmap(path)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None, f"Preview unavailable for {suffix or 'this file type'}\n{path}"
        return pixmap, ""

    def _set_last_image_preview_text(self, text: str):
        if not hasattr(self, "last_image_preview_label"):
            return
        self.last_image_preview_label.clear()
        self.last_image_preview_label.setText("No preview")
        self.last_image_preview_label.setToolTip("")
        if hasattr(self, "last_image_preview_details_label"):
            self.last_image_preview_details_label.setText(text)

    def _set_last_image_preview_details(self, latest: Path, message: str = ""):
        if not hasattr(self, "last_image_preview_details_label"):
            return
        try:
            stamp = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            stamp = "timestamp unavailable"
        detail_lines = [
            f"Last image: {latest.name}",
            f"Saved: {stamp}",
            f"Folder: {latest.parent}",
        ]
        if message:
            detail_lines.append(message)
        self.last_image_preview_details_label.setText("\n".join(detail_lines))
        self.last_image_preview_details_label.setToolTip(str(latest))

    def refresh_last_image_preview(self, force: bool = True):
        latest = self._latest_image_for_status(self.session_started_at)
        if latest is None:
            self._last_image_preview_path = ""
            if str(self.settings.get("nina_image_dir") or "").strip():
                self._set_last_image_preview_text("No saved image found yet.")
            else:
                self._set_last_image_preview_text(
                    "Set CONFIG â†’ N.I.N.A. image folder to enable last-image preview."
                )
            return
        latest_text = str(latest)
        if not force and self._last_image_preview_path == latest_text:
            return
        self._last_image_preview_path = latest_text
        pixmap, message = self._last_image_pixmap_for_path(latest)
        if pixmap is None:
            self._set_last_image_preview_text(
                message or f"Preview unavailable\n{latest}"
            )
            return
        target_width = max(180, self.last_image_preview_label.width() - 8)
        target_height = max(100, self.last_image_preview_label.height() - 8)
        scaled = pixmap.scaled(
            target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.last_image_preview_label.clear()
        self.last_image_preview_label.setPixmap(scaled)
        self.last_image_preview_label.setToolTip(str(latest))
        self._set_last_image_preview_details(latest)

    def _update_last_image_preview_if_changed(self, latest: Path | None):
        if latest is None:
            self.refresh_last_image_preview(force=False)
            return
        if str(latest) != self._last_image_preview_path:
            self.refresh_last_image_preview(force=True)

    def open_last_image(self):
        latest = self._latest_image_for_status(self.session_started_at)
        if latest is None:
            QMessageBox.information(
                self, "Open last image", "No saved N.I.N.A. image was found yet."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(latest)))

    def open_nina_image_folder(self):
        latest = self._latest_image_for_status(self.session_started_at)
        if latest is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(latest.parent)))
            return
        raw = str(self.settings.get("nina_image_dir") or "").strip()
        if not raw:
            QMessageBox.information(
                self, "Open image folder", "Set CONFIG â†’ N.I.N.A. image folder first."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(raw).expanduser())))

    def _update_session_status_cards(self, api_state: dict | None = None):
        api_state = api_state if api_state is not None else self.api_last_state
        target = self._format_target_status(api_state)
        raw_session_state = (
            self._state_first_value_any(
                api_state, ("Status", "State", "SequenceStatus", "RunState")
            )
            if api_state
            else None
        )
        current_step = (
            self._state_first_value_any(
                api_state,
                (
                    "CurrentInstruction",
                    "CurrentStep",
                    "CurrentAction",
                    "CurrentSequenceItem",
                ),
            )
            if api_state
            else None
        )
        if not current_step and api_state:
            current_step = self._state_first_value_any(api_state, ("Name",))
        planned_count = self._planned_frame_number()
        planned_text = str(planned_count) if planned_count is not None else "â€”"
        exposure = (
            self._state_first_value_any(api_state, ("ExposureTime", "ExposureSeconds"))
            if api_state
            else None
        )
        gain = (
            self._state_first_value_any(api_state, ("Gain", "CameraGain"))
            if api_state
            else None
        )
        captured = (
            self._state_first_value_any(
                api_state,
                ("Completed", "CompletedCount", "CompletedFrames", "CapturedFrames"),
            )
            if api_state
            else None
        )
        fallback_count, session_folder_count, filename_count = (
            self._image_capture_counts(self.session_started_at)
        )
        captured_number = self._captured_frame_number(
            captured, fallback_count, session_folder_count, filename_count
        )
        captured_text = str(captured_number) if captured_number is not None else "â€”"
        latest_image = self._latest_image_for_status(self.session_started_at)
        session_text = self._display_session_state(
            api_state, raw_session_state, latest_image, captured_number, planned_count
        )

        self.status_api_value.setText(
            "API: online" if api_state else "API: not checked"
        )
        self.status_sequence_value.setText(
            f"Loaded sequence: {self.api_loaded_sequence_name or self.settings.get('last_api_sequence_name') or 'â€”'}"
        )
        self.status_target_value.setText(f"Target: {target}")
        self.status_session_value.setText(f"Session: {session_text}")
        self.status_step_value.setText(f"Current step: {current_step or 'â€”'}")
        self.status_frames_value.setText(
            f"Frames: {captured_text} captured / {planned_text} planned"
        )
        self.status_capture_value.setText(
            f"Capture: exposure {exposure or (self.current_plan_data or {}).get('exposure_seconds') or 'â€”'}s Â· gain {gain if gain not in (None, '') else (self.current_plan_data or {}).get('gain', 'â€”')}"
        )
        self.status_devices_value.setText(self._summarize_device_status(api_state))
        self.status_last_image_value.setText(
            self._format_latest_image_text(self.session_started_at, latest_image)
        )
        if hasattr(self, "workflow_status_strip"):
            api_text = "online" if api_state else "not checked"
            sequence_text = self.api_loaded_sequence_name or str(
                self.settings.get("last_api_sequence_name") or "â€”"
            )
            image_text = latest_image.name if latest_image is not None else "â€”"
            self.workflow_status_strip.setText(
                f"API: {api_text} Â· Target: {target or 'â€”'} Â· Loaded: {sequence_text} Â· Images: {captured_text} Â· Last: {image_text}"
            )
        self._update_last_image_preview_if_changed(latest_image)

    def _collapsible_panel(
        self, title: str, *, expanded: bool = True
    ) -> tuple[QFrame, QFrame]:
        frame = QFrame()
        frame.setObjectName("settingsCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        button = QToolButton()
        button.setText(("â–¾ " if expanded else "â–¸ ") + title)
        button.setObjectName("ninaDrawerHeader")
        button.setCheckable(True)
        button.setChecked(expanded)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        body = QFrame()
        body.setVisible(expanded)

        def toggle(checked: bool):
            button.setText(("â–¾ " if checked else "â–¸ ") + title)
            body.setVisible(checked)

        button.toggled.connect(toggle)
        layout.addWidget(button)
        layout.addWidget(body)
        return frame, body

    def _apply_side_panel_state(self):
        hidden = bool(self._side_panel_hidden)
        self.side_drawer.setVisible(not hidden)
        self.show_side_button.setVisible(hidden)
        self.hide_side_button.setText("HIDE SIDE PANEL")
        if hidden:
            self.splitter.setSizes([max(900, self.width() - 40), 0])
        else:
            self.splitter.setSizes([720, 330])

    def toggle_side_panel(self):
        self._side_panel_hidden = not self._side_panel_hidden
        self._apply_side_panel_state()

    def _set_plan_progress(
        self, label: str, value: int | None = None, *, busy: bool = False
    ):
        self.plan_progress_label.setText(str(label or "Workingâ€¦"))
        self.plan_progress_label.setVisible(True)
        self.plan_progress_bar.setVisible(True)
        if busy:
            self.plan_progress_bar.setRange(0, 0)
        else:
            self.plan_progress_bar.setRange(0, 100)
            if value is not None:
                self.plan_progress_bar.setValue(max(0, min(100, int(value))))

    def _hide_plan_progress(self):
        self.plan_progress_bar.setVisible(False)
        self.plan_progress_label.setVisible(False)
        self.plan_progress_bar.setRange(0, 100)
        self.plan_progress_bar.setValue(0)

    def _load_settings_into_ui(self):
        self.executable_input.setText(str(self.settings.get("executable_path") or ""))
        self.api_host_input.setText(str(self.settings.get("api_host") or "127.0.0.1"))
        self.api_port_input.setValue(int(self.settings.get("api_port") or 1888))
        if hasattr(self, "nina_sequence_dir_input"):
            self.nina_sequence_dir_input.setText(
                str(self.settings.get("nina_sequence_import_dir") or "")
            )
        if hasattr(self, "nina_image_dir_input"):
            self.nina_image_dir_input.setText(
                str(self.settings.get("nina_image_dir") or "")
            )
        if hasattr(self, "equipment_prep_template_input"):
            self.equipment_prep_template_input.setText(
                str(self.settings.get("equipment_prep_template_path") or "")
            )
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
                "nina_sequence_import_dir": (
                    self.nina_sequence_dir_input.text().strip()
                    if hasattr(self, "nina_sequence_dir_input")
                    else str(self.settings.get("nina_sequence_import_dir") or "")
                ),
                "nina_image_dir": (
                    self.nina_image_dir_input.text().strip()
                    if hasattr(self, "nina_image_dir_input")
                    else str(self.settings.get("nina_image_dir") or "")
                ),
                "equipment_prep_template_path": (
                    self.equipment_prep_template_input.text().strip()
                    if hasattr(self, "equipment_prep_template_input")
                    else str(self.settings.get("equipment_prep_template_path") or "")
                ),
                "installed_version": self.installed_version_input.text().strip(),
                "update_manifest_url": self.update_url_input.text().strip(),
                "auto_check_updates": self.auto_check_updates_checkbox.isChecked(),
                "auto_download_updates": self.auto_download_updates_checkbox.isChecked(),
            }
        )
        return data

    def save_from_ui(self):
        self.settings = save_settings(self._settings_from_ui())

    def browse_nina_sequence_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select N.I.N.A. sequence folder",
            self.nina_sequence_dir_input.text().strip()
            or str(Path.home() / "Documents"),
        )
        if folder:
            self.nina_sequence_dir_input.setText(folder)
            self.save_from_ui()

    def browse_nina_image_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select N.I.N.A. image save folder",
            self.nina_image_dir_input.text().strip() or str(Path.home() / "Pictures"),
        )
        if folder:
            self.nina_image_dir_input.setText(folder)
            self.save_from_ui()
            self._update_session_status_cards()

    def browse_equipment_prep_template(self):
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose N.I.N.A. equipment-prep sample JSON",
            self.equipment_prep_template_input.text().strip()
            or r"D:\Dropbox\N.I.N.A\FZAstro_EquipmentPrepSample.json",
            "N.I.N.A. JSON (*.json);;All files (*.*)",
        )
        if selected:
            self.equipment_prep_template_input.setText(selected)
            self.save_from_ui()

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
            "No bundled FZAstro Imaging executable was found yet. Build or copy FZAstroImaging.exe into bundled_apps/FZAstroImaging, then click Find again.",
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
        bundle_hint = "" if exists else f" Â· expected at {path}"
        self.status_label.setText(
            f"Status: {'running' if running else 'not running'} Â· bundle executable {'found' if exists else 'missing'}{bundle_hint}"
        )
        self._update_session_status_cards()

    def _should_poll_nina_api_state(self) -> bool:
        return bool(
            self.api_sequence_loaded
            or self.session_started_at
            or self.api_loaded_sequence_name
            or self.settings.get("last_api_sequence_name")
        )

    def refresh_live_session_status(self):
        """Auto-refresh the cockpit status cards while the dialog is open.

        The timer keeps the visible frame count and latest image moving without
        requiring the user to press REFRESH.  It polls N.I.N.A. state only after
        a sequence has been loaded/started, and always refreshes the saved-image
        fallback from the configured image folder.
        """

        if self._live_status_refresh_busy:
            return
        self._live_status_refresh_busy = True
        try:
            self.settings = self._settings_from_ui()
            api_state = self.api_last_state
            if self._should_poll_nina_api_state():
                state = get_sequence_state(self.settings)
                if state.success:
                    self.api_last_state = state.raw
                    api_state = state.raw
            self._update_session_status_cards(api_state)
        finally:
            self._live_status_refresh_busy = False

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

    def open_targets(self):
        main_window = self._main_window_parent()
        if main_window is None or not hasattr(main_window, "open_astro_targets_dialog"):
            QMessageBox.information(
                self,
                "Open TARGETS",
                "Open this panel from the main FZAstro AI window to use TARGETS selection.",
            )
            return
        main_window.open_astro_targets_dialog()
        self.load_selected_target()

    def load_selected_target(self):
        main_window = self._main_window_parent()
        getter = (
            getattr(main_window, "get_pending_imaging_target_from_targets", None)
            if main_window is not None
            else None
        )
        pending = getter() if getter is not None else None
        if not pending:
            self.target_summary_label.setText("No target selected from TARGETS yet.")
            self.notes_output.setPlainText(
                "Open TARGETS, select an available target, then click SEND TO FZASTRO IMAGING. "
                "The selected target will populate this control panel before any N.I.N.A. JSON is generated."
            )
            return None
        pick = dict(pending.get("pick") or pending)
        imaging = dict(pending.get("imaging") or {})
        capture = dict(pending.get("capture") or {})
        framing = dict(pending.get("framing_preview") or {})
        lookup_html = str(pending.get("lookup_html") or "").strip()
        preview_image_path = str(pending.get("preview_image_path") or "").strip()

        self._set_camera_combo_from_imaging(framing, imaging)
        if imaging.get("focal_mm") or imaging.get("focal_length_mm"):
            self.focal_spin.setValue(
                float(
                    imaging.get("focal_mm") or imaging.get("focal_length_mm") or 700.0
                )
            )
        if capture.get("exposure_seconds"):
            self.exposure_spin.setValue(int(capture.get("exposure_seconds") or 60))
        if capture.get("gain") is not None:
            self.gain_spin.setValue(int(capture.get("gain") or 0))

        distance = self._text_from_keys(
            pick, ("distance", "distance_text", "dist", "distance_ly", "distance_mly")
        )
        distance_part = f" Â· Distance {distance}" if distance else ""
        self.target_summary_label.setText(
            f"Selected from TARGETS: {pick.get('name') or 'â€”'} Â· Type: {pick.get('type') or 'â€”'}{distance_part}\n"
            f"RA {pick.get('ra') or 'â€”'} Â· Dec {pick.get('dec') or 'â€”'} Â· Mag {pick.get('mag') or 'â€”'} Â· Size {pick.get('size') or 'â€”'}\n"
            f"Camera {self._selected_camera_imaging().get('preset_name') or 'â€”'} Â· Focal {float(self.focal_spin.value()):.0f} mm Â· "
            f"Exposure {int(self.exposure_spin.value())} s Â· Gain {int(self.gain_spin.value())} Â· Frames auto from SEEING"
        )
        self.window_summary_label.setText(
            "Selected target is staged from TARGETS. Click CONFIRM + LOAD to calculate the best SEEING window and auto frames."
        )
        self._set_target_preview_image(preview_image_path)
        if lookup_html:
            self.lookup_details_browser.setHtml(lookup_html)
        else:
            self.lookup_details_browser.setHtml(
                "<html><body style='background:#0f1318;color:#9ca8b4;font-family:Segoe UI;font-size:10px;'>"
                "No LOOKUP details were attached. Open TARGETS, let the LOOKUP panel finish, then send the target again."
                "</body></html>"
            )
        self.lookup_summary_label.setText(
            "Selected target, LOOKUP details, sky preview, camera, focal length, exposure, and gain came from TARGETS. "
            "Frames will be calculated from the best SEEING imaging window."
        )
        self.notes_output.setPlainText(
            "Loaded selected TARGETS object into Imaging Control. The camera, focal length, exposure, gain, thumbnail, and lookup details were populated from TARGETS.\n\n"
            "Next: click CONFIRM + LOAD INTO N.I.N.A. Frames are calculated from the best SEEING imaging window. "
            "N.I.N.A. JSON is still generated only after final confirmation."
        )
        self.refresh_framing_preview()
        return pick

    def _text_from_keys(self, data: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def _set_target_preview_image(self, image_path: str):
        path = Path(str(image_path or "")).expanduser()
        if not image_path or not path.exists():
            self.target_preview_label.setPixmap(QPixmap())
            self.target_preview_label.setText("No frame preview attached.")
            self.target_preview_label.setToolTip("")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.target_preview_label.setPixmap(QPixmap())
            self.target_preview_label.setText("Frame preview could not be loaded.")
            self.target_preview_label.setToolTip(str(path))
            return
        self.target_preview_label.setText("")
        self.target_preview_label.setToolTip(str(path))
        self.target_preview_label.setPixmap(
            pixmap.scaled(
                self.target_preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def prepare_selected_target(self):
        pick = self.load_selected_target()
        if not pick:
            QMessageBox.information(
                self,
                "Prepare selected target",
                "Select a target in TARGETS first, then send it to FZASTRO IMAGING.",
            )
            return
        main_window = self._main_window_parent()
        runner = (
            getattr(main_window, "prepare_pending_imaging_target_plan", None)
            if main_window is not None
            else None
        )
        if runner is None:
            QMessageBox.information(
                self,
                "Prepare selected target",
                "Open this panel from the main FZAstro AI window to prepare the selected TARGETS object.",
            )
            return
        self._save_camera_selection_to_parent()
        self._draft_poll_started_at = time.time()
        self._draft_poll_deadline = self._draft_poll_started_at + 90.0
        self._set_plan_progress("Preparing draft from SEEING/TARGETSâ€¦", busy=True)
        ok = runner(
            exposure_seconds=int(self.exposure_spin.value()),
            gain=int(self.gain_spin.value()),
        )
        if ok is False:
            self._hide_plan_progress()
            return
        self._draft_poll_timer.start()
        self.notes_output.setPlainText(
            "Requested a draft imaging plan for the selected TARGETS object.\n\n"
            "FZAstro is now evaluating structured SEEING rows, moon/darkness, cloud, transparency, target visibility, and the confirmed exposure/gain. "
            "The frames count will be calculated from the best SEEING window. N.I.N.A. JSON is still generated only after final confirmation."
        )

    def _poll_latest_draft_after_prepare(self):
        path = self._latest_plan_json()
        now = time.time()
        if path is not None:
            try:
                is_new = path.stat().st_mtime >= max(
                    0.0, self._draft_poll_started_at - 1.0
                )
            except Exception:
                is_new = True
            if is_new:
                self._draft_poll_timer.stop()
                continue_load = bool(self._continue_confirm_load_after_prepare)
                self._continue_confirm_load_after_prepare = False
                self._set_plan_progress("Draft ready Â· loading reviewâ€¦", 92)
                self.load_latest_draft(show_missing=False)
                if continue_load:
                    self._set_plan_progress(
                        "Draft ready Â· continuing CONFIRM + LOADâ€¦", 100
                    )
                    QTimer.singleShot(250, self.confirm_generate_and_load_via_api)
                else:
                    self._set_plan_progress(
                        "Draft ready Â· review target, framing, and capture", 100
                    )
                    QTimer.singleShot(1800, self._hide_plan_progress)
                return
        if self._draft_poll_deadline and now > self._draft_poll_deadline:
            self._draft_poll_timer.stop()
            self._continue_confirm_load_after_prepare = False
            self._set_plan_progress(
                "Draft still running or unavailable Â· use LOAD LATEST DRAFT", 50
            )
            QTimer.singleShot(4500, self._hide_plan_progress)
            return
        self._set_plan_progress(
            "Evaluating SEEING window and target visibilityâ€¦", busy=True
        )

    def _latest_plan_json(self) -> Path | None:
        if not IMAGING_PLAN_DIR.exists():
            return None
        candidates = []
        for path in IMAGING_PLAN_DIR.rglob("*.json"):
            if path.name.endswith(".nina-review.json") or path.name.endswith(
                ".nina-sequence.json"
            ):
                continue
            candidates.append(path)
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def load_latest_draft_if_available(self):
        if self._latest_plan_json() is not None:
            self.load_latest_draft(show_missing=False)

    def load_latest_draft(self, show_missing: bool = True):
        path = self._latest_plan_json()
        if path is None:
            if show_missing:
                QMessageBox.information(
                    self,
                    "Load latest draft",
                    "No draft plan JSON was found yet. Prepare a target first.",
                )
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            plan = dict(payload.get("plan") or {})
        except Exception as exc:
            QMessageBox.warning(self, "Load latest draft", str(exc))
            return
        self.current_plan_json = path
        self.current_plan_data = plan
        self._populate_plan_fields(plan)
        self.notes_output.setPlainText(
            f"Loaded draft:\n{path}\n\n"
            "Review/adjust framing and capture values. The N.I.N.A. sequence JSON is generated only after confirmation."
        )

    def _current_plan_file_ready(self) -> bool:
        """Return True only when the selected draft JSON still exists on disk."""

        if self.current_plan_json is not None:
            try:
                if Path(self.current_plan_json).exists():
                    return True
            except Exception:
                pass
        self.current_plan_json = None
        latest = self._latest_plan_json()
        if latest is not None:
            self.load_latest_draft(show_missing=False)
            try:
                return bool(
                    self.current_plan_json and Path(self.current_plan_json).exists()
                )
            except Exception:
                return False
        return False

    def _missing_current_plan_message(self) -> str:
        return (
            "The draft imaging-plan JSON is no longer available on disk. "
            "This can happen after cleaning Documents/FZAstroAI/Imaging Plans or when a stale plan was restored from a previous run.\n\n"
            "Click 1 Â· OPEN TARGETS, send the target to FZASTRO IMAGING again, then click 2 Â· CONFIRM + LOAD."
        )

    def _populate_plan_fields(self, plan: dict):
        window = dict(plan.get("window") or {})
        framing = dict(plan.get("framing") or {})
        imaging = dict(plan.get("imaging") or {})
        self.target_summary_label.setText(
            f"Target: {plan.get('target_name') or 'â€”'} Â· Type: {plan.get('target_type') or 'â€”'} Â· "
            f"RA {plan.get('ra') or 'â€”'} Â· Dec {plan.get('dec') or 'â€”'} Â· Mag {plan.get('magnitude') or 'â€”'} Â· Size {plan.get('size') or 'â€”'}"
        )
        self.window_summary_label.setText(
            f"Window: {window.get('start_label') or window.get('start_iso') or 'â€”'} â†’ {window.get('end_label') or window.get('end_iso') or 'â€”'} Â· "
            f"Score {window.get('score') or 'â€”'}/100 Â· Cloud {window.get('cloud_pct') if window.get('cloud_pct') is not None else 'â€”'}% Â· "
            f"Seeing {window.get('seeing_text') or 'â€”'} Â· Transparency {window.get('transparency_text') or 'â€”'} Â· "
            f"Moon {window.get('moon_text') or 'â€”'} Â· Astro dark {'yes' if window.get('astro_dark') else 'no'}"
        )
        self.lookup_summary_label.setText(
            "Structured metadata: TARGETS/LOOKUP target details + SEEING backend rows + IMAGING camera profile. Rendered HTML/widget state is not used."
        )
        self._set_camera_combo_from_imaging(framing, imaging)
        self.focal_spin.setValue(
            float(framing.get("focal_length_mm") or imaging.get("focal_mm") or 700.0)
        )
        self.exposure_spin.setValue(
            int(plan.get("exposure_seconds") or framing.get("exposure_seconds") or 60)
        )
        self.gain_spin.setValue(int(plan.get("gain") or framing.get("gain") or 200))
        self.frames_spin.setValue(self._auto_frames_from_current_window())
        # Preserve the TARGETS thumbnail/details in the review panel when the
        # latest draft was created from the staged TARGETS handoff.
        main_window = self._main_window_parent()
        getter = (
            getattr(main_window, "get_pending_imaging_target_from_targets", None)
            if main_window is not None
            else None
        )
        pending = getter() if getter is not None else None
        if isinstance(pending, dict):
            pick = dict(pending.get("pick") or {})
            if (
                str(pick.get("name") or "").strip().casefold()
                == str(plan.get("target_name") or "").strip().casefold()
            ):
                self._set_target_preview_image(
                    str(pending.get("preview_image_path") or "")
                )
                lookup_html = str(pending.get("lookup_html") or "").strip()
                if lookup_html:
                    self.lookup_details_browser.setHtml(lookup_html)
        self.refresh_framing_preview()
        self._update_session_status_cards()

    def _selected_camera_imaging(self) -> dict:
        preset = str(self.camera_combo.currentData() or "585")
        data = normalise_astro_imaging(
            {"preset": preset, "focal_mm": float(self.focal_spin.value())}
        )
        return dict(data)

    def _set_camera_combo_from_imaging(self, framing: dict, imaging: dict):
        preset = str(imaging.get("preset") or "").strip()
        camera_name = str(
            framing.get("camera_model")
            or imaging.get("preset_name")
            or imaging.get("camera_name")
            or ""
        ).casefold()
        if not preset:
            for key, preset_info in CAMERA_PRESETS.items():
                if str(preset_info.get("name") or "").casefold() == camera_name:
                    preset = str(key)
                    break
        index = self.camera_combo.findData(preset or "585")
        self.camera_combo.setCurrentIndex(
            index if index >= 0 else max(0, self.camera_combo.findData("585"))
        )

    def _save_camera_selection_to_parent(self):
        main_window = self._main_window_parent()
        if main_window is not None and hasattr(
            main_window, "set_current_astro_imaging"
        ):
            try:
                main_window.set_current_astro_imaging(self._selected_camera_imaging())
            except Exception:
                pass

    def _auto_frames_from_current_window(self) -> int:
        plan = dict(self.current_plan_data or {})
        window = dict(plan.get("window") or {})
        try:
            start = str(window.get("start_iso") or "").replace("Z", "+00:00")
            end = str(window.get("end_iso") or "").replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            duration_minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
        except Exception:
            return int(plan.get("frames") or 1)
        usable_seconds = max(0, duration_minutes * 60 - 10 * 60)
        frames = max(1, int(usable_seconds // max(1, int(self.exposure_spin.value()))))
        return min(frames, 500)

    def _current_imaging_for_preview(self) -> dict:
        plan = dict(self.current_plan_data or {})
        imaging = dict(plan.get("imaging") or {})
        imaging.update(self._selected_camera_imaging())
        imaging["focal_mm"] = float(self.focal_spin.value())
        imaging["reducer_factor"] = 1.0
        return imaging

    def refresh_framing_preview(self):
        if self.current_plan_data is None:
            return
        auto_frames = self._auto_frames_from_current_window()
        if int(self.frames_spin.value()) != auto_frames:
            self.frames_spin.setValue(auto_frames)
        try:
            framing = calculate_framing_details(
                target_size=self.current_plan_data.get("size"),
                imaging=self._current_imaging_for_preview(),
                exposure_seconds=int(self.exposure_spin.value()),
                gain=int(self.gain_spin.value()),
                frames=int(auto_frames),
            )
        except Exception as exc:
            self.framing_result_label.setText(f"Framing calculation failed: {exc}")
            return
        self.framing_result_label.setText(
            f"FOV {framing['fov_width_deg']}Â° Ã— {framing['fov_height_deg']}Â° Â· "
            f"scale {framing['image_scale_arcsec_px']} arcsec/px Â· "
            f"focal {framing['effective_focal_length_mm']} mm Â· "
            f"target size {framing.get('target_size_arcmin') or 'â€”'} arcmin Â· "
            f"fit {framing['target_fit']} Â· total {framing['estimated_total_minutes']} min"
        )

    def confirm_generate_nina_json(self):
        if not self._current_plan_file_ready():
            QMessageBox.information(
                self, "Confirm N.I.N.A. JSON", self._missing_current_plan_message()
            )
            self.execution_status_label.setText(
                "Draft plan missing Â· send the target from TARGETS again"
            )
            return
        answer = QMessageBox.question(
            self,
            "Confirm N.I.N.A. JSON",
            "Generate the importable .nina-sequence.json now using the displayed target, framing, focal length, exposure, gain, and automatically calculated frames?\n\nThis still does not slew, guide, capture, or start the sequence.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_plan_progress(
            "Generating confirmed N.I.N.A. sequence JSONâ€¦", busy=True
        )
        try:
            result = confirm_imaging_plan_for_nina(
                self.current_plan_json,
                camera_model=str(
                    self._selected_camera_imaging().get("preset_name") or ""
                ),
                focal_length_mm=float(self.focal_spin.value()),
                reducer_factor=1.0,
                exposure_seconds=int(self.exposure_spin.value()),
                gain=int(self.gain_spin.value()),
                frames=self._auto_frames_from_current_window(),
            )
        except Exception as exc:
            self._hide_plan_progress()
            QMessageBox.warning(self, "Confirm N.I.N.A. JSON", str(exc))
            return
        self._set_plan_progress("N.I.N.A. sequence JSON generated", 100)
        self.current_plan_data = (
            json.loads(Path(result.plan_json_path).read_text(encoding="utf-8")).get(
                "plan"
            )
            or {}
        )
        self._populate_plan_fields(self.current_plan_data)
        self.notes_output.setPlainText(
            "Confirmed and generated N.I.N.A. Advanced Sequencer JSON:\n\n"
            f"{result.nina_sequence_path}\n\n"
            "Use OPEN LATEST PLAN IN IMAGING to launch/open it for review. No hardware action was requested."
        )
        QTimer.singleShot(1800, self._hide_plan_progress)
        QMessageBox.information(
            self,
            "N.I.N.A. JSON generated",
            "The .nina-sequence.json file was generated after confirmation.",
        )

    def confirm_generate_and_load_via_api(self):
        """One-click safe handoff: confirm JSON, copy to N.I.N.A., load, and verify state.

        This intentionally stops before START.  START SESSION remains a separate,
        explicit hardware-action confirmation and internally arms the loaded plan.
        """

        if not self._current_plan_file_ready():
            self._continue_confirm_load_after_prepare = True
            self.prepare_selected_target()
            if (
                not self._draft_poll_timer.isActive()
                and not self._current_plan_file_ready()
            ):
                self._continue_confirm_load_after_prepare = False
            if not self._current_plan_file_ready():
                self.execution_status_label.setText(
                    "Preparing selected TARGETS object. Step 2 will continue automatically when the draft is ready."
                )
                return

        self.save_from_ui()
        if not str(self.settings.get("nina_sequence_import_dir") or "").strip():
            if self._side_panel_hidden:
                self.toggle_side_panel()
            QMessageBox.information(
                self,
                "N.I.N.A. sequence folder required",
                "Set CONFIG â†’ N.I.N.A. sequence folder first.\n\n"
                "For the working setup, use:\nD:\\Dropbox\\N.I.N.A",
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm + load into N.I.N.A.",
            "Generate the confirmed N.I.N.A. Advanced Sequencer JSON and load it into N.I.N.A. through the API now?\n\n"
            "This will copy a plain .json file into the configured N.I.N.A. sequence folder, call list-available, load by sequenceName, and verify API state.\n\n"
            "It will NOT arm, start, slew, guide, autofocus, or capture.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.execution_armed = False
        self.api_sequence_loaded = False
        self.api_loaded_sequence_name = ""
        self.api_last_state = None
        self._set_plan_progress(
            "Opening N.I.N.A. if needed, then generating and loading sequenceâ€¦",
            busy=True,
        )

        try:
            generated = confirm_imaging_plan_for_nina(
                self.current_plan_json,
                camera_model=str(
                    self._selected_camera_imaging().get("preset_name") or ""
                ),
                focal_length_mm=float(self.focal_spin.value()),
                reducer_factor=1.0,
                exposure_seconds=int(self.exposure_spin.value()),
                gain=int(self.gain_spin.value()),
                frames=self._auto_frames_from_current_window(),
            )
            self.current_plan_data = (
                json.loads(
                    Path(generated.plan_json_path).read_text(encoding="utf-8")
                ).get("plan")
                or {}
            )
            self._populate_plan_fields(self.current_plan_data)
            plan = dict(self.current_plan_data or {})
            sequence_path = Path(
                str(plan.get("nina_sequence_path") or generated.nina_sequence_path)
            )
        except Exception as exc:
            self._hide_plan_progress()
            QMessageBox.warning(
                self,
                "Confirm + load into N.I.N.A.",
                f"Could not generate confirmed sequence:\n\n{exc}",
            )
            return

        load_result = load_confirmed_sequence_via_api(sequence_path, self.settings)
        if not load_result.success:
            self._hide_plan_progress()
            self.execution_status_label.setText(
                f"N.I.N.A. API load failed Â· {load_result.message}"
            )
            QMessageBox.warning(
                self, "Confirm + load into N.I.N.A.", load_result.message
            )
            return

        self.api_sequence_loaded = True
        self.api_loaded_sequence_name = load_result.sequence_name
        self.api_last_state = load_result.state
        self.settings["last_api_sequence_name"] = load_result.sequence_name
        self.settings = save_settings(self.settings)
        self._update_session_status_cards(load_result.state)
        self._set_plan_progress(
            "Confirmed sequence loaded and verified in N.I.N.A.", 100
        )
        self.execution_status_label.setText(
            f"N.I.N.A. API loaded and verified: {load_result.sequence_name} Â· Next: review, then START SESSION only when ready."
        )
        self.notes_output.setPlainText(
            "One-step N.I.N.A. handoff complete.\n\n"
            f"Generated source: {sequence_path}\n"
            f"Loaded sequenceName: {load_result.sequence_name}\n"
            f"Method: {load_result.method}\n"
            f"N.I.N.A. sequence folder: {self.settings.get('nina_sequence_import_dir') or 'â€”'}\n\n"
            "Next: review the plan in N.I.N.A. Advanced Sequencer, then use START SESSION only when ready. "
            "START remains a separate explicit hardware-action confirmation."
        )
        QTimer.singleShot(2200, self._hide_plan_progress)

    def equipment_prep_power_on(self):
        """Review/load an explicit N.I.N.A. equipment-prep template without starting it."""

        self.save_from_ui()
        configured = str(
            self.settings.get("equipment_prep_template_path") or ""
        ).strip()
        sample_path = Path(
            configured or r"D:\Dropbox\N.I.N.A\FZAstro_EquipmentPrepSample.json"
        ).expanduser()
        basic_text = (
            "Basic equipment-prep steps are already present in generated FZAstro target sequences when supported by the template: "
            "EQUIPMENT_CHECK_Container, Wait for Time, Unpark Scope, Set Tracking, and Cool Camera.\n\n"
            "For real switch/power/dew/cover/device startup, FZAstro needs your own N.I.N.A. Advanced Sequencer sample because instruction blocks and device names depend on your local setup."
        )
        if not sample_path.exists():
            self.notes_output.setPlainText(
                basic_text
                + "\n\nCreate or upload this sample template, then set it in CONFIG:\n"
                + r"D:\Dropbox\N.I.N.A\FZAstro_EquipmentPrepSample.json"
                + "\n\nFZAstro will load it for review only. N.I.N.A. must execute it only after your explicit confirmation."
            )
            self.execution_status_label.setText(
                "Equipment prep sample not configured Â· using basic generated-sequence prep notes only"
            )
            QMessageBox.information(
                self,
                "Equipment prep sample needed",
                basic_text
                + "\n\nPlease create/upload:\n"
                + r"D:\Dropbox\N.I.N.A\FZAstro_EquipmentPrepSample.json",
            )
            self._update_session_status_cards()
            return
        if not str(self.settings.get("nina_sequence_import_dir") or "").strip():
            if self._side_panel_hidden:
                self.toggle_side_panel()
            QMessageBox.information(
                self,
                "N.I.N.A. sequence folder required",
                "Set CONFIG â†’ N.I.N.A. sequence folder first so the equipment-prep sample can be copied and loaded for review.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "Load equipment prep into N.I.N.A.",
            "Load the equipment-prep sample into N.I.N.A. Advanced Sequencer for review?\n\n"
            "FZAstro will copy/load the JSON through the API only. It will NOT start execution.\n\n"
            "After running equipment prep manually in N.I.N.A., load the real target sequence again with step 2 before using START SESSION.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_plan_progress(
            "Loading equipment-prep sample for reviewâ€¦", busy=True
        )
        result = load_confirmed_sequence_via_api(sample_path, self.settings)
        if not result.success:
            self._hide_plan_progress()
            self.execution_status_label.setText(
                f"Equipment prep load failed Â· {result.message}"
            )
            QMessageBox.warning(self, "Equipment prep load", result.message)
            return
        # Protection: loading the prep template changes N.I.N.A.'s current sequence,
        # but FZAstro should not treat it as the target plan that can be started by
        # the main START SESSION button.
        self.api_sequence_loaded = False
        self.api_loaded_sequence_name = result.sequence_name
        self.api_last_state = result.state
        self._update_session_status_cards(result.state)
        self._set_plan_progress("Equipment-prep sample loaded for N.I.N.A. review", 100)
        self.execution_status_label.setText(
            "Equipment-prep sample loaded for review Â· run it manually in N.I.N.A., then reload the target plan"
        )
        self.notes_output.setPlainText(
            "Equipment-prep sample loaded into N.I.N.A. for review only.\n\n"
            f"Template: {sample_path}\n"
            f"Loaded sequenceName: {result.sequence_name}\n\n"
            "FZAstro did not start execution. If you run equipment prep in N.I.N.A., return here and click 2 Â· CONFIRM + LOAD again before START SESSION for the target session."
        )
        QTimer.singleShot(2200, self._hide_plan_progress)

    def _ensure_confirmed_plan_for_execution(self) -> Path | None:
        if not self._current_plan_file_ready():
            QMessageBox.information(
                self, "Draft plan missing", self._missing_current_plan_message()
            )
            return None
        plan = dict(self.current_plan_data or {})
        if not bool(plan.get("nina_sequence_confirmed")):
            QMessageBox.information(
                self,
                "Confirm N.I.N.A. JSON first",
                "Generate the confirmed .nina-sequence.json before arming or reporting a session.",
            )
            return None
        sequence_path = Path(str(plan.get("nina_sequence_path") or ""))
        if not sequence_path.exists():
            QMessageBox.information(
                self,
                "Confirmed sequence missing",
                "The plan is marked confirmed, but the .nina-sequence.json file was not found. Generate it again.",
            )
            return None
        return Path(self.current_plan_json)

    def arm_execution_session(self):
        plan_json = self._ensure_confirmed_plan_for_execution()
        if plan_json is None:
            return
        answer = QMessageBox.question(
            self,
            "Arm imaging session",
            "Arm this confirmed plan for N.I.N.A. API execution handoff?\n\n"
            "FZAstro will allow START SESSION only after the confirmed sequence is loaded into N.I.N.A. through the API. "
            "START SESSION is a real hardware-action request and remains separate from planning/generation.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.execution_armed = True
        self.execution_status_label.setText(
            "Execution mode: READY Â· START SESSION is available because the plan must already be loaded and verified."
        )
        self.notes_output.setPlainText(
            "Session armed for the confirmed and API-loaded plan. Next: START SESSION only when N.I.N.A., equipment, or simulators are ready.\n\n"
            "FZAstro will create a session report from the structured plan data and N.I.N.A. API state. "
            "No automatic start happens after plan generation or loading."
        )

    def test_nina_api_connection(self):
        self.save_from_ui()
        self._set_plan_progress("Testing N.I.N.A. APIâ€¦", busy=True)
        result = test_nina_api(self.settings)
        self._set_plan_progress("N.I.N.A. API test complete", 100)
        if result.success:
            self.execution_status_label.setText(
                f"N.I.N.A. API connected Â· version {result.response}"
            )
            self.notes_output.setPlainText(
                f"N.I.N.A. API connected successfully.\n\nVersion: {result.response}\n"
                f"Base: http://{self.settings.get('api_host')}:{self.settings.get('api_port')}/v2/api"
            )
        else:
            self.execution_status_label.setText(
                f"N.I.N.A. API connection failed Â· {result.message}"
            )
            QMessageBox.warning(self, "N.I.N.A. API", result.message)
        QTimer.singleShot(1600, self._hide_plan_progress)

    def list_nina_api_sequences(self):
        self.save_from_ui()
        self._set_plan_progress("Listing N.I.N.A. API sequencesâ€¦", busy=True)
        result = list_available_sequences(self.settings)
        self._set_plan_progress("N.I.N.A. API sequence list complete", 100)
        if not result.success:
            QMessageBox.warning(self, "N.I.N.A. API sequences", result.message)
            QTimer.singleShot(1600, self._hide_plan_progress)
            return
        names = result.response if isinstance(result.response, list) else []
        self.notes_output.setPlainText(
            "N.I.N.A. API visible sequences:\n\n"
            + "\n".join(f"- {name}" for name in names)
        )
        self.execution_status_label.setText(
            f"N.I.N.A. API sequences visible: {len(names)}"
        )
        QTimer.singleShot(1600, self._hide_plan_progress)

    def load_confirmed_plan_via_api(self):
        plan_json = self._ensure_confirmed_plan_for_execution()
        if plan_json is None:
            return
        plan = dict(self.current_plan_data or {})
        sequence_path = Path(str(plan.get("nina_sequence_path") or ""))
        self.save_from_ui()
        self._set_plan_progress(
            "Loading confirmed plan through N.I.N.A. APIâ€¦", busy=True
        )
        result = load_confirmed_sequence_via_api(sequence_path, self.settings)
        if not result.success:
            self.api_sequence_loaded = False
            self.api_loaded_sequence_name = ""
            self.api_last_state = None
            self._hide_plan_progress()
            if sequence_path.parent.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(sequence_path.parent)))
            QMessageBox.warning(
                self,
                "Load plan via N.I.N.A. API",
                f"{result.message}\n\nSet CONFIG â†’ N.I.N.A. sequence folder to the real Advanced Sequencer folder that appears in /sequence/list-available. For this workflow it can be D:\\Dropbox\\N.I.N.A when N.I.N.A. lists files saved there.",
            )
            self.execution_status_label.setText(
                f"N.I.N.A. API load failed Â· {result.message}"
            )
            return
        self.api_sequence_loaded = True
        self.api_loaded_sequence_name = result.sequence_name
        self.api_last_state = result.state
        self.settings["last_api_sequence_name"] = result.sequence_name
        self.settings = save_settings(self.settings)
        self._update_session_status_cards(result.state)
        self._set_plan_progress("Confirmed plan loaded into N.I.N.A. API", 100)
        self.execution_status_label.setText(
            f"N.I.N.A. API loaded sequence: {result.sequence_name}"
        )
        self.notes_output.setPlainText(
            "Confirmed sequence loaded into N.I.N.A. through API.\n\n"
            f"Sequence name: {result.sequence_name}\n"
            f"Method: {result.method}\n"
            f"Source file: {result.sequence_path}\n\n"
            "Review N.I.N.A. Advanced Sequencer state before starting. Legacy Sequencer may remain empty. START still requires the START SESSION confirmation."
        )
        QTimer.singleShot(1800, self._hide_plan_progress)

    def check_nina_api_state(self):
        self.save_from_ui()
        self._set_plan_progress("Reading N.I.N.A. sequence stateâ€¦", busy=True)
        result = get_sequence_state(self.settings)
        self._set_plan_progress("N.I.N.A. sequence state loaded", 100)
        if not result.success:
            QMessageBox.warning(self, "N.I.N.A. sequence state", result.message)
            QTimer.singleShot(1600, self._hide_plan_progress)
            return
        self.api_last_state = result.raw
        self._update_session_status_cards(result.raw)
        self.notes_output.setPlainText(json.dumps(result.raw, indent=2, sort_keys=True))
        self.execution_status_label.setText("N.I.N.A. sequence state loaded from API")
        QTimer.singleShot(1600, self._hide_plan_progress)

    def start_armed_session_via_api(self):
        if not getattr(self, "api_sequence_loaded", False):
            QMessageBox.information(
                self,
                "Sequence not loaded",
                "Click 2 Â· CONFIRM + LOAD first and confirm the Advanced Sequencer shows the loaded target.",
            )
            return
        state = get_sequence_state(self.settings)
        if not state.success:
            QMessageBox.warning(
                self,
                "N.I.N.A. state not verified",
                "FZAstro could not verify the loaded sequence state through the N.I.N.A. API. Use CHECK STATE in the side panel, or reload the confirmed sequence before starting.\n\n"
                + state.message,
            )
            return
        self.api_last_state = state.raw
        self._update_session_status_cards(state.raw)

        answer = QMessageBox.warning(
            self,
            "Arm + start sequence via N.I.N.A. API",
            "This will arm the currently loaded FZAstro plan and send START to N.I.N.A.\n\n"
            "START SESSION is a real hardware-action request. It may slew, center, guide, autofocus, expose, and run the loaded Advanced Sequencer plan through N.I.N.A.\n\n"
            "Continue only if the plan has been reviewed in N.I.N.A. Advanced Sequencer and your equipment or simulators are ready.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.execution_armed = True
        previous_session_started_at = self.session_started_at
        start_request_epoch = time.time()
        self._set_plan_progress("Sending START to N.I.N.A.â€¦", busy=True)
        result = start_sequence_via_api(self.settings)
        self._set_plan_progress("START request complete", 100)
        if not result.success:
            self.execution_armed = False
            self.session_started_at = previous_session_started_at
            QMessageBox.warning(self, "START SESSION", result.message)
            self.execution_status_label.setText(
                f"START SESSION failed Â· {result.message}"
            )
            return
        self.session_started_at = start_request_epoch
        state_after_start = get_sequence_state(self.settings)
        if state_after_start.success:
            self.api_last_state = state_after_start.raw
            self._update_session_status_cards(state_after_start.raw)
        else:
            self._update_session_status_cards()
        self.execution_status_label.setText(
            "START SESSION sent Â· monitor N.I.N.A. sequence state"
        )
        self.notes_output.setPlainText(
            "START SESSION request accepted by N.I.N.A.\n\n"
            f"Loaded sequence: {self.api_loaded_sequence_name or self.settings.get('last_api_sequence_name') or 'â€”'}\n\n"
            "Use STOP / ABORT if needed. Use SESSION REPORT after or during the run to capture current API state and highlights."
        )
        QTimer.singleShot(1800, self._hide_plan_progress)

    def stop_session_via_api(self):
        answer = QMessageBox.warning(
            self,
            "Stop / abort via N.I.N.A. API",
            "Send STOP / ABORT to N.I.N.A. API? This may interrupt the running sequence.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_plan_progress("Sending STOP / ABORT VIA APIâ€¦", busy=True)
        result = stop_sequence_via_api(self.settings)
        self._set_plan_progress("STOP / ABORT request complete", 100)
        if not result.success:
            QMessageBox.warning(self, "STOP / ABORT VIA API", result.message)
            self.execution_status_label.setText(
                f"STOP / ABORT failed Â· {result.message}"
            )
            return
        state_after_stop = get_sequence_state(self.settings)
        if state_after_stop.success:
            self.api_last_state = state_after_stop.raw
            self._update_session_status_cards(state_after_stop.raw)
        else:
            self._update_session_status_cards()
        self.execution_status_label.setText("STOP / ABORT VIA API sent")
        self.notes_output.setPlainText(
            f"STOP / ABORT response:\n\n{json.dumps(result.raw, indent=2, sort_keys=True)}"
        )
        QTimer.singleShot(1800, self._hide_plan_progress)

    def _state_first_value(self, node, key: str):
        if isinstance(node, dict):
            if key in node and node.get(key) not in (None, ""):
                return node.get(key)
            for value in node.values():
                found = self._state_first_value(value, key)
                if found not in (None, ""):
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._state_first_value(value, key)
                if found not in (None, ""):
                    return found
        return None

    def _state_first_named_item(self, node, name_fragment: str) -> dict:
        fragment = str(name_fragment or "").casefold()
        if isinstance(node, dict):
            name = str(node.get("Name") or "").casefold()
            if fragment and fragment in name:
                return dict(node)
            for value in node.values():
                found = self._state_first_named_item(value, fragment)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = self._state_first_named_item(value, fragment)
                if found:
                    return found
        return {}

    def _session_report_highlights(
        self, report, plan: dict, api_state: dict | None
    ) -> str:
        window = dict(plan.get("window") or {})
        framing = dict(plan.get("framing") or {})
        location = dict(plan.get("location") or {})
        target_name = str(
            plan.get("target_name")
            or self._state_first_value(api_state, "TargetName")
            or "â€”"
        )
        state_target = (
            self._state_first_value(api_state, "TargetName") if api_state else None
        )
        exposure_item = (
            self._state_first_named_item(api_state, "Take Exposure")
            if api_state
            else {}
        )
        captured = (
            self._state_first_value_any(
                api_state,
                ("Completed", "CompletedCount", "CompletedFrames", "CapturedFrames"),
            )
            if api_state
            else None
        )
        fallback_captured, session_folder_count, filename_count = (
            self._image_capture_counts(self.session_started_at)
        )
        frames = plan.get("frames") or "â€”"
        captured_text = self._captured_frame_text(
            captured, fallback_captured, session_folder_count, filename_count
        )
        exposure = (
            exposure_item.get("ExposureTime") or plan.get("exposure_seconds") or "â€”"
        )
        gain = (
            exposure_item.get("Gain")
            if exposure_item.get("Gain") is not None
            else plan.get("gain")
        )
        total_minutes = (
            plan.get("estimated_total_minutes")
            or framing.get("estimated_total_minutes")
            or "â€”"
        )
        score = window.get("score") if window.get("score") is not None else "â€”"
        cloud = (
            window.get("cloud_pct") if window.get("cloud_pct") is not None else "â€”"
        )
        site = (
            location.get("name")
            or location.get("label")
            or location.get("site_name")
            or "â€”"
        )
        bortle = (
            location.get("bortle")
            or dict(location.get("sky_quality") or {}).get("bortle")
            or "â€”"
        )
        api_line = f"Loaded API sequence: {self.api_loaded_sequence_name or self.settings.get('last_api_sequence_name') or 'â€”'}"
        if state_target:
            api_line += f" Â· API target: {state_target}"
        return "\n".join(
            [
                "SESSION REPORT HIGHLIGHTS",
                "",
                f"Target: {target_name} Â· Type: {plan.get('target_type') or 'â€”'}",
                f"Window: {window.get('start_label') or window.get('start_iso') or 'â€”'} â†’ {window.get('end_label') or window.get('end_iso') or 'â€”'}",
                f"Conditions: score {score}/100 Â· cloud {cloud}% Â· seeing {window.get('seeing_text') or 'â€”'} Â· transparency {window.get('transparency_text') or 'â€”'} Â· moon {window.get('moon_text') or 'â€”'}",
                f"Capture: planned {frames} Ã— {exposure}s Â· captured {captured_text} Â· gain {gain if gain is not None else 'â€”'} Â· estimated {total_minutes} min",
                f"Framing: {framing.get('camera_model') or 'â€”'} Â· {framing.get('effective_focal_length_mm') or framing.get('focal_length_mm') or 'â€”'} mm Â· fit {framing.get('target_fit') or 'â€”'}",
                f"Site: {site} Â· Bortle {bortle} Â· timezone {location.get('tz') or location.get('timezone') or 'â€”'}",
                api_line,
                self._format_latest_image_text(self.session_started_at),
                "Safety: report generated from confirmed plan + N.I.N.A. API state; START remains explicit and user-controlled.",
                "",
                "Files:",
                f"Markdown: {report.report_markdown_path}",
                f"JSON: {report.report_json_path}",
            ]
        )

    def generate_session_report(self):
        plan_json = self._ensure_confirmed_plan_for_execution()
        if plan_json is None:
            return
        self._set_plan_progress("Generating session reportâ€¦", busy=True)
        api_state_raw = None
        try:
            api_events = []
            state = get_sequence_state(self.settings)
            if state.success:
                api_state_raw = state.raw
                api_events.append(
                    {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "message": "N.I.N.A. API sequence state snapshot",
                        "api_state": state.raw,
                    }
                )
            latest_image = self._latest_image_for_status(self.session_started_at)
            if latest_image is not None:
                api_events.append(
                    {
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "message": "Latest image fallback snapshot",
                        "last_image_path": str(latest_image),
                    }
                )
            report = create_session_report(
                plan_json,
                status="api_loaded_or_manual_execution",
                execution_mode="nina_api_or_manual_execution",
                notes=(
                    "Report generated from confirmed FZAstro Imaging plan and current N.I.N.A. API state when available. "
                    "Hardware execution remains under explicit user control."
                ),
                events=api_events,
            )
        except Exception as exc:
            self._hide_plan_progress()
            QMessageBox.warning(self, "Generate session report", str(exc))
            return
        self.settings["last_session_report_dir"] = report.session_dir
        self.settings = save_settings(self.settings)
        self._set_plan_progress("Session report generated", 100)
        highlights = self._session_report_highlights(
            report, dict(self.current_plan_data or {}), api_state_raw
        )
        self.notes_output.setPlainText(highlights)
        self.execution_status_label.setText(
            f"Session report generated Â· highlights displayed Â· folder: {report.session_dir}"
        )
        QTimer.singleShot(1800, self._hide_plan_progress)
        QMessageBox.information(
            self,
            "Session report generated",
            "The session report files were written and the key highlights are displayed in the notes panel.",
        )

    def open_latest_session_report_folder(self):
        raw = str(self.settings.get("last_session_report_dir") or "").strip()
        folder = (
            Path(raw)
            if raw
            else Path.home() / "Documents" / "FZAstroAI" / "Imaging Sessions"
        )
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_latest_sequence_in_imaging(self):
        self.save_from_ui()
        sequence = latest_sequence_file(IMAGING_PLAN_DIR)
        if sequence is None:
            QMessageBox.information(
                self,
                "Open latest imaging plan",
                "No confirmed .nina-sequence.json file was found yet. Confirm a draft first.",
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
            "Status: launch/open requested for latest confirmed sequence"
        )
        self.notes_output.setPlainText(
            "Launch/open request sent for confirmed N.I.N.A. Advanced Sequencer file:\n\n"
            f"{result.sequence_path}\n\n"
            "Review the loaded sequence in FZAstro Imaging/N.I.N.A. before starting anything. No slew, guiding, capture, or sequence start was requested."
        )
        QTimer.singleShot(1200, self.refresh_status)

    def open_plans_folder(self):
        IMAGING_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(IMAGING_PLAN_DIR)))

    def show_planning_help(self):
        QMessageBox.information(
            self,
            "Safe imaging-plan workflow",
            "Simple workflow:\n\n"
            "1. OPEN TARGETS and send one selected target to FZASTRO IMAGING.\n"
            "2. CONFIRM + LOAD INTO N.I.N.A. prepares the selected target if needed, generates the confirmed Advanced Sequencer JSON, opens N.I.N.A. if needed, copies it to the configured N.I.N.A. folder, loads by sequenceName, waits for API initialization, and verifies API state.\n"
            "3. START SESSION only after reviewing the loaded plan in N.I.N.A. Advanced Sequencer and confirming hardware/simulator readiness.\n"
            "4. SESSION REPORT writes the files and shows target, conditions, capture, site, API, latest-image, and safety highlights in the notes panel.\n\n"
            "Basic equipment prep is already part of the generated target sequence when supported by the template. Manual tools and diagnostics are in the side panel. The live cockpit auto-refreshes every 15 seconds and uses the current N.I.N.A. image-run folder instead of the entire image root.",
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
                "Enter your FZAstro Imaging update manifest URL first.",
            )
            return
        self.check_update_button.setEnabled(False)
        self.update_status_label.setText("Updates: checkingâ€¦")
        try:
            info = check_for_update(self.settings)
        except Exception as exc:
            self.update_status_label.setText(f"Updates: check failed Â· {exc}")
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
            status += f" Â· published {info.published_at}"
        if not info.has_download:
            status += " Â· no downloadable asset found"
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
        self.update_status_label.setText("Updates: downloading packageâ€¦")
        try:
            path = download_update(self.latest_update)
        except Exception as exc:
            self.update_status_label.setText(f"Updates: download failed Â· {exc}")
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
    if parent is not None and hasattr(parent, "open_workspace_tab"):

        def _clear_reference(_widget=None):
            try:
                if getattr(parent, "nina_control_dialog", None) is _widget:
                    setattr(parent, "nina_control_dialog", None)
            except Exception:
                pass

        def _create_nina_tab():
            dialog = NinaControlDialog(parent)
            setattr(parent, "nina_control_dialog", dialog)
            try:
                dialog.destroyed.connect(lambda *_args: _clear_reference(dialog))
            except Exception:
                pass
            return dialog

        dialog = parent.open_workspace_tab(
            "nina.control",
            "N.I.N.A.",
            _create_nina_tab,
            tooltip="FZAstro Imaging / N.I.N.A. control panel",
            on_close=_clear_reference,
        )
        if hasattr(dialog, "load_selected_target"):
            QTimer.singleShot(0, dialog.load_selected_target)
        return dialog

    existing = (
        getattr(parent, "nina_control_dialog", None) if parent is not None else None
    )
    if existing is not None:
        try:
            if existing.isVisible():
                existing.show()
                existing.raise_()
                existing.activateWindow()
                if hasattr(existing, "load_selected_target"):
                    QTimer.singleShot(0, existing.load_selected_target)
                return existing
        except RuntimeError:
            existing = None

    dialog = NinaControlDialog(parent)
    dialog.show()
    if hasattr(dialog, "load_selected_target"):
        QTimer.singleShot(0, dialog.load_selected_target)
    if parent is not None:
        setattr(parent, "nina_control_dialog", dialog)

        def _clear_reference():
            try:
                if getattr(parent, "nina_control_dialog", None) is dialog:
                    setattr(parent, "nina_control_dialog", None)
            except Exception:
                pass

        dialog.destroyed.connect(_clear_reference)
    return dialog

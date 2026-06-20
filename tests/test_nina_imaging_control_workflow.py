import os
from datetime import datetime, timedelta
from pathlib import Path

from fzastro_ai.nina import nina_bridge

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROL_SOURCE = PROJECT_ROOT / "fzastro_ai" / "ui" / "nina_control_dialog.py"
TARGETS_SOURCE = PROJECT_ROOT / "fzastro_ai" / "ui" / "targets_dialog.py"
BRIDGE_SOURCE = PROJECT_ROOT / "fzastro_ai" / "nina" / "nina_bridge.py"


def test_imaging_control_main_workflow_is_numbered_operations_cockpit():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert 'QPushButton("1\\nOPEN TARGETS")' in text
    assert 'QPushButton("2\\nCONFIRM + LOAD")' in text
    assert 'QPushButton("3\\nSTART SESSION")' in text
    assert 'QPushButton("SESSION REPORT")' in text
    assert "workflowStepButton" in text
    assert "workflow_tools_layout.addWidget(self.stop_session_button, 1)" in text
    assert "workflow_tools_layout.addWidget(self.generate_report_button, 1)" in text
    assert "workflowStatusStrip" in text
    assert "workflow_status_strip" in text
    assert "SAFE REVIEW ONLY" not in text
    assert 'QPushButton("3 · EQUIPMENT PREP / POWER ON")' not in text
    assert 'QPushButton("2 · PREPARE TARGET")' not in text
    assert "LOAD VIA API ONLY" in text
    assert "TOOLS / DIAGNOSTICS" in text


def test_targets_handoff_keeps_targets_tab_and_returns_to_nina_tab():
    control_text = CONTROL_SOURCE.read_text(encoding="utf-8")
    targets_text = TARGETS_SOURCE.read_text(encoding="utf-8")

    assert 'getattr(self, "_workspace_host", None)' in control_text
    assert "parent = self.parentWidget()" in control_text
    assert "main_window.open_astro_targets_dialog()" in control_text
    assert 'focus_nina_tab("nina.control")' in targets_text
    assert "nina_dialog = opener()" in targets_text
    assert "QTimer.singleShot(180, self.accept)" not in targets_text


def test_confirm_load_handles_missing_stale_draft_file():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")
    plan_text = (PROJECT_ROOT / "fzastro_ai" / "nina" / "imaging_plan.py").read_text(
        encoding="utf-8"
    )

    assert "def _current_plan_file_ready" in text
    assert "Draft plan missing" in text
    assert "Step 2 will continue automatically" in text
    assert "Draft imaging-plan JSON was not found" in plan_text


def test_imaging_control_exposes_status_cards_and_image_folder_config():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert "LIVE SESSION STATUS" in text
    assert "status_api_value" in text
    assert "status_sequence_value" in text
    assert "status_frames_value" in text
    assert "status_last_image_value" in text
    assert "N.I.N.A. image folder" in text
    assert "count_nina_image_files_since" in text
    assert "latest_nina_image_file" in text
    assert "_captured_frame_text" in text


def test_equipment_prep_sample_is_not_a_main_workflow_button():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert "FZAstro_EquipmentPrepSample.json" in text
    assert "EQUIPMENT_CHECK_Container" in text
    assert "def equipment_prep_power_on" in text
    assert 'QPushButton("3 · EQUIPMENT PREP / POWER ON")' not in text


def test_nina_bridge_start_uses_get_and_tracks_image_folder(tmp_path):
    bridge = BRIDGE_SOURCE.read_text(encoding="utf-8")

    assert (
        'nina_api_request("/sequence/start", settings=settings, method="GET"' in bridge
    )
    assert (
        'nina_api_request("/sequence/stop", settings=settings, method="GET"' in bridge
    )
    assert "nina_image_dir" in nina_bridge.DEFAULT_SETTINGS
    assert "equipment_prep_template_path" in nina_bridge.DEFAULT_SETTINGS

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    first = image_dir / "2026-03-05" / "FLAT" / "2026-03-05_21-34-56__10.00s_0049.fits"
    second = (
        image_dir / "2026-06-17" / "LIGHT" / "2026-06-18_01-48-01__60.00s_0000.fits"
    )
    third = image_dir / "2026-06-17" / "LIGHT" / "2026-06-18_01-49-01__60.00s_0001.fits"
    for item in (first, second, third):
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(item.name, encoding="utf-8")

    # Simulate Dropbox refreshing an old file's modified time.  FZAstro must
    # still prefer the actual N.I.N.A. filename capture timestamp.
    old_epoch = datetime(2026, 3, 5, 21, 35, 0).timestamp()
    new_epoch = datetime(2026, 6, 18, 1, 49, 1).timestamp()
    refreshed_old_mtime = datetime(2026, 6, 18, 2, 30, 0).timestamp()
    os.utime(first, (refreshed_old_mtime, refreshed_old_mtime))
    os.utime(second, (new_epoch - 60, new_epoch - 60))
    os.utime(third, (new_epoch, new_epoch))

    settings = {"nina_image_dir": str(image_dir)}
    assert nina_bridge.count_nina_image_files_since(settings) == 3
    assert nina_bridge.latest_nina_image_file(settings) == third

    session_start = datetime(2026, 6, 18, 1, 47, 30).timestamp()
    assert nina_bridge.count_nina_image_files_since(settings, session_start) == 2
    assert nina_bridge.latest_nina_image_file(settings, session_start) == third

    late_session_start = (
        datetime(2026, 6, 18, 1, 49, 30) + timedelta(seconds=1)
    ).timestamp()
    assert nina_bridge.count_nina_image_files_since(settings, late_session_start) == 2

    assert old_epoch < session_start


def test_imaging_control_auto_refreshes_live_session_status():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert "_live_status_refresh_timer" in text
    assert ".setInterval(15000)" in text
    assert ".timeout.connect(self.refresh_live_session_status)" in text
    assert "def refresh_live_session_status" in text
    assert "get_sequence_state(self.settings)" in text
    assert "latest_nina_image_session_count" in text
    assert "latest_nina_image_session_files" in text
    assert "nina_filename_frame_count" in text


def test_latest_session_folder_count_recovers_when_start_time_is_late(tmp_path):
    image_dir = tmp_path / "images"
    latest_folder = image_dir / "2026-06-17" / "LIGHT"
    earlier = latest_folder / "2026-06-18_01-51-01__60.00s_0002.fits"
    latest = latest_folder / "2026-06-18_01-52-01__60.00s_0003.fits"
    old = image_dir / "2026-03-05" / "FLAT" / "2026-03-05_21-34-56__10.00s_0049.fits"
    for item in (earlier, latest, old):
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(item.name, encoding="utf-8")

    settings = {"nina_image_dir": str(image_dir)}
    late_start = datetime(2026, 6, 18, 2, 10, 0).timestamp()

    assert nina_bridge.count_nina_image_files_since(settings, late_start) == 0
    assert nina_bridge.latest_nina_image_file(settings, late_start) is None
    assert nina_bridge.latest_nina_image_file(settings) == latest
    assert nina_bridge.latest_nina_image_session_count(settings, late_start) == 2
    assert nina_bridge.latest_nina_image_session_files(settings, late_start) == [
        earlier,
        latest,
    ]
    assert nina_bridge.nina_filename_frame_count(latest) == 4


def test_latest_session_files_ignore_older_runs_in_same_nina_light_folder(tmp_path):
    image_dir = tmp_path / "images"
    light_dir = image_dir / "2026-06-17" / "LIGHT"
    old_a = light_dir / "2026-06-18_00-01-00__60.00s_0000.fits"
    old_b = light_dir / "2026-06-18_00-02-00__60.00s_0001.fits"
    new_a = light_dir / "2026-06-18_02-26-49__60.00s_0000.fits"
    new_b = light_dir / "2026-06-18_02-27-49__60.00s_0001.fits"
    for item in (old_a, old_b, new_a, new_b):
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(item.name, encoding="utf-8")

    settings = {"nina_image_dir": str(image_dir)}

    assert nina_bridge.latest_nina_image_file(settings) == new_b
    assert nina_bridge.latest_nina_image_session_files(settings) == [new_a, new_b]
    assert nina_bridge.latest_nina_image_session_count(settings) == 2


def test_imaging_control_last_image_preview_supports_fits_stretch_and_open_buttons():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert "LAST IMAGE PREVIEW" in text
    assert "OPEN LAST IMAGE" in text
    assert "OPEN IMAGE FOLDER" in text
    assert "REFRESH PREVIEW" in text
    assert "def refresh_last_image_preview" in text
    assert "def _fits_preview_pixmap" in text
    assert "from astropy.io import fits" in text
    assert "Format_Grayscale8" in text
    assert "np.percentile(sample, (0.5, 99.5))" in text
    assert "QDesktopServices.openUrl(QUrl.fromLocalFile(str(latest)))" in text


def test_last_image_preview_layout_matches_target_lookup_details_row():
    text = CONTROL_SOURCE.read_text(encoding="utf-8")

    assert "live_status_row = QHBoxLayout()" in text
    assert "preview_column = QVBoxLayout()" in text
    assert "status_details_widget = QWidget()" in text
    assert "status_details_layout = QGridLayout(status_details_widget)" in text
    assert "last_image_preview_details_label" in text
    assert "self.last_image_preview_label.setMinimumSize(220, 120)" in text
    assert "self.last_image_preview_label.setMaximumSize(300, 180)" in text
    assert (
        "preview_column.addWidget(self.last_image_preview_label, 0, Qt.AlignTop)"
        in text
    )
    assert "status_details_layout.addWidget(label, row, col, 1, 2)" in text
    assert "status_details_layout.addWidget(last_image_button_row" in text
    assert "live_status_row.addLayout(preview_column, 0)" in text
    assert "live_status_row.addWidget(status_details_widget, 1)" in text
    assert "self._set_last_image_preview_details(latest)" in text

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from ..file_tools import prepare_content
from ..logging_utils import log_exception, log_warning
from ..nina.imaging_plan import (
    IMAGING_PLAN_DIR,
    ImagingPlanResult,
    build_predefined_imaging_plan,
    build_selected_target_imaging_plan,
    format_imaging_plan_markdown,
    parse_predefined_imaging_command,
    predefined_imaging_command_help,
)
from ..nina.nina_bridge import (
    check_for_update,
    launch_sequence_file,
    load_settings,
    save_settings,
)
from ..ui.nina_control_dialog import open_nina_control_dialog


class ImagingPlanWorker(QThread):
    """Create a safe FZAstro Imaging/N.I.N.A. review plan off the UI thread."""

    finished_plan = Signal(object, float)
    error_received = Signal(str)

    def __init__(
        self,
        command,
        location: dict[str, Any],
        imaging: dict[str, Any],
        *,
        selected_target: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.command = command
        self.location = dict(location or {})
        self.imaging = dict(imaging or {})
        self.selected_target = dict(selected_target or {})

    def run(self):
        start = time.perf_counter()
        try:
            if self.selected_target:
                plan = build_selected_target_imaging_plan(
                    command=self.command,
                    location=self.location,
                    imaging=self.imaging,
                    selected_target=self.selected_target,
                )
            else:
                plan = build_predefined_imaging_plan(
                    command=self.command,
                    location=self.location,
                    imaging=self.imaging,
                )
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_plan.emit(plan, elapsed)
        except Exception as exc:
            log_exception("ImagingPlanWorker.run", exc)
            self.error_received.emit(str(exc))


class NinaActionsMixin:
    """Main-window hooks for FZAstro Imaging / bundled N.I.N.A. integration."""

    def open_nina_control(self):
        return open_nina_control_dialog(self)

    def open_imaging_plans_folder(self):
        """Open the generated review-plan folder without starting equipment control."""

        try:
            IMAGING_PLAN_DIR.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(IMAGING_PLAN_DIR)))
            self.stats_label.setText("Opened FZAstro Imaging plans folder.")
        except Exception as exc:
            log_exception("NinaActionsMixin.open_imaging_plans_folder", exc)
            QMessageBox.warning(self, "FZAstro Imaging plans", str(exc))

    def set_pending_imaging_target_from_targets(
        self,
        pick: dict[str, Any],
        *,
        planner_options: dict[str, Any] | None = None,
        planner_result: dict[str, Any] | None = None,
        imaging: dict[str, Any] | None = None,
        capture: dict[str, Any] | None = None,
        lookup_html: str = "",
        preview_image_path: str = "",
        framing_preview: dict[str, Any] | None = None,
    ):
        """Stage a user-selected TARGETS row for Imaging Control.

        This is only a UI handoff. It does not create a N.I.N.A. JSON file and
        does not request slew/guiding/capture. Imaging Control later prepares a
        draft plan from the selected target and calculates frames from the best
        SEEING window. TARGETS may also hand over camera/focal/exposure/gain,
        LOOKUP details, and a thumbnail preview for review.
        """

        self.pending_imaging_target_from_targets = {
            "pick": dict(pick or {}),
            "planner_options": dict(planner_options or {}),
            "planner_result": dict(planner_result or {}),
            "imaging": dict(imaging or {}),
            "capture": dict(capture or {}),
            "lookup_html": str(lookup_html or ""),
            "preview_image_path": str(preview_image_path or ""),
            "framing_preview": dict(framing_preview or {}),
        }
        try:
            self.stats_label.setText(
                f"Selected imaging target: {pick.get('name') or 'target'}"
            )
        except Exception:
            pass

    def get_pending_imaging_target_from_targets(self) -> dict[str, Any] | None:
        pending = getattr(self, "pending_imaging_target_from_targets", None)
        return dict(pending) if isinstance(pending, dict) else None

    def prepare_pending_imaging_target_plan(
        self, *, exposure_seconds: int | None = None, gain: int | None = None
    ) -> bool:
        pending = self.get_pending_imaging_target_from_targets()
        pick = dict((pending or {}).get("pick") or {})
        target = str(pick.get("name") or "").strip()
        if not target:
            QMessageBox.information(
                self, "FZAstro Imaging plan", "Select a target in TARGETS first."
            )
            return False
        capture = dict((pending or {}).get("capture") or {})
        imaging = dict((pending or {}).get("imaging") or {})
        if imaging and hasattr(self, "set_current_astro_imaging"):
            try:
                self.set_current_astro_imaging(imaging)
            except Exception:
                pass
        exposure_source = (
            exposure_seconds
            if exposure_seconds is not None
            else capture.get("exposure_seconds", 60)
        )
        gain_source = gain if gain is not None else capture.get("gain", 200)
        exposure = max(1, min(24 * 3600, int(exposure_source or 60)))
        gain_value = max(0, min(10000, int(gain_source or 0)))
        # Do not pass a frame count. Frames are calculated from the best SEEING
        # imaging window and the confirmed exposure length.
        return self.try_handle_predefined_imaging_plan_command(
            f"/nina-plan target {target} exposure {exposure}s gain {gain_value}",
            selected_target=pick,
        )

    def maybe_auto_check_nina_updates(self):
        settings = load_settings()
        if not settings.get("auto_check_updates"):
            return
        if not str(settings.get("update_manifest_url") or "").strip():
            return
        QTimer.singleShot(2500, self._auto_check_nina_updates)

    def _auto_check_nina_updates(self):
        settings = load_settings()
        try:
            info = check_for_update(settings, timeout=8.0)
        except Exception as exc:
            log_warning("NINA auto-update check failed", exc)
            return
        if not info:
            return
        settings["last_update_check"] = info.published_at or "checked"
        settings["last_available_version"] = info.version
        save_settings(settings)
        if info.is_newer:
            try:
                self.stats_label.setText(
                    f"FZAstro Imaging update available: {info.version}. Open FZAstro Imaging Control to download."
                )
            except Exception:
                pass

    def try_handle_predefined_imaging_plan_command(
        self, text: str, *, selected_target: dict[str, Any] | None = None
    ) -> bool:
        """Handle safe predefined FZAstro Imaging/N.I.N.A. plan commands.

        This intentionally creates draft review files first. The importable
        N.I.N.A. Advanced Sequencer JSON is generated only after the user
        confirms target/framing/capture values in FZASTRO IMAGING CONTROL.
        """

        command = parse_predefined_imaging_command(text)
        if command is None:
            return False

        if str(text or "").strip().casefold() in {
            "/nina-plan",
            "/imaging-plan",
            "/astro-plan",
            "/plan-imaging",
        }:
            QMessageBox.information(
                self, "FZAstro Imaging plan", predefined_imaging_command_help()
            )
            return True

        worker = getattr(self, "nina_plan_worker", None)
        if worker is not None and worker.isRunning():
            self.stats_label.setText("FZAstro Imaging plan already running.")
            return True

        if command.auto_start_requested:
            QMessageBox.information(
                self,
                "Review-only imaging plan",
                "FZAstro will create a review-only plan. It will not start, schedule, slew, guide, or capture automatically.",
            )

        user_message_id = uuid.uuid4().hex
        display_text = str(text or command.raw_text).strip()
        self.messages.append(
            {
                "id": user_message_id,
                "role": "user",
                "content": prepare_content(display_text, []),
                "files": [],
            }
        )
        self.add_message_widget(":ME:", display_text, [], message_id=user_message_id)

        try:
            location = self.get_current_astro_location()
            imaging = self.get_current_astro_imaging()
        except Exception as exc:
            log_exception(
                "NinaActionsMixin.try_handle_predefined_imaging_plan_command", exc
            )
            QMessageBox.warning(self, "FZAstro Imaging plan", str(exc))
            return True

        self.request_start_time = time.perf_counter()
        try:
            self.generation_timer.start(100)
        except Exception:
            pass
        self.set_busy_ui_state(
            "Creating FZAstro Imaging draft from SEEING/TARGETS... • 0.00s"
        )

        worker = ImagingPlanWorker(
            command, location, imaging, selected_target=selected_target
        )
        self.nina_plan_worker = worker
        worker.finished_plan.connect(self.finish_predefined_imaging_plan)
        worker.error_received.connect(self.handle_predefined_imaging_plan_error)
        worker.finished.connect(self.handle_predefined_imaging_plan_worker_finished)
        worker.start()
        return True

    def finish_predefined_imaging_plan(self, plan: ImagingPlanResult, elapsed: float):
        try:
            self.generation_timer.stop()
        except Exception:
            pass
        try:
            self.global_thought_box.setMarkdown("")
            self._last_thoughts_text = ""
        except Exception:
            pass

        text = format_imaging_plan_markdown(plan)
        text = (
            f"{text}\n\n"
            "**Next step:** open FZASTRO IMAGING CONTROL, load the latest draft, "
            "review/adjust target framing, focal length, exposure, gain, and frames, "
            "then click **CONFIRM & GENERATE N.I.N.A. JSON**. The importable "
            "`.nina-sequence.json` is not generated before that confirmation."
        )
        files = [
            plan.plan_text_path,
            plan.nina_xml_path,
            plan.nina_csv_path,
            plan.nina_review_path,
            plan.plan_json_path,
        ]
        if (
            bool(getattr(plan, "nina_sequence_confirmed", False))
            and Path(plan.nina_sequence_path).exists()
        ):
            files.insert(1, plan.nina_sequence_path)
        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "astro", "imaging", "nina"]

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": text,
                "files": files,
                "news_sources": {},
                "response_time": float(elapsed),
                "source_tags": source_tags,
            }
        )

        self.add_message_widget(
            ":AI: ",
            text,
            files=files,
            message_id=assistant_message_id,
            response_time=float(elapsed),
            source_tags=source_tags,
        )

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.force_scroll_to_bottom()
        QTimer.singleShot(0, self.force_scroll_to_bottom)
        self.set_idle_ui_state(f"FZAstro Imaging draft ready • {float(elapsed):.2f}s")

    def _try_open_generated_nina_sequence(self, plan: ImagingPlanResult) -> str:
        """Launch FZAstro Imaging and attempt to open the generated sequence file.

        This method deliberately performs only a launch/open request.  It never
        starts a sequence or requests any telescope/camera/guider action.
        """

        sequence_path = str(getattr(plan, "nina_sequence_path", "") or "").strip()
        if not sequence_path:
            return ""
        try:
            result = launch_sequence_file(sequence_path, load_settings())
            try:
                self.stats_label.setText(
                    "FZAstro Imaging launch/open requested for generated plan."
                )
            except Exception:
                pass
            return (
                "**FZAstro Imaging launch requested:** the generated `.nina-sequence.json` "
                "was sent to the bundled imaging app for review. If N.I.N.A. does not show "
                "it automatically, use Advanced Sequencer → Open and select:\n\n"
                f"`{result.sequence_path}`\n\n"
                "No slew, guiding, capture, or sequence start was requested."
            )
        except Exception as exc:
            log_warning("NinaActionsMixin._try_open_generated_nina_sequence", exc)
            try:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(Path(sequence_path).parent))
                )
            except Exception:
                pass
            return (
                "**FZAstro Imaging auto-open skipped:** the review plan was created, "
                f"but FZAstro could not launch/open it automatically: `{exc}`.\n\n"
                "Open FZAstro Imaging/N.I.N.A. manually and load this file in the Advanced Sequencer:\n\n"
                f"`{sequence_path}`"
            )

    def handle_predefined_imaging_plan_error(self, error: str):
        log_warning("NinaActionsMixin.handle_predefined_imaging_plan_error", error)
        try:
            self.generation_timer.stop()
        except Exception:
            pass
        self.set_idle_ui_state("FZAstro Imaging plan failed")
        QMessageBox.warning(self, "FZAstro Imaging plan", str(error))

    def handle_predefined_imaging_plan_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "nina_plan_worker", None):
            self.nina_plan_worker = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception as exc:
                log_warning("NinaActionsMixin worker cleanup skipped", exc)

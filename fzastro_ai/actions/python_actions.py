"""Python execution actions for the main FZAstro AI window.

Extracted from app.py during Phase 2G without behavior changes.
"""

import re
import time
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from ..config import PYTHON_EXECUTION_MAX_OUTPUT_CHARS, PYTHON_EXECUTION_TIMEOUT_SECONDS
from ..logging_utils import log_exception
from ..memory_store import make_fenced_code
from ..routing.intent_detection import (
    extract_last_python_code_block_from_text as _routing_extract_last_python_code_block_from_text,
    extract_python_code_from_text as _routing_extract_python_code_from_text,
    is_python_execution_request as _routing_is_python_execution_request,
    is_python_generate_and_test_request as _routing_is_python_generate_and_test_request,
    looks_like_python_code as _routing_looks_like_python_code,
    python_code_has_risky_auto_actions as _routing_python_code_has_risky_auto_actions,
)
from ..routing.source_tags import normalize_response_source_tags
from ..workers import PythonExecutionWorker, resolve_python_execution_interpreter


def prepare_content(text, files):
    # Imported lazily to avoid an app -> actions -> app import cycle at startup.
    from ..app import prepare_content as _prepare_content

    return _prepare_content(text, files)


class PythonActionsMixin:
    @staticmethod
    def is_python_execution_request(text):
        return _routing_is_python_execution_request(text)

    @staticmethod
    def is_python_generate_and_test_request(text):
        return _routing_is_python_generate_and_test_request(text)

    @staticmethod
    def python_code_has_risky_auto_actions(code):
        return _routing_python_code_has_risky_auto_actions(code)

    @staticmethod
    def extract_python_code_from_text(text, force=False):
        return _routing_extract_python_code_from_text(text, force=force)

    @staticmethod
    def looks_like_python_code(text):
        return _routing_looks_like_python_code(text)

    @staticmethod
    def extract_last_python_code_block_from_text(text):
        return _routing_extract_last_python_code_block_from_text(text)

    def find_last_python_code_block_in_chat(self):
        for message in reversed(self.messages or []):
            if not isinstance(message, dict):
                continue

            source_tags = normalize_response_source_tags(
                message.get("source_tags") or []
            )

            # Do not re-run stdout/stderr cards from previous Python executions.
            if "python_execution" in source_tags:
                continue

            content = str(message.get("content") or "")
            code = self.extract_last_python_code_block_from_text(content)

            if code:
                return code

        return ""

    def run_python_code_block_from_chat(self, code):
        clean_code = str(code or "").strip()

        if not clean_code:
            return

        self.execute_python_code(
            "Run Python code block from chat:\n\n"
            + make_fenced_code("python", clean_code),
            force=False,
            record_user_message=False,
        )

    def run_python_from_input(self):
        input_text = self.input_box.toPlainText().strip()

        if input_text:
            code = self.extract_python_code_from_text(input_text, force=False)

            if not code and self.looks_like_python_code(input_text):
                code = input_text

            if code:
                self.execute_python_code(make_fenced_code("python", code), force=False)
                return

            code = self.find_last_python_code_block_in_chat()

            if code:
                reply = QMessageBox.question(
                    self,
                    "Run latest Python block?",
                    "No runnable Python code was detected in the input box. Run the latest Python code block from the chat instead?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )

                if reply == QMessageBox.Yes:
                    self.execute_python_code(
                        "Run latest Python block from chat:\n\n"
                        + make_fenced_code("python", code),
                        force=False,
                    )

                return

            QMessageBox.information(
                self,
                "No Python code found",
                "Paste Python code in the input box with /run-python, or click Run on a Python code block in chat.",
            )
            return

        code = self.find_last_python_code_block_in_chat()

        if not code:
            QMessageBox.information(
                self,
                "No Python code found",
                "No Python code block was found in the chat. Ask the model to write Python code first, or paste code into the input box.",
            )
            return

        self.execute_python_code(
            "Run latest Python block from chat:\n\n" + make_fenced_code("python", code),
            force=False,
        )

    def execute_python_code(
        self, text, force=False, record_user_message=True, auto_generated=False
    ):
        if self.worker and self.worker.isRunning():
            return

        decision_worker = getattr(self, "decision_worker", None)

        if decision_worker is not None and decision_worker.isRunning():
            return

        web_worker = getattr(self, "web_worker", None)

        if web_worker is not None and web_worker.isRunning():
            return

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            return

        raw_text = str(text or "").strip()
        code = self.extract_python_code_from_text(raw_text, force=force)

        if not code:
            QMessageBox.information(
                self,
                "No Python code found",
                "Paste Python code in the input box or use /run-python followed by a Python code block.",
            )
            return

        if not resolve_python_execution_interpreter():
            QMessageBox.warning(
                self,
                "Python interpreter not found",
                "No Python interpreter was found. Set FZASTRO_PYTHON to your venv python.exe path, then restart the app.",
            )
            return

        self.current_news_sources = {}
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""
        self.pending_stream_text = ""
        self.last_rendered_stream_text = ""
        self.stream_render_timer.stop()

        if raw_text:
            display_text = raw_text
        else:
            display_text = make_fenced_code("python", code)

        if force and not self.is_python_execution_request(display_text):
            if "```" not in display_text:
                display_text = "Run Python:\n\n" + make_fenced_code("python", code)
            else:
                display_text = "Run Python:\n\n" + display_text

        if record_user_message:
            user_message_id = uuid.uuid4().hex
            self.messages.append(
                {
                    "id": user_message_id,
                    "role": "user",
                    "content": prepare_content(display_text, []),
                    "files": [],
                }
            )
            self.add_message_widget(
                ":ME:", display_text, [], message_id=user_message_id
            )

            self.input_box.clear()
            self.attached_files = []
            self.render_attachments()

        self.request_start_time = time.perf_counter()
        self.generation_timer.start(100)
        self.set_busy_ui_state(
            "Python auto-test • 0.00s • running"
            if auto_generated
            else "Python • 0.00s • running"
        )

        self.python_worker = PythonExecutionWorker(
            code,
            python_executable=resolve_python_execution_interpreter(),
            timeout=PYTHON_EXECUTION_TIMEOUT_SECONDS,
            max_output_chars=PYTHON_EXECUTION_MAX_OUTPUT_CHARS,
        )
        python_worker = self.python_worker
        python_worker.finished_execution.connect(self.handle_python_execution_result)
        python_worker.stopped_execution.connect(self.handle_python_execution_stopped)
        python_worker.error_received.connect(self.handle_python_execution_error)
        python_worker.finished.connect(
            lambda finished_worker=python_worker: self.finalize_python_execution_worker(
                finished_worker
            )
        )
        python_worker.start()

    def schedule_python_auto_test(self, final_answer):
        pending = getattr(self, "pending_python_auto_test", None)
        self.pending_python_auto_test = None

        if not pending or not pending.get("enabled"):
            return

        code = self.extract_python_code_from_text(final_answer, force=False)

        if not code:
            self.stats_label.setText(
                "Python auto-test skipped: no Python code block found"
            )
            return

        if self.python_code_has_risky_auto_actions(code):
            warning_text = (
                "## Python auto-test skipped\n\n"
                "The generated code contains actions that are not allowed for automatic execution. "
                "Review it first, then run it manually with the code-block **Run** button or `/run-python` if you trust it."
            )
            elapsed = 0.0
            assistant_message_id = uuid.uuid4().hex
            source_tags = ["app", "python_execution"]
            self.messages.append(
                {
                    "id": assistant_message_id,
                    "role": "assistant",
                    "content": warning_text,
                    "files": [],
                    "news_sources": {},
                    "response_time": elapsed,
                    "source_tags": source_tags,
                }
            )
            self.add_message_widget(
                ":AI: ",
                warning_text,
                message_id=assistant_message_id,
                response_time=elapsed,
                source_tags=source_tags,
            )
            self.save_current_chat()
            return

        def start_when_chat_worker_is_done():
            chat_worker = getattr(self, "worker", None)

            if chat_worker is not None and chat_worker.isRunning():
                QTimer.singleShot(80, start_when_chat_worker_is_done)
                return

            self.execute_python_code(
                make_fenced_code("python", code),
                force=False,
                record_user_message=False,
                auto_generated=True,
            )

        QTimer.singleShot(80, start_when_chat_worker_is_done)

    def stop_python_execution(self):
        if self.stop_in_progress:
            return

        self.stop_in_progress = True
        self.set_action_button_mode("stopping")
        self.stats_label.setText("Stopping Python execution.")

        python_worker = getattr(self, "python_worker", None)

        if python_worker is None:
            self.set_idle_ui_state("Python execution stopped")
            return

        try:
            python_worker.stop()
        except Exception as exc:
            log_exception("FZAstroAI.stop_python_execution line 18969", exc)
            self.set_idle_ui_state("Python execution stop failed")

    @staticmethod
    def format_python_execution_result(
        stdout,
        stderr,
        return_code,
        elapsed,
        timed_out=False,
        stopped=False,
        fatal_error=False,
    ):
        stdout = str(stdout or "").strip("\n")
        stderr = str(stderr or "").strip("\n")

        if fatal_error:
            title = "## Python execution failed"
        elif stopped:
            title = "## Python execution stopped"
        else:
            title = "## Python execution result"

        if timed_out:
            status = "Timed out"
        elif stopped:
            status = "Stopped by user"
        elif fatal_error:
            status = "Failed before execution"
        elif int(return_code) == 0:
            status = "Completed"
        else:
            status = "Completed with errors"

        parts = [
            title,
            "",
            f"Status: **{status}**",
            f"Exit code: `{return_code}`",
            f"Elapsed: `{elapsed:.2f}s`",
        ]

        if stdout:
            parts.extend(["", "**Output:**", make_fenced_code("text", stdout)])

        if stderr:
            parts.extend(["", "**Errors:**", make_fenced_code("text", stderr)])

        if not stdout and not stderr:
            parts.extend(["", "Code executed successfully with no output."])

        if not fatal_error:
            parts.extend(
                [
                    "",
                    "",
                ]
            )

        return "\n".join(parts).strip()

    def handle_python_execution_result(
        self, stdout, stderr, return_code, elapsed, timed_out
    ):
        self.generation_timer.stop()
        # Keep the QThread object referenced until QThread.finished is emitted.
        # Clearing it here can destroy the wrapper while the native thread is
        # still unwinding, which can crash PySide on Windows with 0xC0000409.
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""

        result_text = self.format_python_execution_result(
            stdout, stderr, return_code, elapsed, timed_out=timed_out
        )
        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "python_execution"]

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": result_text,
                "files": [],
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": source_tags,
            }
        )
        self.add_message_widget(
            ":AI: ",
            result_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=source_tags,
        )
        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.force_scroll_to_bottom()
        QTimer.singleShot(0, self.force_scroll_to_bottom)

        if hasattr(self, "set_last_tool_result"):
            status = (
                "timeout"
                if timed_out
                else ("success" if int(return_code) == 0 else "error")
            )
            self.set_last_tool_result(
                "Python execution",
                status,
                f"Exit code {return_code} • elapsed {elapsed:.2f}s",
                details=result_text,
            )

        if timed_out:
            self.set_idle_ui_state(f"Python timed out after {elapsed:.2f}s")
        elif int(return_code) == 0:
            self.set_idle_ui_state(f"Python finished in {elapsed:.2f}s")
        else:
            self.set_idle_ui_state(f"Python finished with errors in {elapsed:.2f}s")

    def handle_python_execution_stopped(self, stdout, stderr, elapsed):
        self.generation_timer.stop()
        # Keep the QThread object referenced until QThread.finished is emitted.
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""

        result_text = self.format_python_execution_result(
            stdout, stderr, -1, elapsed, stopped=True
        )
        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "python_execution"]

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": result_text,
                "files": [],
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": source_tags,
            }
        )
        self.add_message_widget(
            ":AI: ",
            result_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=source_tags,
        )
        self.save_current_chat()
        if hasattr(self, "set_last_tool_result"):
            self.set_last_tool_result(
                "Python execution",
                "stopped",
                f"Stopped by user after {elapsed:.2f}s",
                details=result_text,
            )
        self.set_idle_ui_state(f"Python stopped after {elapsed:.2f}s")

    def handle_python_execution_error(self, error):
        self.generation_timer.stop()
        elapsed = max(
            0.0,
            time.perf_counter()
            - getattr(self, "request_start_time", time.perf_counter()),
        )
        # Keep the QThread object referenced until QThread.finished is emitted.
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""

        result_text = self.format_python_execution_result(
            "",
            str(error or "Unknown Python execution error"),
            -1,
            elapsed,
            fatal_error=True,
        )
        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "python_execution"]

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": result_text,
                "files": [],
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": source_tags,
            }
        )
        self.add_message_widget(
            ":AI: ",
            result_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=source_tags,
        )
        self.save_current_chat()
        if hasattr(self, "set_last_tool_result"):
            self.set_last_tool_result(
                "Python execution",
                "error",
                f"Failed before execution after {elapsed:.2f}s",
                details=result_text,
            )
        self.set_idle_ui_state(f"Python execution failed after {elapsed:.2f}s")

    def finalize_python_execution_worker(self, finished_worker):
        """Release a PythonExecutionWorker only after its QThread has finished."""
        worker = finished_worker

        if worker is None:
            return

        if worker is getattr(self, "python_worker", None):
            self.python_worker = None

        # closeEvent owns deletion for workers that are part of shutdown.
        closing_workers = list(getattr(self, "_closing_workers", []) or [])

        if worker in closing_workers:
            return

        try:
            worker.deleteLater()
        except RuntimeError:
            pass

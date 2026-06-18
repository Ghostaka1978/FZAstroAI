"""Chat send/response lifecycle actions for the main FZAstro AI window.

Extracted from app.py during Phase 2K without behavior changes.
"""

from dataclasses import replace
import time
import uuid

from PySide6.QtWidgets import QMessageBox

from ..assistant_text import normalize_assistant_link_markup
from ..config import KNOWLEDGE_MAX_CONTEXT_CHARS
from ..file_tools import has_image_attachments
from ..llm import (
    estimate_token_count,
    find_installed_vision_model,
    get_ollama_model_capabilities,
)
from ..logging_utils import log_debug, log_exception
from ..memory_store import make_fenced_code
from ..persona_routing import is_assistant_persona_status_query
from ..routing.chat_route import collect_chat_route_facts, decide_chat_route_from_facts
from ..routing.source_tags import (
    infer_response_source_tags,
    normalize_response_source_tags,
)


class ChatLifecycleMixin:
    def action_button_clicked(self):
        if self.worker and self.worker.isRunning():
            self.stop_generation()
            return

        decision_worker = getattr(self, "decision_worker", None)

        if decision_worker is not None and decision_worker.isRunning():
            self.stop_web_decision()
            return

        web_worker = getattr(self, "web_worker", None)

        if web_worker is not None and web_worker.isRunning():
            self.stop_web_search()
            return

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            self.stop_python_execution()
            return

        astro_worker = getattr(self, "astro_worker", None)

        if astro_worker is not None and astro_worker.isRunning():
            self.stop_astro_tool()
            return

        self.send_message()

    def answer_assistant_persona_status_query(self):
        self.generation_timer.stop()
        elapsed = 0.0

        if getattr(self, "request_start_time", None):
            elapsed = max(0.0, time.perf_counter() - self.request_start_time)

        if hasattr(self, "current_persona_chat_summary"):
            response_text = self.current_persona_chat_summary()
        elif hasattr(self, "current_persona_summary"):
            response_text = self.current_persona_summary()
        else:
            response_text = "No assistant persona information is available."

        assistant_message_id = uuid.uuid4().hex
        source_tags = ["app", "persona"]

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": response_text,
                "files": [],
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": source_tags,
            }
        )
        self.add_message_widget(
            ":AI: ",
            response_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=source_tags,
        )
        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.force_scroll_to_bottom()

        if hasattr(self, "set_last_tool_result"):
            self.set_last_tool_result(
                "Assistant persona",
                "success",
                "Displayed the active local assistant persona/calibration profile.",
                details=response_text,
            )

        self.set_idle_ui_state(f"Assistant persona shown • {elapsed:.2f}s")

    def execute_tool_plan(
        self,
        plan,
        *,
        text,
        display_text,
        files,
        web_mode,
        model_override=None,
    ):
        """Execute a validated deterministic tool plan through existing workers."""
        if plan is None:
            return False

        if hasattr(self, "set_last_tool_result"):
            self.set_last_tool_result(
                f"Tool route: {plan.tool_id}",
                "running",
                plan.reason or "Routing request through an app tool.",
                f"confidence={plan.confidence:.2f}",
            )

        if plan.action == "python_run":
            if plan.requires_confirmation:
                reply = QMessageBox.question(
                    self,
                    "Run potentially risky Python?",
                    (
                        "The code contains file, process, network, dynamic execution, "
                        "or other actions that are not safe for automatic execution.\n\n"
                        "Run it anyway?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )

                if reply != QMessageBox.Yes:
                    self.set_idle_ui_state("Python execution cancelled")
                    return True

            self.execute_python_code(
                make_fenced_code("python", plan.query),
                force=True,
                record_user_message=False,
            )
            return True

        if plan.action in {"documents_direct", "documents_search", "documents_brief"}:
            self.current_news_sources = {}
            self.stats_label.setText("Using local document knowledge... • 0.00s")
            self.send_message_after_web(
                plan.query or text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=True,
                model_override=model_override,
            )
            return True

        if plan.action in {"web_search", "web_read_page", "web_screenshot_page"}:
            if web_mode == "Off":
                return False

            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": web_mode == "Always",
                "include_document_knowledge": False,
                "model_override": model_override,
            }

            if plan.action == "web_search":
                self.stats_label.setText(
                    "Preparing web search without model routing..."
                )
                self.start_web_search_request(self.build_web_query(plan.query), request)
                return True

            self.stats_label.setText("Preparing URL page extraction...")
            self.start_web_search_request(plan.query or text, request)
            return True

        if plan.action == "weather_today":
            if web_mode == "Off":
                return False

            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": False,
                "include_document_knowledge": False,
                "model_override": model_override,
                "worker_mode": "weather",
            }

            self.stats_label.setText("Fetching current weather...")
            self.start_web_search_request(plan.query or text, request)
            return True

        if plan.action in {"stock_quote", "stock_compare", "market_pulse"}:
            if web_mode == "Off":
                return False

            worker_mode_by_action = {
                "stock_quote": "stock_quote",
                "stock_compare": "stock_compare",
                "market_pulse": "market_pulse",
            }
            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": False,
                "include_document_knowledge": False,
                "model_override": model_override,
                "worker_mode": worker_mode_by_action[plan.action],
            }

            self.stats_label.setText("Fetching market data...")
            self.start_web_search_request(plan.query or text, request)
            return True

        return False

    def send_message(self, daily_brief=False, force_web_search=False):
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

        astro_worker = getattr(self, "astro_worker", None)

        if astro_worker is not None and astro_worker.isRunning():
            return

        # News citation metadata belongs to exactly one generated response.
        # Clear any completed briefing state before starting a new request so
        # ordinary assistant replies cannot inherit the NEWS badge/header.
        self.current_news_sources = {}

        text = self.input_box.toPlainText().strip()

        if not text and not self.attached_files:
            return

        if not text and self.attached_files:
            text = "Inspect the attached file.\n\n"

        if (
            text
            and not self.attached_files
            and hasattr(self, "try_handle_local_composer_command")
            and self.try_handle_local_composer_command(text)
        ):
            self.input_box.clear()
            return

        if self.is_python_execution_request(text):
            self.execute_python_code(text, force=False)
            return

        if self.is_astro_direct_request(text):
            self.execute_astro_direct_request(text)
            return

        display_text = text
        files = list(self.attached_files)
        model_override = None

        if has_image_attachments(files):
            model_name = self.current_model_name()
            capabilities = get_ollama_model_capabilities(model_name)

            if capabilities is None or "vision" not in capabilities:
                vision_model = find_installed_vision_model(exclude_model=model_name)

                if vision_model:
                    # Use the vision model only for this request. The user's normal
                    # text-model selection remains unchanged after image analysis.
                    model_override = vision_model
                else:
                    QMessageBox.warning(
                        self,
                        "No vision model installed",
                        (
                            f"The selected model '{model_name}' cannot inspect images, "
                            "and no installed Ollama model advertising the 'vision' "
                            "capability was found.\n\n"
                            "Install or select a vision-capable model to analyze image "
                            "attachments. Web image retrieval does not require a vision "
                            "model and remains available."
                        ),
                    )
                    return

        self.request_start_time = time.perf_counter()
        self.generation_timer.start(100)

        self.set_busy_ui_state()

        self.add_message_widget(":ME:", display_text, files)

        # The newly inserted user message may contain its own action buttons.
        self.set_busy_ui_state()

        self.input_box.clear()
        self.attached_files = []
        self.render_attachments()

        if daily_brief:
            search_query = (
                "world news today || "
                "technology news today || "
                "business news today || "
                "science news today"
            )

            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": True,
                "include_document_knowledge": False,
                "model_override": model_override,
            }

            self.stats_label.setText("Preparing daily news brief... • 0.00s")

            self.start_web_search_request(search_query, request)
            return

        if force_web_search:
            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": True,
                "include_document_knowledge": False,
                "model_override": model_override,
            }

            self.stats_label.setText("Retrieving current stock price... • 0.00s")

            self.start_web_search_request(self.build_web_query(text), request)
            return

        if is_assistant_persona_status_query(text):
            self.answer_assistant_persona_status_query()
            return

        if self.is_python_generate_and_test_request(text):
            self.stats_label.setText("Preparing Python auto-test... • 0.00s")
            self.send_message_after_web(
                text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=False,
                model_override=model_override,
            )
            return

        web_mode = self.web_box.currentText()

        route_facts = collect_chat_route_facts(
            text,
            files=files,
            knowledge_library=getattr(self, "knowledge_library", None),
            web_mode=web_mode,
            force_web_search=False,
            recent_context=self.build_recent_conversation_context(),
            log_exception_func=log_exception,
        )
        latest_image_available = bool(
            self.latest_assistant_image_files()
            if route_facts.recent_image_followup
            else []
        )
        route_facts = replace(
            route_facts,
            latest_assistant_image_available=latest_image_available,
        )
        route = decide_chat_route_from_facts(
            route_facts,
            web_mode=web_mode,
            files=files,
        )

        if route.action == "deterministic_tool" and self.execute_tool_plan(
            route.tool_plan,
            text=text,
            display_text=display_text,
            files=files,
            web_mode=web_mode,
            model_override=model_override,
        ):
            return

        if route.action == "local_chat":
            self.send_message_after_web(
                text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=route.include_document_knowledge,
                model_override=model_override,
            )
            return

        if route.action == "forced_web_search":
            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": True,
                "include_document_knowledge": False,
                "model_override": model_override,
            }

            self.stats_label.setText("Preparing web search without model routing...")
            self.start_web_search_request(self.build_web_query(text), request)
            return

        # Local document-library actions must win before the generic image
        # router.  "Give me the image from page 270 from <PDF title>" is a
        # rendered PDF-page request, not a Bing image search.
        if route.action == "local_document_direct":
            self.stats_label.setText(
                "Using local document knowledge directly... • 0.00s"
            )
            self.send_message_after_web(
                text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=True,
                model_override=model_override,
            )
            return

        if route.action == "web_disabled_current_info":
            self.generation_timer.stop()
            elapsed = max(0.0, time.perf_counter() - self.request_start_time)
            assistant_message_id = uuid.uuid4().hex
            response_text = (
                "Web is Off, so I cannot verify current or latest information for "
                "this request. Switch Web to Auto or Always and ask again."
            )
            source_tags = ["app"]
            self.messages.append(
                {
                    "id": assistant_message_id,
                    "role": "assistant",
                    "content": response_text,
                    "files": [],
                    "news_sources": {},
                    "response_time": elapsed,
                    "source_tags": source_tags,
                }
            )
            self.add_message_widget(
                ":AI: ",
                response_text,
                message_id=assistant_message_id,
                response_time=elapsed,
                source_tags=source_tags,
            )
            self.save_current_chat()
            self.chat_container.adjustSize()
            self.chat_container.updateGeometry()
            self.force_scroll_to_bottom()
            self.set_idle_ui_state("Web is Off")
            return

        # Image retrieval is a deterministic capability, not a question for
        # the Auto web-routing model.  Route explicit web-image requests directly
        # from both Auto and Always modes so a router answer/refusal can never
        # intercept them.
        if route.action == "web_image":
            request = {
                "text": text,
                "display_text": display_text,
                "files": files,
                "force_search": web_mode == "Always",
                "include_document_knowledge": False,
                "model_override": model_override,
            }

            self.stats_label.setText("Preparing web image search...")

            self.start_web_search_request(text, request)
            return

        if route.action == "recent_image_followup":
            self.send_message_after_web(
                text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=False,
                model_override=model_override,
            )
            return

        if route.action == "attachment_local":
            self.stats_label.setText("Inspecting attached file locally... • 0.00s")
            self.send_message_after_web(
                text,
                [],
                display_text=display_text,
                files=files,
                show_user=False,
                include_document_knowledge=False,
                model_override=model_override,
            )
            return

        self.start_web_decision(
            text,
            display_text,
            files,
            force_search=route.force_search,
            model_override=model_override,
        )

    def finish_stopped_response(self, response_text):
        self.stream_render_timer.stop()
        if not self.stop_in_progress:
            return

        elapsed = max(0.0, time.perf_counter() - self.request_start_time)
        stream_widget = self.current_stream_widget

        if stream_widget is not None:
            try:
                thoughts, final_answer = stream_widget.split_thoughts(response_text)
            except RuntimeError:
                thoughts = ""
                final_answer = response_text
        else:
            thoughts = ""
            final_answer = response_text

        if thoughts:
            self._last_thoughts_text = thoughts
            self.show_latest_thoughts(thoughts)
        else:
            fallback_activity = self.build_model_activity_fallback(
                final_answer, completed=True
            )
            self._last_thoughts_text = fallback_activity

            if fallback_activity:
                self.show_latest_thoughts(fallback_activity)
            else:
                self.global_thought_box.setMarkdown("")

        stopped_text = normalize_assistant_link_markup(final_answer).strip()

        if stopped_text:
            stopped_text += "\n\n[Stopped by user]"
        else:
            stopped_text = "[Stopped by user]"

        self.current_stream_widget = None

        if stream_widget is not None:
            try:
                stream_widget.streaming = False
                stream_widget.set_text(stopped_text)
                stream_widget.set_reply_elapsed(elapsed, finished=True, stopped=True)
            except RuntimeError:
                pass

        assistant_message_id = self.current_assistant_message_id or uuid.uuid4().hex

        response_news_sources = dict(getattr(self, "current_news_sources", {}) or {})
        response_source_tags = normalize_response_source_tags(
            getattr(self, "current_source_tags", [])
            or getattr(stream_widget, "source_tags", [])
            or infer_response_source_tags(
                text=stopped_text,
                files=list(getattr(stream_widget, "files", []) or []),
                news_sources=response_news_sources,
            )
        )

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": stopped_text,
                "files": list(getattr(stream_widget, "files", []) or []),
                "news_sources": response_news_sources,
                "response_time": elapsed,
                "source_tags": response_source_tags,
            }
        )
        self.current_assistant_message_id = None
        self.current_news_sources = {}
        self.current_source_tags = []
        self.pending_python_auto_test = None

        self.save_current_chat()
        self.set_idle_ui_state(f"Stopped after {elapsed:.2f}s")

    def handle_error(self, error):
        self.stream_render_timer.stop()
        elapsed = max(0.0, time.perf_counter() - self.request_start_time)
        stream_widget = self.current_stream_widget
        self.current_stream_widget = None
        self.current_assistant_message_id = None
        self.current_news_sources = {}
        self.current_source_tags = []
        self.pending_python_auto_test = None

        if stream_widget is not None:
            try:
                stream_widget.streaming = False
                stream_widget.set_text(f"AI error: {error}")
                stream_widget.set_reply_elapsed(elapsed, finished=True, failed=True)
            except RuntimeError:
                pass

        self.set_idle_ui_state(f"Reply failed after {elapsed:.2f}s")

    def finish_response(self, response_text):
        self.stream_render_timer.stop()
        log_debug("RAW RESPONSE", response_text)

        elapsed = max(0.0, time.perf_counter() - self.request_start_time)

        if self.current_stream_widget:
            thoughts, final_answer = self.current_stream_widget.split_thoughts(
                response_text
            )
        else:
            thoughts = ""
            final_answer = response_text

        final_answer = normalize_assistant_link_markup(final_answer)

        if thoughts:
            self._last_thoughts_text = thoughts
            self.show_latest_thoughts(thoughts)
        else:
            fallback_activity = self.build_model_activity_fallback(
                final_answer, completed=True
            )
            self._last_thoughts_text = fallback_activity

            if fallback_activity:
                self.show_latest_thoughts(fallback_activity)
            else:
                self.global_thought_box.setMarkdown("")

        assistant_message_id = self.current_assistant_message_id or uuid.uuid4().hex

        response_news_sources = dict(getattr(self, "current_news_sources", {}) or {})
        response_files = list(getattr(self.current_stream_widget, "files", []) or [])
        response_source_tags = normalize_response_source_tags(
            getattr(self, "current_source_tags", [])
            or getattr(self.current_stream_widget, "source_tags", [])
            or infer_response_source_tags(
                text=final_answer,
                files=response_files,
                news_sources=response_news_sources,
            )
        )

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": final_answer,
                "files": response_files,
                "news_sources": response_news_sources,
                "response_time": elapsed,
                "source_tags": response_source_tags,
            }
        )
        self.current_assistant_message_id = None
        self.current_news_sources = {}
        self.current_source_tags = []

        self.save_current_chat()

        should_follow_chat = self.chat_scroll_is_near_bottom()
        stream_widget = self.current_stream_widget
        self.current_stream_widget = None

        if stream_widget is not None:
            try:
                stream_widget.streaming = False
                stream_widget.set_text(final_answer)
                stream_widget.set_reply_elapsed(elapsed, finished=True)
                stream_widget.updateGeometry()
                self.chat_container.adjustSize()
                self.chat_container.updateGeometry()
            except RuntimeError:
                pass

        self.queue_chat_scroll_to_bottom(should_follow_chat, settle=True)

        chars = len(final_answer)
        approx_tokens = estimate_token_count(final_answer)
        tokens_per_second = approx_tokens / elapsed if elapsed > 0 else 0
        context_fragment = self.context_budget_status_fragment(approx_tokens)

        self.set_idle_ui_state(
            f"{self.current_model_name()} • {elapsed:.2f}s • "
            f"out {chars} chars/~{approx_tokens} tok • "
            f"{context_fragment} • ~{tokens_per_second:.1f} tok/s"
        )

        self.schedule_python_auto_test(final_answer)

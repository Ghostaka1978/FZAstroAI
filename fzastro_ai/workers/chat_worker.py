import time

from PySide6.QtCore import QThread, Signal

from ..config import RUNTIME_CHAT_TIMEOUT_SECONDS, RUNTIME_VISION_CHAT_TIMEOUT_SECONDS
from ..llm import (
    build_chat_request_params,
    extract_delta_reasoning,
    extract_delta_text,
    is_expected_stream_close_error,
    looks_like_repetition_loop,
)
from ..logging_utils import log_debug, log_exception, log_warning
from ..runtime import (
    apply_ollama_model_keep_alive,
    format_runtime_model_unavailable_message,
    is_ollama_base_url,
    is_runtime_model_not_found_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)


class ChatWorker(QThread):
    token_received = Signal(str)
    error_received = Signal(str)
    finished_response = Signal(str)
    stopped_response = Signal(str)

    def __init__(
        self,
        messages,
        model,
        think_enabled=True,
        emit_interval=0.10,
        num_predict=4096,
        vision_request=False,
        base_url=None,
        api_key=None,
        keep_alive=None,
    ):
        super().__init__()
        self.messages = messages
        self.model = model
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_key = normalize_runtime_api_key(api_key)
        self.keep_alive = keep_alive
        self.think_enabled = bool(think_enabled)
        self.emit_interval = max(0.03, float(emit_interval))
        self.num_predict = max(64, int(num_predict))
        self.vision_request = bool(vision_request)
        self.stop_requested = False
        self.stream = None

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

        try:
            if self.stream:
                self.stream.close()
        except Exception as exc:
            log_debug("ChatWorker.stop stream close", exc)
            pass

    def should_stop(self):
        return bool(self.stop_requested or self.isInterruptionRequested())

    @staticmethod
    def _is_expected_stream_close_error(error):
        """Compatibility wrapper for expected stream-close markers.

        The shared parser owns the actual marker list, including winerror 10038
        and not a socket, so cancellation handling stays consistent.
        """
        return is_expected_stream_close_error(error)

    def run(self):
        response_text = ""
        thinking_text = ""
        last_emit_time = 0.0

        def build_combined_response():
            if thinking_text:
                return (
                    f"<|channel|>thought\n"
                    f"{thinking_text}\n"
                    f"<|channel|>\n"
                    f"{response_text}"
                )

            return response_text

        stream_opened = False

        try:
            request_started_at = time.perf_counter()
            log_debug(
                "ChatWorker.run request starting",
                f"model={self.model}, vision={self.vision_request}, messages={len(self.messages)}",
            )

            # Daily-news/document generation may override the output budget while
            # preserving the normal chat profile. Vision uses its own calmer
            # sampling and stronger repeat penalty.
            request_params = build_chat_request_params(
                model=self.model,
                messages=self.messages,
                profile="vision" if self.vision_request else "chat",
                base_url=self.base_url,
                stream=True,
                think_enabled=self.think_enabled,
                num_predict=self.num_predict,
                keep_alive=self.keep_alive,
            )

            request_timeout = (
                min(RUNTIME_CHAT_TIMEOUT_SECONDS, RUNTIME_VISION_CHAT_TIMEOUT_SECONDS)
                if self.vision_request and is_ollama_base_url(self.base_url)
                else RUNTIME_CHAT_TIMEOUT_SECONDS
            )
            log_debug(
                "ChatWorker.run runtime timeout",
                f"model={self.model}, vision={self.vision_request}, timeout={request_timeout:.1f}s",
            )
            chat_client = make_runtime_client(
                self.base_url, self.api_key, timeout=request_timeout
            )
            self.stream = chat_client.chat.completions.create(**request_params)
            stream_opened = True
            log_debug(
                "ChatWorker.run stream opened",
                f"model={self.model}, elapsed={time.perf_counter() - request_started_at:.2f}s",
            )
            first_chunk_seen = False

            for chunk in self.stream:
                if not first_chunk_seen:
                    first_chunk_seen = True
                    log_debug(
                        "ChatWorker.run first stream chunk",
                        f"model={self.model}, elapsed={time.perf_counter() - request_started_at:.2f}s",
                    )

                if self.should_stop():
                    self.stopped_response.emit(build_combined_response())
                    return

                reasoning = extract_delta_reasoning(chunk)
                content = extract_delta_text(chunk)

                if reasoning:
                    thinking_text += reasoning

                if content:
                    response_text += content

                    # The repetition-loop breaker is intentionally limited to
                    # vision/image-analysis requests. Long news briefs naturally
                    # repeat publisher names, country names, section headings,
                    # and citation patterns, which can look repetitive to a
                    # generic token-count heuristic even when the answer is
                    # valid. For normal text/news generation, rely on the
                    # finite num_predict budget and repeat_penalty instead.
                    if self.vision_request and looks_like_repetition_loop(
                        response_text
                    ):
                        try:
                            if self.stream:
                                self.stream.close()
                        except Exception as exc:
                            log_debug(
                                "ChatWorker.run repetition-loop stream close", exc
                            )
                            pass

                        self.finished_response.emit(
                            f"Generation stopped because model '{self.model}' entered a "
                            "repetition loop while analyzing the image. The page was "
                            "retrieved, but this model did not produce a stable visual "
                            "description. Select a different installed vision model and retry; "
                            "the PDF does not need to be imported again."
                        )
                        return

                # Do not enqueue one GUI event for every streamed token.
                # Large daily-news responses can contain thousands of chunks;
                # emitting the complete accumulated response for every chunk
                # creates an O(n²) copy/event workload and starves the UI thread.
                now = time.perf_counter()

                if now - last_emit_time >= self.emit_interval:
                    combined_response = build_combined_response()

                    if combined_response:
                        self.token_received.emit(combined_response)
                        last_emit_time = now

            final_response = build_combined_response()

            if self.should_stop():
                self.stopped_response.emit(final_response)
            else:
                self.finished_response.emit(final_response)

        except Exception as e:
            final_response = build_combined_response()

            if self.should_stop():
                log_debug("ChatWorker.run stream closed after stop request", e)
                self.stopped_response.emit(final_response)
                return

            if self.vision_request and "timed out" in str(e).casefold():
                log_warning(
                    "ChatWorker.run vision request timed out before first token", e
                )
                self.error_received.emit(
                    f"The vision request timed out before model '{self.model}' produced output. "
                    "This usually means the selected model is not a reliable vision model, "
                    "the image request overloaded Ollama, or the local model server stalled. "
                    "Select an installed VL/LLaVA/MiniCPM/Gemma vision model, or restart Ollama and retry."
                )
                return

            if self._is_expected_stream_close_error(e):
                log_warning("ChatWorker.run model stream disconnected", e)
                self.error_received.emit(
                    "The model stream disconnected before it finished. Retry the request; "
                    "if it repeats, restart the local model server."
                )
                return

            if is_runtime_model_not_found_error(e):
                log_warning("ChatWorker.run selected model unavailable", e)
                self.error_received.emit(
                    format_runtime_model_unavailable_message(self.model, self.base_url)
                )
                return

            log_exception("ChatWorker.run stream failure", e)
            self.error_received.emit(str(e))

        finally:
            try:
                if self.stream:
                    self.stream.close()
            except Exception as exc:
                log_debug("ChatWorker.run final stream close", exc)
                pass

            self.stream = None

            if stream_opened:
                apply_result = apply_ollama_model_keep_alive(
                    self.base_url,
                    self.model,
                    self.keep_alive,
                    timeout=4.0,
                )
                if apply_result.status not in {
                    "applied",
                    "provider_default",
                    "not_ollama",
                }:
                    log_warning(
                        "ChatWorker.run Ollama keep-alive apply skipped",
                        f"{apply_result.status}: {apply_result.message}",
                    )
                elif apply_result.applied:
                    log_debug(
                        "ChatWorker.run Ollama keep-alive applied",
                        apply_result.message,
                    )

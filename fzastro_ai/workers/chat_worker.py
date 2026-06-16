import re
import time
from collections import Counter

from PySide6.QtCore import QThread, Signal

from ..config import RUNTIME_CHAT_TIMEOUT_SECONDS
from ..logging_utils import log_debug, log_exception, log_warning
from ..runtime import (
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
    ):
        super().__init__()
        self.messages = messages
        self.model = model
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_key = normalize_runtime_api_key(api_key)
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
        """Return True for errors commonly caused by closing a live stream.

        On Windows/httpx, closing an OpenAI-compatible streaming response from
        another thread can surface as ``httpx.ReadError: [WinError 10038]`` while
        the iterator is blocked reading the next chunk. That is an expected
        cancellation/disconnect path, not a worker crash.
        """
        message = f"{type(error).__module__}.{type(error).__name__}: {error}".casefold()
        expected_markers = (
            "winerror 10038",
            "not a socket",
            "responseclosed",
            "streamclosed",
            "closedresourceerror",
            "operation aborted",
        )
        return any(marker in message for marker in expected_markers)

    @staticmethod
    def _looks_like_repetition_loop(text):
        tail = str(text or "")[-5000:].casefold()
        tokens = re.findall(r"[^\W_]+", tail, flags=re.UNICODE)

        if len(tokens) < 70:
            return False

        counts = Counter(tokens)
        most_common_count = counts.most_common(1)[0][1]

        if most_common_count >= 20 and most_common_count / len(tokens) >= 0.20:
            return True

        if len(tokens) >= 120 and len(counts) / len(tokens) < 0.25:
            return True

        trigrams = Counter(
            tuple(tokens[index : index + 3]) for index in range(len(tokens) - 2)
        )

        if trigrams and trigrams.most_common(1)[0][1] >= 8:
            return True

        return False

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

        try:
            request_started_at = time.perf_counter()
            log_debug(
                "ChatWorker.run request starting",
                f"model={self.model}, vision={self.vision_request}, messages={len(self.messages)}",
            )

            request_params = {
                "model": self.model,
                "messages": self.messages,
                "temperature": (0.12 if self.vision_request else 0.3),
                "top_p": (0.90 if self.vision_request else 0.95),
                "presence_penalty": (0.0 if self.vision_request else 0.2),
                "stream": True,
            }

            if is_ollama_base_url(self.base_url):
                request_params["extra_body"] = {
                    "think": self.think_enabled,
                    "top_k": 20,
                    "options": {
                        # Daily-news generation is large and citation-heavy. A
                        # finite output budget plus a small repetition penalty
                        # prevents pathological loops while preserving enough
                        # room for the complete briefing.
                        "num_predict": self.num_predict,
                        "repeat_penalty": (1.16 if self.vision_request else 1.08),
                        "repeat_last_n": (256 if self.vision_request else 64),
                    },
                }

            chat_client = make_runtime_client(
                self.base_url, self.api_key, timeout=RUNTIME_CHAT_TIMEOUT_SECONDS
            )
            self.stream = chat_client.chat.completions.create(**request_params)
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

                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                try:
                    delta_data = delta.model_dump()
                except Exception as exc:
                    log_exception("ChatWorker.run delta serialization", exc)
                    delta_data = {}

                content = getattr(delta, "content", None)

                if content is None and isinstance(delta_data, dict):
                    content = delta_data.get("content")

                reasoning = (
                    getattr(delta, "thinking", None)
                    or getattr(delta, "reasoning", None)
                    or getattr(delta, "reasoning_content", None)
                )

                if not reasoning and isinstance(delta_data, dict):
                    reasoning = (
                        delta_data.get("thinking")
                        or delta_data.get("reasoning")
                        or delta_data.get("reasoning_content")
                    )

                delta_extra = getattr(delta, "model_extra", None)

                if not reasoning and isinstance(delta_extra, dict):
                    reasoning = (
                        delta_extra.get("thinking")
                        or delta_extra.get("reasoning")
                        or delta_extra.get("reasoning_content")
                    )

                choice_extra = getattr(choice, "model_extra", None)

                if not reasoning and isinstance(choice_extra, dict):
                    reasoning = (
                        choice_extra.get("thinking")
                        or choice_extra.get("reasoning")
                        or choice_extra.get("reasoning_content")
                    )

                chunk_extra = getattr(chunk, "model_extra", None)

                if not reasoning and isinstance(chunk_extra, dict):
                    reasoning = (
                        chunk_extra.get("thinking")
                        or chunk_extra.get("reasoning")
                        or chunk_extra.get("reasoning_content")
                    )

                if reasoning:
                    thinking_text += str(reasoning)

                if content:
                    response_text += str(content)

                    # The repetition-loop breaker is intentionally limited to
                    # vision/image-analysis requests. Long news briefs naturally
                    # repeat publisher names, country names, section headings,
                    # and citation patterns, which can look repetitive to a
                    # generic token-count heuristic even when the answer is
                    # valid. For normal text/news generation, rely on the
                    # finite num_predict budget and repeat_penalty instead.
                    if self.vision_request and self._looks_like_repetition_loop(
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

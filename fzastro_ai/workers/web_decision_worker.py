from ..routing.tool_router import parse_tool_decision
from ..tool_manifest import build_tool_capability_prompt

from PySide6.QtCore import QThread, Signal

from ..config import RUNTIME_DECISION_TIMEOUT_SECONDS
from ..llm import build_chat_request_params
from ..logging_utils import log_exception, log_warning
from ..runtime import (
    format_runtime_model_unavailable_message,
    is_runtime_connection_error,
    is_runtime_model_not_found_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)


def parse_web_decision(raw_text):
    """Parse a constrained router response.

    Kept under the old name for compatibility with existing imports.  The
    router now understands web and local-document actions, but still returns
    the existing (action, query) tuple shape for the app signal path.
    """
    plan = parse_tool_decision(raw_text)

    if len(plan.query) > 300:
        raise ValueError("The generated tool query exceeds 300 characters.")

    return plan.action, plan.query


class ToolDecisionWorker(QThread):
    """Model-based fallback router used only after deterministic routing declines."""

    decision_ready = Signal(str, str)
    error_received = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        user_text,
        model,
        force_search=False,
        conversation_context="",
        base_url=None,
        api_key=None,
    ):
        super().__init__()
        self.user_text = user_text
        self.model = model
        self.force_search = force_search
        self.conversation_context = conversation_context
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_key = normalize_runtime_api_key(api_key)
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self):
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        if self.should_stop():
            self.stopped.emit()
            return

        if self.force_search:
            routing_instruction = (
                "Internet search is mandatory for this request. "
                "Return action web_search and generate the most effective search query."
            )
        else:
            routing_instruction = (
                "Decide whether the request should be answered normally or should use "
                "one of the app tools first. "
                "Use web_search for current events, recent news, current prices, market "
                "prices, commodity prices, oil prices, fuel prices, exchange rates, "
                "weather, schedules, laws, regulations, current office holders, current "
                "software versions, recent product information, explicit requests to "
                "search online, requests for sources, requests to find, fetch, show, or "
                "retrieve an image, photo, picture, or wallpaper, or information that may "
                "have changed. "
                "Use documents_search when the user asks to find, search, locate, or answer "
                "from imported/local documents, books, manuals, PDFs, or the knowledge library. "
                "Use documents_brief when the user asks to brief, summarize, recap, or create "
                "an overview of an imported/local document, book, manual, or PDF. "
                "Follow-up questions may contain references such as 'it', 'that', 'the price', "
                "'the barrel', 'this version', 'the book', or 'the document'. Resolve those "
                "references using the supplied recent conversation context. "
                "Use answer for writing, translation, pure mathematics, creative work, "
                "general stable explanations, or requests fully answerable from the user's "
                "message without an app tool."
            )

        capability_prompt = build_tool_capability_prompt()

        system_message = (
            "You are the tool routing component for FZAstro AI. "
            "You do not answer the user's question. "
            "You only decide whether the app should use a tool before answering. "
            f"{routing_instruction} "
            f"{capability_prompt} "
            "Return exactly one JSON object containing action, query, confidence, and reason. "
            "The action must be one of answer, web_search, documents_search, or documents_brief. "
            "When action is answer, query must be an empty string. "
            "When action is not answer, query must contain a concise standalone query of no more than 300 characters. "
            "Resolve ambiguous follow-up references using the recent conversation context. "
            "The generated query must be standalone and must include the resolved subject. "
            "Do not include markdown, explanations, reasoning, code fences, URLs, local file paths, or additional fields."
        )

        decision_input = (
            "[RECENT CONVERSATION]\n"
            f"{self.conversation_context.strip() or 'No previous conversation.'}\n\n"
            "[CURRENT USER REQUEST]\n"
            f"{self.user_text}"
        )

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "fzastro_web_decision",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "answer",
                                "web_search",
                                "documents_search",
                                "documents_brief",
                            ],
                        },
                        "query": {"type": "string"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["action", "query", "confidence", "reason"],
                    "additionalProperties": False,
                },
            },
        }

        try:
            decision_client = make_runtime_client(
                self.base_url, self.api_key, timeout=RUNTIME_DECISION_TIMEOUT_SECONDS
            )
            request_params = build_chat_request_params(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": decision_input},
                ],
                profile="router",
                base_url=self.base_url,
                stream=False,
                response_format=response_format,
            )

            try:
                response = decision_client.chat.completions.create(**request_params)
            except Exception as exc:
                if is_runtime_connection_error(exc) or is_runtime_model_not_found_error(
                    exc
                ):
                    raise

                # Some OpenAI-compatible servers do not implement JSON schema
                # response_format. Retry with a plain text JSON instruction.
                # This is an expected compatibility fallback and should not
                # write a traceback unless the retry itself fails.
                log_warning("WebDecisionWorker.run response_format retry", exc)
                request_params.pop("response_format", None)
                response = decision_client.chat.completions.create(**request_params)

            if self.should_stop():
                self.stopped.emit()
                return

            if not response.choices:
                raise ValueError("The model returned no web decision.")

            raw_decision = response.choices[0].message.content or ""
            action, query = parse_web_decision(raw_decision)

            if self.force_search and action != "web_search":
                raise ValueError(
                    "The model did not generate a mandatory web search query."
                )

            if self.should_stop():
                self.stopped.emit()
                return

            self.decision_ready.emit(action, query)

        except Exception as e:
            if is_runtime_model_not_found_error(e):
                log_warning("WebDecisionWorker.run selected model unavailable", e)
                user_error = (
                    format_runtime_model_unavailable_message(self.model, self.base_url)
                    + " Web routing will use deterministic fallback."
                )
            elif is_runtime_connection_error(e):
                log_warning(
                    "WebDecisionWorker.run provider unavailable or timed out", e
                )
                user_error = (
                    "Web routing timed out or the selected model provider is unavailable. "
                    "Falling back to deterministic routing."
                )
            else:
                log_exception("WebDecisionWorker.run", e)
                user_error = str(e)

            if self.should_stop():
                self.stopped.emit()
            else:
                self.error_received.emit(user_error)


# Backward-compatible name retained for older imports and tests.
WebDecisionWorker = ToolDecisionWorker

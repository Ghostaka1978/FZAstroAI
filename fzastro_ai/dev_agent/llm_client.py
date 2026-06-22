from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from ..config import (
    API_KEY,
    BASE_URL,
    DEFAULT_MODEL_NAME,
    RUNTIME_DECISION_TIMEOUT_SECONDS,
)
from ..llm import build_chat_request_params
from ..runtime import (
    is_local_ollama_base_url,
    is_local_ollama_listener_present,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
    ollama_root_url,
)


class DevAgentLLMError(RuntimeError):
    """Raised when the Developer Agent model backend cannot respond safely."""


@dataclass(frozen=True)
class OllamaAgentConfig:
    """Connection settings for the local Developer Agent model."""

    model: str = DEFAULT_MODEL_NAME
    base_url: str = BASE_URL
    timeout_seconds: float = RUNTIME_DECISION_TIMEOUT_SECONDS
    keep_alive: str | None = "0"
    temperature: float = 0.1
    num_ctx: int | None = 128000

    @property
    def normalized_base_url(self) -> str:
        return normalize_runtime_base_url(self.base_url)

    @property
    def ollama_root(self) -> str:
        return ollama_root_url(self.base_url)


@dataclass(frozen=True)
class AgentModelResponse:
    """Text returned by an agent-capable LLM backend."""

    text: str
    model: str
    backend: str = "ollama"
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class RuntimeAgentConfig:
    """Active FZAstro runtime settings for Developer Agent model calls.

    The Developer Agent should use the same OpenAI-compatible runtime path as
    normal chat instead of owning a separate endpoint stack. The UI supplies the
    active model, base URL, API key, and Ollama keep-alive value from the main
    app controls.
    """

    model: str = DEFAULT_MODEL_NAME
    base_url: str = BASE_URL
    api_key: str = API_KEY
    timeout_seconds: float = RUNTIME_DECISION_TIMEOUT_SECONDS
    keep_alive: str | None = None
    temperature: float = 0.1
    num_ctx: int | None = 128000
    num_predict: int | None = 4096

    @property
    def normalized_base_url(self) -> str:
        return normalize_runtime_base_url(self.base_url)

    @property
    def normalized_api_key(self) -> str:
        return normalize_runtime_api_key(self.api_key)


class RuntimeAgentClient:
    """Developer Agent client using FZAstro's existing model runtime.

    This client intentionally routes through ``make_runtime_client`` and
    ``build_chat_request_params`` so agent calls behave like the main app's
    OpenAI-compatible chat calls. For local Ollama it only checks the OS
    listener table before sending a request; it never starts or wakes Ollama by
    probing HTTP endpoints.
    """

    def __init__(self, config: RuntimeAgentConfig | None = None):
        self.config = config or RuntimeAgentConfig()

    def _ensure_local_listener(self) -> None:
        if is_local_ollama_base_url(self.config.base_url):
            if not is_local_ollama_listener_present(self.config.base_url, timeout=0.5):
                raise DevAgentLLMError(
                    "Local Ollama is not listening. OpenClaude will not auto-start it."
                )

    def is_available(self) -> bool:
        if is_local_ollama_base_url(self.config.base_url):
            return is_local_ollama_listener_present(self.config.base_url, timeout=0.5)
        # Remote/OpenAI-compatible providers are validated by the actual request.
        return True

    @staticmethod
    def _response_text(response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices")
            first = choices[0] if isinstance(choices, list) and choices else None
            message = first.get("message") if isinstance(first, dict) else None
            content = message.get("content") if isinstance(message, dict) else ""
            return str(content or "").strip()

        choices = getattr(response, "choices", None)
        first = choices[0] if choices else None
        message = getattr(first, "message", None) if first is not None else None
        content = getattr(message, "content", "") if message is not None else ""
        return str(content or "").strip()

    @staticmethod
    def _coerce_delta_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item or ""))
            return "".join(parts)
        return str(value)

    @classmethod
    def _chunk_delta_text(cls, chunk: Any) -> str:
        """Extract visible text from an OpenAI-compatible streaming chunk.

        Ollama and OpenAI-compatible servers usually stream content through
        ``choices[0].delta.content``. Some local coding models expose auxiliary
        reasoning fields instead, so this extractor accepts those too without
        treating them as hidden validation output.
        """
        if isinstance(chunk, dict):
            choices = chunk.get("choices")
            first = choices[0] if isinstance(choices, list) and choices else None
            delta = first.get("delta") if isinstance(first, dict) else None
            if isinstance(delta, dict):
                # Only display final assistant content. Reasoning fields are
                # intentionally ignored so local reasoning models do not leak
                # scratchpad text into the OpenClaude chat.
                text = cls._coerce_delta_value(delta.get("content"))
                return text
            return ""

        choices = getattr(chunk, "choices", None)
        first = choices[0] if choices else None
        delta = getattr(first, "delta", None) if first is not None else None
        text = cls._coerce_delta_value(
            getattr(delta, "content", None) if delta is not None else None
        )
        return text

    def _format_runtime_exception(self, exc: Exception) -> str:
        raw = str(exc).strip() or exc.__class__.__name__
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        model = str(self.config.model or DEFAULT_MODEL_NAME).strip()
        base_url = self.config.normalized_base_url
        lower = raw.casefold()
        prefix = (
            "Developer Agent model request failed through the active FZAstro runtime"
        )

        if status_code == 404 or "model" in lower and "not found" in lower:
            return (
                f"{prefix}: active model `{model}` was not found at `{base_url}`. "
                "Use the main app model selector/refresh button and choose an installed model, "
                "then run Ask Active Model again. Raw provider error: " + raw
            )

        return f"{prefix} using `{model}` at `{base_url}`: {raw}"

    def _chat_request_params(
        self, messages: list[dict[str, str]], *, format_json: bool, stream: bool
    ) -> dict[str, Any]:
        response_format = {"type": "json_object"} if format_json else None
        return build_chat_request_params(
            model=self.config.model,
            messages=messages,
            profile="router",
            base_url=self.config.base_url,
            stream=stream,
            response_format=response_format,
            temperature=self.config.temperature,
            num_ctx=self.config.num_ctx,
            num_predict=self.config.num_predict,
            keep_alive=self.config.keep_alive,
        )

    def chat(
        self, messages: list[dict[str, str]], *, format_json: bool = False
    ) -> AgentModelResponse:
        self._ensure_local_listener()
        request_params = self._chat_request_params(
            messages, format_json=format_json, stream=False
        )
        try:
            client = make_runtime_client(
                self.config.base_url,
                self.config.api_key,
                timeout=self.config.timeout_seconds,
            )
            response = client.chat.completions.create(**request_params)
        except Exception as exc:
            message = self._format_runtime_exception(exc)
            raise DevAgentLLMError(message) from exc

        return AgentModelResponse(
            text=self._response_text(response),
            model=str(self.config.model or DEFAULT_MODEL_NAME),
            backend="fzastro-runtime",
            raw=None,
        )

    def stream_chat(self, messages: list[dict[str, str]], *, format_json: bool = False):
        """Yield visible text deltas from the active FZAstro runtime.

        The request still uses the same main-app runtime configuration. This is
        only a transport change from blocking completion to incremental chunks,
        so OpenClaude stays aligned with normal chat settings and does
        not auto-start local Ollama.
        """
        self._ensure_local_listener()
        request_params = self._chat_request_params(
            messages, format_json=format_json, stream=True
        )
        try:
            client = make_runtime_client(
                self.config.base_url,
                self.config.api_key,
                timeout=self.config.timeout_seconds,
            )
            stream = client.chat.completions.create(**request_params)
            for chunk in stream:
                text = self._chunk_delta_text(chunk)
                if text:
                    yield text
        except Exception as exc:
            message = self._format_runtime_exception(exc)
            raise DevAgentLLMError(message) from exc


class OllamaAgentClient:
    """Small local coding-agent client for Ollama-compatible endpoints.

    The client never starts Ollama. For the default local endpoint it first
    checks the OS listener table through the existing runtime helper, then uses
    regular HTTP only when a listener is already present. It supports both the
    native Ollama API (``/api/chat``) and OpenAI-compatible local endpoints
    (``/v1/chat/completions``), because FZAstro's runtime base URL is normally
    stored in OpenAI-compatible form.
    """

    def __init__(self, config: OllamaAgentConfig | None = None):
        self.config = config or OllamaAgentConfig()

    @property
    def native_chat_url(self) -> str:
        return f"{self.config.ollama_root}/api/chat"

    @property
    def native_tags_url(self) -> str:
        return f"{self.config.ollama_root}/api/tags"

    @property
    def openai_chat_url(self) -> str:
        return f"{self.config.normalized_base_url}/chat/completions"

    @property
    def openai_models_url(self) -> str:
        return f"{self.config.normalized_base_url}/models"

    def _ensure_local_listener(self) -> None:
        if is_local_ollama_base_url(self.config.base_url):
            if not is_local_ollama_listener_present(self.config.base_url, timeout=0.5):
                raise DevAgentLLMError(
                    "Local Ollama is not listening. OpenClaude will not auto-start it."
                )

    def is_available(self) -> bool:
        if is_local_ollama_base_url(self.config.base_url):
            if not is_local_ollama_listener_present(self.config.base_url, timeout=0.5):
                return False

        timeout = min(float(self.config.timeout_seconds), 5.0)
        for url in (self.native_tags_url, self.openai_models_url):
            try:
                response = requests.get(url, timeout=timeout)
            except requests.RequestException:
                continue
            if response.status_code == 200:
                return True
        return False

    def _native_payload(
        self, messages: list[dict[str, str]], *, format_json: bool
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": self.config.temperature}
        if self.config.num_ctx:
            options["num_ctx"] = int(self.config.num_ctx)

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if self.config.keep_alive is not None:
            payload["keep_alive"] = self.config.keep_alive
        if format_json:
            payload["format"] = "json"
        return payload

    def _openai_payload(
        self, messages: list[dict[str, str]], *, format_json: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "temperature": self.config.temperature,
        }
        if format_json:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            url,
            json=payload,
            timeout=float(self.config.timeout_seconds),
        )
        response.raise_for_status()
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise DevAgentLLMError(
                f"Developer Agent model endpoint returned non-JSON HTTP output: {url}"
            ) from exc
        if not isinstance(data, dict):
            raise DevAgentLLMError(
                f"Developer Agent model endpoint returned unexpected output: {url}"
            )
        return data

    def _chat_native(
        self, messages: list[dict[str, str]], *, format_json: bool
    ) -> AgentModelResponse:
        data = self._post_json(
            self.native_chat_url,
            self._native_payload(messages, format_json=format_json),
        )
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else ""
        return AgentModelResponse(
            text=str(content or "").strip(),
            model=str(data.get("model") or self.config.model),
            backend="ollama-native",
            raw=data,
        )

    def _chat_openai_compatible(
        self, messages: list[dict[str, str]], *, format_json: bool
    ) -> AgentModelResponse:
        data = self._post_json(
            self.openai_chat_url,
            self._openai_payload(messages, format_json=format_json),
        )
        choices = data.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else ""
        return AgentModelResponse(
            text=str(content or "").strip(),
            model=str(data.get("model") or self.config.model),
            backend="openai-compatible",
            raw=data,
        )

    @staticmethod
    def _status_from_exception(exc: requests.RequestException) -> int | None:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)

    def chat(
        self, messages: list[dict[str, str]], *, format_json: bool = False
    ) -> AgentModelResponse:
        self._ensure_local_listener()

        errors: list[str] = []
        try:
            return self._chat_native(messages, format_json=format_json)
        except requests.RequestException as exc:
            errors.append(f"{self.native_chat_url}: {exc}")
            if self._status_from_exception(exc) not in {404, 405}:
                raise DevAgentLLMError(
                    "Developer Agent model request failed: " + " | ".join(errors)
                ) from exc

        try:
            return self._chat_openai_compatible(messages, format_json=format_json)
        except requests.RequestException as exc:
            errors.append(f"{self.openai_chat_url}: {exc}")
            raise DevAgentLLMError(
                "Developer Agent model request failed. Tried native Ollama and OpenAI-compatible endpoints: "
                + " | ".join(errors)
            ) from exc

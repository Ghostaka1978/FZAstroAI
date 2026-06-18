"""Qt-free final chat request planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..config import (
    PYTHON_APPLICATION_CAPABILITY_PROMPT,
    PYTHON_AUTO_TEST_PROMPT,
    RESPONSE_STYLE_PROMPT,
)
from ..conversation_context import build_recent_chat_context
from .content import normalize_content_for_model
from .context_budget import ContextBudgetResult, enforce_context_budget
from .model_catalog import get_ollama_model_context_limit


@dataclass(frozen=True)
class ChatGenerationSettings:
    profile: str
    num_predict: int
    think_enabled: bool
    emit_interval: float
    stream_render_interval_ms: int


@dataclass(frozen=True)
class ChatRequestPlan:
    api_messages: list[dict[str, Any]]
    context_budget: ContextBudgetResult
    generation_settings: ChatGenerationSettings


def build_python_execution_context(*, python_auto_test_request: bool = False) -> str:
    context = "\n\n" + PYTHON_APPLICATION_CAPABILITY_PROMPT.strip()

    if python_auto_test_request:
        context += "\n\n" + PYTHON_AUTO_TEST_PROMPT.strip()

    return context


def build_response_style_context() -> str:
    return "\n\n" + RESPONSE_STYLE_PROMPT.strip()


def choose_chat_generation_settings(
    *,
    is_news_generation: bool = False,
    request_requires_vision: bool = False,
    is_exhaustive_document_request: bool = False,
) -> ChatGenerationSettings:
    if is_news_generation:
        return ChatGenerationSettings(
            profile="daily_news",
            num_predict=12000,
            think_enabled=False,
            emit_interval=0.14,
            stream_render_interval_ms=280,
        )

    if request_requires_vision:
        return ChatGenerationSettings(
            profile="vision",
            num_predict=1200,
            think_enabled=False,
            emit_interval=0.07,
            stream_render_interval_ms=90,
        )

    if is_exhaustive_document_request:
        return ChatGenerationSettings(
            profile="document_exhaustive",
            num_predict=12000,
            think_enabled=False,
            emit_interval=0.07,
            stream_render_interval_ms=90,
        )

    return ChatGenerationSettings(
        profile="chat",
        num_predict=4096,
        think_enabled=True,
        emit_interval=0.07,
        stream_render_interval_ms=90,
    )


def _combined_system_prompt(
    *,
    system_prompt: str = "",
    recent_chat_context: str = "",
    memory_context: str = "",
    knowledge_context: str = "",
    python_execution_context: str = "",
) -> str:
    return (
        str(system_prompt or "")
        + str(recent_chat_context or "")
        + str(memory_context or "")
        + str(knowledge_context or "")
        + build_response_style_context()
        + str(python_execution_context or "")
    ).strip()


def build_chat_request_plan(
    *,
    system_prompt: str,
    history_messages: Sequence[Mapping[str, Any]],
    current_user_content: Any,
    allow_images: bool,
    model: str | None = None,
    base_url: str | None = None,
    context_limit: int | None = None,
    recent_chat_context: str | None = None,
    memory_context: str = "",
    knowledge_context: str = "",
    python_auto_test_request: bool = False,
    is_news_generation: bool = False,
    request_requires_vision: bool = False,
    is_exhaustive_document_request: bool = False,
) -> ChatRequestPlan:
    history = list(history_messages or [])

    if recent_chat_context is None:
        recent_chat_context = build_recent_chat_context(history)

    generation_settings = choose_chat_generation_settings(
        is_news_generation=is_news_generation,
        request_requires_vision=request_requires_vision,
        is_exhaustive_document_request=is_exhaustive_document_request,
    )

    combined_system_prompt = _combined_system_prompt(
        system_prompt=system_prompt,
        recent_chat_context=recent_chat_context,
        memory_context=memory_context,
        knowledge_context=knowledge_context,
        python_execution_context=build_python_execution_context(
            python_auto_test_request=python_auto_test_request
        ),
    )
    api_messages: list[dict[str, Any]] = []

    if combined_system_prompt:
        api_messages.append({"role": "system", "content": combined_system_prompt})

    for message in history:
        api_messages.append(
            {
                "role": message.get("role", "user"),
                "content": normalize_content_for_model(
                    message.get("content"), allow_images=allow_images
                ),
            }
        )

    api_messages.append(
        {
            "role": "user",
            "content": normalize_content_for_model(
                current_user_content, allow_images=allow_images
            ),
        }
    )

    resolved_context_limit = (
        context_limit
        if context_limit is not None
        else get_ollama_model_context_limit(model, base_url)
    )
    context_budget = enforce_context_budget(
        api_messages,
        context_limit=resolved_context_limit,
        generation_budget=generation_settings.num_predict,
    )

    if context_budget.generation_budget == generation_settings.num_predict:
        final_generation_settings = generation_settings
    else:
        final_generation_settings = ChatGenerationSettings(
            profile=generation_settings.profile,
            num_predict=context_budget.generation_budget,
            think_enabled=generation_settings.think_enabled,
            emit_interval=generation_settings.emit_interval,
            stream_render_interval_ms=generation_settings.stream_render_interval_ms,
        )

    return ChatRequestPlan(
        api_messages=context_budget.messages,
        context_budget=context_budget,
        generation_settings=final_generation_settings,
    )

"""Qt-free helpers for the FZAstro AI model runtime."""

from .content import (
    estimate_messages_context_tokens,
    estimate_model_content_tokens,
    estimate_token_count,
    format_token_budget_count,
    normalize_content_for_model,
)
from .context_budget import ContextBudgetResult, enforce_context_budget
from .model_catalog import (
    configure_model_catalog_runtime,
    find_installed_vision_model,
    get_available_models,
    get_ollama_model_capabilities,
    get_ollama_model_context_limit,
    is_experimental_vision_model,
    ollama_model_name_has_reliable_vision_hint,
    ollama_model_name_is_qwen_text_only,
    parse_ollama_context_limit,
)
from .profiles import GENERATION_PROFILES, GenerationProfile, get_generation_profile
from .prompt_builder import (
    ChatGenerationSettings,
    ChatRequestPlan,
    build_chat_request_plan,
    build_python_execution_context,
    choose_chat_generation_settings,
)
from .request_builder import build_chat_request_params
from .stream_parser import (
    extract_delta_reasoning,
    extract_delta_text,
    is_expected_stream_close_error,
    looks_like_repetition_loop,
)

__all__ = [
    "GENERATION_PROFILES",
    "GenerationProfile",
    "ContextBudgetResult",
    "ChatGenerationSettings",
    "ChatRequestPlan",
    "build_chat_request_params",
    "build_chat_request_plan",
    "build_python_execution_context",
    "configure_model_catalog_runtime",
    "estimate_messages_context_tokens",
    "estimate_model_content_tokens",
    "estimate_token_count",
    "enforce_context_budget",
    "find_installed_vision_model",
    "format_token_budget_count",
    "extract_delta_reasoning",
    "extract_delta_text",
    "get_available_models",
    "get_generation_profile",
    "get_ollama_model_capabilities",
    "get_ollama_model_context_limit",
    "choose_chat_generation_settings",
    "is_expected_stream_close_error",
    "is_experimental_vision_model",
    "looks_like_repetition_loop",
    "normalize_content_for_model",
    "ollama_model_name_has_reliable_vision_hint",
    "ollama_model_name_is_qwen_text_only",
    "parse_ollama_context_limit",
]

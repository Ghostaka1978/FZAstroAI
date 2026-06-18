"""Model discovery, capability, and context-window helpers."""

from __future__ import annotations

import re

import requests

from ..config import (
    API_KEY,
    BASE_URL,
    DEFAULT_MODEL_NAME,
    RUNTIME_MODEL_LIST_TIMEOUT_SECONDS,
)
from ..logging_utils import log_exception, log_warning
from ..runtime import (
    is_ollama_base_url,
    is_runtime_connection_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)

_ACTIVE_BASE_URL = BASE_URL
_ACTIVE_API_KEY = API_KEY
_MODEL_CAPABILITY_CACHE = {}
_MODEL_CONTEXT_LIMIT_CACHE = {}


def configure_model_catalog_runtime(base_url=None, api_key=None):
    """Update the provider used by model-catalog helpers without importing UI."""
    global _ACTIVE_BASE_URL, _ACTIVE_API_KEY

    _ACTIVE_BASE_URL = normalize_runtime_base_url(base_url)
    _ACTIVE_API_KEY = normalize_runtime_api_key(api_key)


def get_available_models(base_url=None, api_key=None):
    try:
        runtime_client = make_runtime_client(
            base_url if base_url is not None else _ACTIVE_BASE_URL,
            api_key if api_key is not None else _ACTIVE_API_KEY,
            timeout=RUNTIME_MODEL_LIST_TIMEOUT_SECONDS,
        )
        response = runtime_client.models.list()
        models = [str(model.id).strip() for model in response.data if model.id]
        return models if models else [DEFAULT_MODEL_NAME]
    except Exception as exc:
        if is_runtime_connection_error(exc):
            log_warning("get_available_models provider unavailable", exc)
        else:
            log_exception("get_available_models", exc)
        return [DEFAULT_MODEL_NAME]


def parse_ollama_context_limit(payload):
    """Extract configured or advertised context length from /api/show payload."""
    if not isinstance(payload, dict):
        return None

    # Prefer explicit Modelfile runtime setting because that is what the app will
    # actually use when no per-request num_ctx override is sent.
    for field_name in ("parameters", "modelfile"):
        field_text = str(payload.get(field_name) or "")

        for match in re.finditer(
            r"(?im)^\s*(?:PARAMETER\s+)?num_ctx\s+(?P<value>\d{3,9})\s*$",
            field_text,
        ):
            try:
                value = int(match.group("value"))
            except (TypeError, ValueError):
                continue

            if value > 0:
                return value

    candidates = []
    model_info = payload.get("model_info") or {}

    if isinstance(model_info, dict):
        for key, value in model_info.items():
            key_text = str(key or "").casefold()

            if "context_length" not in key_text and "context length" not in key_text:
                continue

            try:
                number = int(value)
            except (TypeError, ValueError):
                continue

            if number > 0:
                candidates.append(number)

    return max(candidates) if candidates else None


def get_ollama_model_context_limit(model_name, base_url=None):
    """Return estimated context-window size for an Ollama model, if available."""
    clean_model = str(model_name or "").strip()
    clean_base_url = normalize_runtime_base_url(
        base_url if base_url is not None else _ACTIVE_BASE_URL
    )
    cache_key = (clean_base_url, clean_model)

    if not clean_model:
        return None

    if cache_key in _MODEL_CONTEXT_LIMIT_CACHE:
        return _MODEL_CONTEXT_LIMIT_CACHE[cache_key]

    if not is_ollama_base_url(clean_base_url):
        _MODEL_CONTEXT_LIMIT_CACHE[cache_key] = None
        return None

    try:
        ollama_root = clean_base_url.rstrip("/").rsplit("/v1", 1)[0].rstrip("/")
        response = requests.post(
            f"{ollama_root}/api/show",
            json={"model": clean_model},
            timeout=3,
        )
        response.raise_for_status()
        context_limit = parse_ollama_context_limit(response.json())
    except Exception as exc:
        log_exception("get_ollama_model_context_limit line 4555", exc)
        context_limit = None

    _MODEL_CONTEXT_LIMIT_CACHE[cache_key] = context_limit
    return context_limit


_QWEN_TEXT_ONLY_PREFIXES = (
    "qwen:",
    "qwen1",
    "qwen2",
    "qwen2.5",
    "qwen3",
)


def ollama_model_name_has_reliable_vision_hint(model_name):
    """Return True when the model name itself looks like a vision model.

    Ollama /api/show capabilities are the primary source, but some model
    wrappers can advertise vision too broadly. For Qwen-family models, require
    an explicit VL marker so a text model such as qwen3:32b/qwen3.6:35b is not
    selected for image requests and left waiting forever before first token.
    """

    clean_name = str(model_name or "").strip().casefold()

    if not clean_name:
        return False

    reliable_markers = (
        "vision",
        "-vl",
        "_vl",
        ":vl",
        "vl:",
        "qwen3vl",
        "qwen2.5vl",
        "qwen2vl",
        "llava",
        "bakllava",
        "moondream",
        "minicpm-v",
        "minicpmv",
        "minicpm-o",
        "minicpmo",
        "gemma3",
        "gemma-3",
        "gemma4",
        "gemma-4",
        "granite3.2-vision",
        "granite-vision",
    )
    return any(marker in clean_name for marker in reliable_markers)


def ollama_model_name_is_qwen_text_only(model_name):
    """Return True for Qwen text-model names that should not inspect images."""

    clean_name = str(model_name or "").strip().casefold()

    if not clean_name:
        return False

    if "vl" in clean_name:
        return False

    return clean_name.startswith(_QWEN_TEXT_ONLY_PREFIXES)


def get_ollama_model_capabilities(model_name):
    """Return Ollama capabilities, or None when the local API is unavailable."""
    clean_model = str(model_name or "").strip()

    if not clean_model:
        return None

    if clean_model in _MODEL_CAPABILITY_CACHE:
        return _MODEL_CAPABILITY_CACHE[clean_model]

    try:
        active_base_url = normalize_runtime_base_url(_ACTIVE_BASE_URL)

        if not is_ollama_base_url(active_base_url):
            return None

        ollama_root = active_base_url.rsplit("/v1", 1)[0].rstrip("/")
        response = requests.post(
            f"{ollama_root}/api/show",
            json={"model": clean_model},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        capabilities = payload.get("capabilities") or []

        if isinstance(capabilities, str):
            capabilities = [capabilities]

        normalized = {
            str(value).strip().lower() for value in capabilities if str(value).strip()
        }

        if "vision" in normalized and ollama_model_name_is_qwen_text_only(clean_model):
            normalized = set(normalized)
            normalized.discard("vision")
            log_warning(
                "get_ollama_model_capabilities ignored unreliable vision capability",
                f"model={clean_model}",
            )

        _MODEL_CAPABILITY_CACHE[clean_model] = normalized
        return normalized
    except Exception as exc:
        log_exception("get_ollama_model_capabilities line 4646", exc)
        return None


def find_installed_vision_model(exclude_model=None):
    """Find an installed Ollama model that explicitly advertises vision."""
    excluded = str(exclude_model or "").strip()
    models = [
        str(model).strip() for model in get_available_models() if str(model).strip()
    ]

    vision_name_hints = (
        "vision",
        "qwen3-vl",
        "qwen2.5-vl",
        "qwen2-vl",
        "llava",
        "bakllava",
        "moondream",
        "minicpm-v",
        "gemma4",
        "gemma-4",
        "gemma3",
    )
    experimental_name_hints = (
        "abliterated",
        "uncensored",
        "uncen",
        "huihui",
    )

    models.sort(
        key=lambda name: (
            not any(hint in name.lower() for hint in vision_name_hints),
            any(hint in name.lower() for hint in experimental_name_hints),
            name.lower(),
        )
    )

    for model_name in models:
        if model_name == excluded:
            continue

        capabilities = get_ollama_model_capabilities(model_name)

        if capabilities is not None and "vision" in capabilities:
            if ollama_model_name_is_qwen_text_only(model_name):
                log_warning(
                    "find_installed_vision_model skipped Qwen text-only model",
                    f"model={model_name}",
                )
                continue

            return model_name

    return None


def is_experimental_vision_model(model_name):
    clean_name = str(model_name or "").strip().lower()
    return any(
        marker in clean_name
        for marker in ("abliterated", "uncensored", "uncen", "huihui")
    )

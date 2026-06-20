"""Shared request construction for OpenAI-compatible chat completions."""

from __future__ import annotations

from typing import Any

from ..runtime import (
    is_ollama_base_url,
    normalize_ollama_keep_alive_value,
    normalize_runtime_base_url,
)
from .profiles import GenerationProfile, get_generation_profile


def _positive_int(value):
    if value is None:
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _set_if_not_none(target: dict[str, Any], key: str, value):
    if value is not None:
        target[key] = value


def build_chat_request_params(
    *,
    model,
    messages,
    profile: str | GenerationProfile = "chat",
    base_url=None,
    stream=True,
    response_format=None,
    temperature=None,
    top_p=None,
    presence_penalty=None,
    think_enabled=None,
    num_predict=None,
    num_ctx=None,
    repeat_penalty=None,
    repeat_last_n=None,
    max_tokens=None,
    keep_alive=None,
    extra_params: dict[str, Any] | None = None,
):
    """Build provider-appropriate chat completion parameters.

    Ollama-compatible endpoints receive Ollama-specific generation options in
    ``extra_body``. Other OpenAI-compatible providers receive ``max_tokens`` when
    an output budget is known and never receive Ollama-only options.
    """
    resolved_profile = get_generation_profile(profile).with_overrides(
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        think=think_enabled,
        num_predict=num_predict,
        num_ctx=num_ctx,
        repeat_penalty=repeat_penalty,
        repeat_last_n=repeat_last_n,
    )
    clean_base_url = normalize_runtime_base_url(base_url)
    output_budget = _positive_int(max_tokens) or _positive_int(
        resolved_profile.num_predict
    )

    request_params: dict[str, Any] = {
        "model": str(model or "").strip(),
        "messages": list(messages or []),
        "stream": bool(stream),
    }

    _set_if_not_none(request_params, "temperature", resolved_profile.temperature)
    _set_if_not_none(request_params, "top_p", resolved_profile.top_p)
    _set_if_not_none(
        request_params, "presence_penalty", resolved_profile.presence_penalty
    )

    if response_format is not None:
        request_params["response_format"] = response_format

    if is_ollama_base_url(clean_base_url):
        options: dict[str, Any] = {}
        _set_if_not_none(options, "num_predict", output_budget)
        _set_if_not_none(options, "repeat_penalty", resolved_profile.repeat_penalty)
        _set_if_not_none(options, "repeat_last_n", resolved_profile.repeat_last_n)
        _set_if_not_none(options, "num_ctx", _positive_int(resolved_profile.num_ctx))

        if resolved_profile.include_temperature_option:
            _set_if_not_none(options, "temperature", resolved_profile.temperature)

        extra_body: dict[str, Any] = {}
        _set_if_not_none(extra_body, "think", resolved_profile.think)
        _set_if_not_none(extra_body, "top_k", resolved_profile.top_k)
        _set_if_not_none(
            extra_body, "keep_alive", normalize_ollama_keep_alive_value(keep_alive)
        )

        if options:
            extra_body["options"] = options

        if extra_body:
            request_params["extra_body"] = extra_body
    elif output_budget is not None:
        request_params["max_tokens"] = output_budget

    if extra_params:
        request_params.update(extra_params)

    return request_params

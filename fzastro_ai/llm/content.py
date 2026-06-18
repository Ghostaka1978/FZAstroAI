"""Content normalization and lightweight token estimates for model requests."""

from __future__ import annotations

import json


def estimate_token_count(text):
    """Fast UI estimate for token budget display.

    Ollama's OpenAI-compatible stream does not reliably return live prompt and
    completion token counts for every local model, so the status bar uses the
    same practical approximation already used elsewhere in the app: roughly four
    characters per token. Treat this as a context-budget estimate, not an exact
    tokenizer measurement.
    """
    clean_text = str(text or "")

    if not clean_text:
        return 0

    return max(1, len(clean_text) // 4)


def format_token_budget_count(value):
    """Compact token count for the status bar."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "?"

    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m"

    if number >= 10_000:
        return f"{number / 1000:.1f}k"

    if number >= 1000:
        return f"{number / 1000:.2f}k"

    return str(max(0, number))


def estimate_model_content_tokens(content):
    """Estimate prompt tokens for string or OpenAI content-array messages."""
    if isinstance(content, list):
        total = 0

        for part in content:
            if not isinstance(part, dict):
                total += estimate_token_count(part)
                continue

            part_type = str(part.get("type") or "").strip().lower()

            if part_type in {"text", "input_text"}:
                total += estimate_token_count(part.get("text") or "")
            elif part_type in {"image", "image_url", "input_image"}:
                # Image-token cost differs by model and resolution. Use a small
                # fixed reserve so the context bar warns users that visual
                # requests are heavier without claiming exact tokenizer data.
                total += 1024
            else:
                total += estimate_token_count(json.dumps(part, ensure_ascii=False))

        return total

    return estimate_token_count(content)


def estimate_messages_context_tokens(messages):
    """Estimate total input-context tokens for the request sent to the model."""
    total = 0

    for message in messages or []:
        if not isinstance(message, dict):
            total += estimate_token_count(message)
            continue

        # Small per-message overhead for role separators / chat template tokens.
        total += 4
        total += estimate_token_count(message.get("role") or "")
        total += estimate_model_content_tokens(message.get("content") or "")

    return max(0, int(total))


def normalize_content_for_model(content, allow_images=True):
    """Normalize OpenAI content arrays for the target Ollama model.

    Text-only arrays are always flattened to a normal string. When the target
    model has no vision capability, historical image parts are replaced by a
    short placeholder so one old image cannot break every later text reply.
    """
    if not isinstance(content, list):
        return content

    text_parts = []
    contains_image = False

    for part in content:
        if not isinstance(part, dict):
            if allow_images:
                return content
            continue

        part_type = str(part.get("type") or "").strip().lower()

        if part_type in {"text", "input_text"}:
            text_parts.append(str(part.get("text") or ""))
            continue

        if part_type in {"image", "image_url", "input_image"}:
            contains_image = True
            continue

        if allow_images:
            return content

    if contains_image and allow_images:
        return content

    if contains_image:
        text_parts.append(
            "[An image was attached in this earlier message, but it is omitted "
            "from this request because the selected model does not support vision.]"
        )

    return "\n".join(value for value in text_parts if value).strip()

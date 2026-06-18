"""Context-window budgeting for final chat-completion requests."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from .content import estimate_messages_context_tokens, estimate_model_content_tokens

_RECENT_CHAT_CONTEXT_RE = re.compile(
    r"\n*\[RECENT CHAT CONTEXT\].*?\[/RECENT CHAT CONTEXT\]\s*",
    flags=re.DOTALL,
)
_KNOWLEDGE_EXCERPT_RE = re.compile(
    r"\n*\[KNOWLEDGE EXCERPT (?P<index>\d+)\].*?\[/KNOWLEDGE EXCERPT (?P=index)\]\s*",
    flags=re.DOTALL,
)


@dataclass(frozen=True)
class ContextBudgetResult:
    messages: list[dict[str, Any]]
    prompt_tokens: int
    context_limit: int | None
    generation_budget: int
    trimmed_sections: tuple[str, ...]
    warnings: tuple[str, ...]


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _last_message_index(messages: list[dict[str, Any]]) -> int:
    return len(messages) - 1


def _has_prior_chat_messages(messages: list[dict[str, Any]]) -> bool:
    pinned_index = _last_message_index(messages)

    for index, message in enumerate(messages):
        if index == pinned_index:
            continue

        if str(message.get("role") or "").strip().lower() in {"user", "assistant"}:
            return True

    return False


def _strip_duplicate_recent_chat_context(
    messages: list[dict[str, Any]], trimmed_sections: list[str]
) -> None:
    if not _has_prior_chat_messages(messages):
        return

    for message in messages:
        if str(message.get("role") or "").strip().lower() != "system":
            continue

        content = message.get("content")
        if not isinstance(content, str) or "[RECENT CHAT CONTEXT]" not in content:
            continue

        clean_content, count = _RECENT_CHAT_CONTEXT_RE.subn("\n\n", content)
        if count <= 0:
            continue

        message["content"] = clean_content.strip()
        trimmed_sections.append("duplicate_recent_chat_context")


def _remove_oldest_history_message(
    messages: list[dict[str, Any]], trimmed_sections: list[str]
) -> bool:
    pinned_index = _last_message_index(messages)

    for index, message in enumerate(messages):
        if index == pinned_index:
            continue

        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue

        removed = messages.pop(index)
        removed_role = str(removed.get("role") or "message").strip().lower()
        trimmed_sections.append(f"old_chat_{removed_role or 'message'}")
        return True

    return False


def _remove_last_knowledge_excerpt(
    messages: list[dict[str, Any]], trimmed_sections: list[str]
) -> bool:
    for message in messages:
        if str(message.get("role") or "").strip().lower() != "system":
            continue

        content = message.get("content")
        if not isinstance(content, str):
            continue

        matches = list(_KNOWLEDGE_EXCERPT_RE.finditer(content))
        if not matches:
            continue

        match = matches[-1]
        excerpt_index = match.group("index")
        message["content"] = (content[: match.start()] + content[match.end() :]).strip()
        trimmed_sections.append(f"knowledge_excerpt_{excerpt_index}")
        return True

    return False


def _trim_text_to_token_budget(text: str, max_tokens: int) -> str:
    clean_text = str(text or "")

    if estimate_model_content_tokens(clean_text) <= max_tokens:
        return clean_text

    max_chars = max(0, int(max_tokens) * 4)
    marker = (
        "\n\n[Context budget trimmed the middle of oversized system/context text.]\n\n"
    )

    if max_chars <= len(marker) + 40:
        return clean_text[: max(0, max_chars)].rstrip()

    usable_chars = max_chars - len(marker)
    head_chars = max(20, int(usable_chars * 0.58))
    tail_chars = max(20, usable_chars - head_chars)

    return clean_text[:head_chars].rstrip() + marker + clean_text[-tail_chars:].lstrip()


def _trim_largest_system_message(
    messages: list[dict[str, Any]],
    *,
    target_tokens: int,
    trimmed_sections: list[str],
) -> bool:
    system_candidates: list[tuple[int, int]] = []

    for index, message in enumerate(messages):
        if str(message.get("role") or "").strip().lower() != "system":
            continue

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue

        system_candidates.append((estimate_model_content_tokens(content), index))

    if not system_candidates:
        return False

    _tokens, index = max(system_candidates)
    message = messages[index]
    content = str(message.get("content") or "")
    other_messages = [
        item for item_index, item in enumerate(messages) if item_index != index
    ]
    other_tokens = estimate_messages_context_tokens(other_messages)
    role_overhead = 4 + estimate_model_content_tokens(message.get("role") or "system")
    max_system_tokens = max(16, int(target_tokens) - other_tokens - role_overhead)
    trimmed_content = _trim_text_to_token_budget(content, max_system_tokens)

    if trimmed_content == content:
        return False

    message["content"] = trimmed_content
    trimmed_sections.append("oversized_system_context")
    return True


def enforce_context_budget(
    messages,
    *,
    context_limit=None,
    generation_budget=0,
    min_generation_budget=64,
) -> ContextBudgetResult:
    """Trim final request messages to fit an estimated model context window.

    The last message is treated as the current user request and is never removed.
    Current attachment text/image placeholders therefore stay pinned with that
    message. Older chat turns are removed before document excerpts or system
    context are shortened.
    """
    budgeted_messages: list[dict[str, Any]] = copy.deepcopy(list(messages or []))
    trimmed_sections: list[str] = []
    warnings: list[str] = []
    clean_context_limit = _positive_int(context_limit)
    clean_generation_budget = _positive_int(generation_budget) or 0
    minimum_generation_budget = max(0, int(min_generation_budget or 0))

    if not budgeted_messages:
        return ContextBudgetResult(
            messages=[],
            prompt_tokens=0,
            context_limit=clean_context_limit,
            generation_budget=clean_generation_budget,
            trimmed_sections=(),
            warnings=(),
        )

    _strip_duplicate_recent_chat_context(budgeted_messages, trimmed_sections)
    prompt_tokens = estimate_messages_context_tokens(budgeted_messages)

    if clean_context_limit is None:
        return ContextBudgetResult(
            messages=budgeted_messages,
            prompt_tokens=prompt_tokens,
            context_limit=None,
            generation_budget=clean_generation_budget,
            trimmed_sections=tuple(trimmed_sections),
            warnings=tuple(warnings),
        )

    def request_total() -> int:
        return prompt_tokens + clean_generation_budget

    while request_total() > clean_context_limit:
        if not _remove_oldest_history_message(budgeted_messages, trimmed_sections):
            break
        prompt_tokens = estimate_messages_context_tokens(budgeted_messages)

    while request_total() > clean_context_limit:
        if not _remove_last_knowledge_excerpt(budgeted_messages, trimmed_sections):
            break
        prompt_tokens = estimate_messages_context_tokens(budgeted_messages)

    if (
        request_total() > clean_context_limit
        and clean_generation_budget > minimum_generation_budget
    ):
        new_generation_budget = max(
            minimum_generation_budget,
            clean_context_limit - prompt_tokens,
        )
        if new_generation_budget < clean_generation_budget:
            clean_generation_budget = new_generation_budget
            trimmed_sections.append("generation_budget")

    if request_total() > clean_context_limit:
        target_prompt_tokens = max(
            0,
            clean_context_limit
            - max(minimum_generation_budget, clean_generation_budget),
        )
        if _trim_largest_system_message(
            budgeted_messages,
            target_tokens=target_prompt_tokens,
            trimmed_sections=trimmed_sections,
        ):
            prompt_tokens = estimate_messages_context_tokens(budgeted_messages)

    if request_total() > clean_context_limit:
        warnings.append("context_budget_exceeded_after_trimming")

    return ContextBudgetResult(
        messages=budgeted_messages,
        prompt_tokens=prompt_tokens,
        context_limit=clean_context_limit,
        generation_budget=clean_generation_budget,
        trimmed_sections=tuple(trimmed_sections),
        warnings=tuple(warnings),
    )

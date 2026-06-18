from fzastro_ai.llm import enforce_context_budget


def _text(length: int, char: str = "x") -> str:
    return char * int(length)


def test_context_budget_removes_duplicate_recent_chat_when_history_is_present():
    messages = [
        {
            "role": "system",
            "content": (
                "Core prompt.\n\n"
                "[RECENT CHAT CONTEXT]\n"
                "USER: old question\n"
                "[/RECENT CHAT CONTEXT]\n"
            ),
        },
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current question"},
    ]

    result = enforce_context_budget(
        messages, context_limit=None, generation_budget=4096
    )

    assert "[RECENT CHAT CONTEXT]" not in result.messages[0]["content"]
    assert "duplicate_recent_chat_context" in result.trimmed_sections
    assert result.context_limit is None
    assert result.generation_budget == 4096


def test_context_budget_trims_oldest_chat_before_current_user_request():
    messages = [
        {"role": "system", "content": "Core prompt."},
        {"role": "user", "content": _text(800, "u")},
        {"role": "assistant", "content": _text(800, "a")},
        {"role": "user", "content": "current request must stay"},
    ]

    result = enforce_context_budget(messages, context_limit=170, generation_budget=64)
    roles_and_content = [(item["role"], item["content"]) for item in result.messages]

    assert ("user", _text(800, "u")) not in roles_and_content
    assert result.messages[-1] == {
        "role": "user",
        "content": "current request must stay",
    }
    assert any(section.startswith("old_chat_") for section in result.trimmed_sections)
    assert result.prompt_tokens + result.generation_budget <= 170


def test_context_budget_trims_lower_ranked_knowledge_excerpt_after_history():
    messages = [
        {
            "role": "system",
            "content": (
                "Core prompt.\n"
                "[KNOWLEDGE EXCERPT 1]\n"
                "Content:\n" + _text(280, "a") + "\n[/KNOWLEDGE EXCERPT 1]\n"
                "[KNOWLEDGE EXCERPT 2]\n"
                "Content:\n" + _text(280, "b") + "\n[/KNOWLEDGE EXCERPT 2]"
            ),
        },
        {"role": "user", "content": "current request"},
    ]

    result = enforce_context_budget(messages, context_limit=170, generation_budget=64)
    system_content = result.messages[0]["content"]

    assert "[KNOWLEDGE EXCERPT 1]" in system_content
    assert "[KNOWLEDGE EXCERPT 2]" not in system_content
    assert "knowledge_excerpt_2" in result.trimmed_sections
    assert result.prompt_tokens + result.generation_budget <= 170


def test_context_budget_reduces_generation_budget_after_prompt_trimming():
    messages = [
        {"role": "system", "content": _text(340, "s")},
        {"role": "user", "content": "current request"},
    ]

    result = enforce_context_budget(messages, context_limit=200, generation_budget=160)

    assert result.generation_budget < 160
    assert result.generation_budget >= 64
    assert "generation_budget" in result.trimmed_sections
    assert result.messages[-1]["content"] == "current request"
    assert result.prompt_tokens + result.generation_budget <= 200


def test_context_budget_unknown_limit_keeps_messages_except_duplicate_recent_context():
    messages = [
        {"role": "system", "content": "Core prompt."},
        {"role": "user", "content": _text(1000, "u")},
        {"role": "user", "content": "current request"},
    ]

    result = enforce_context_budget(
        messages, context_limit=None, generation_budget=4096
    )

    assert result.messages == messages
    assert result.trimmed_sections == ()
    assert result.warnings == ()

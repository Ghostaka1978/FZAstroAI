from fzastro_ai.llm import (
    build_chat_request_plan,
    choose_chat_generation_settings,
)


def test_chat_request_plan_builds_normalized_messages_and_system_context():
    history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "old image request"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
            ],
        },
        {"role": "assistant", "content": "old answer"},
    ]

    plan = build_chat_request_plan(
        system_prompt="Core prompt.",
        history_messages=history,
        current_user_content="current question",
        allow_images=False,
        context_limit=None,
        recent_chat_context="[RECENT CHAT CONTEXT]\nUSER: old\n[/RECENT CHAT CONTEXT]",
        knowledge_context="\n\nDOCUMENT_KNOWLEDGE = AVAILABLE",
        python_auto_test_request=False,
    )

    assert plan.api_messages[0]["role"] == "system"
    assert "Core prompt." in plan.api_messages[0]["content"]
    assert "DOCUMENT_KNOWLEDGE = AVAILABLE" in plan.api_messages[0]["content"]
    assert "APPLICATION RESPONSE STYLE" in plan.api_messages[0]["content"]
    assert "Markdown links" in plan.api_messages[0]["content"]
    assert "APPLICATION PYTHON EXECUTION CONTEXT" in plan.api_messages[0]["content"]
    assert "old image request" in plan.api_messages[1]["content"]
    assert "image was attached" in plan.api_messages[1]["content"]
    assert plan.api_messages[-1] == {"role": "user", "content": "current question"}


def test_chat_generation_settings_match_existing_request_types():
    assert choose_chat_generation_settings().num_predict == 4096
    assert choose_chat_generation_settings().think_enabled is True

    news = choose_chat_generation_settings(is_news_generation=True)
    assert news.profile == "daily_news"
    assert news.num_predict == 12000
    assert news.think_enabled is False
    assert news.stream_render_interval_ms == 280

    vision = choose_chat_generation_settings(request_requires_vision=True)
    assert vision.profile == "vision"
    assert vision.num_predict == 1200
    assert vision.think_enabled is False

    exhaustive = choose_chat_generation_settings(is_exhaustive_document_request=True)
    assert exhaustive.profile == "document_exhaustive"
    assert exhaustive.num_predict == 12000
    assert exhaustive.think_enabled is False


def test_chat_request_plan_applies_context_budget_and_keeps_current_request():
    history = [
        {"role": "user", "content": "u" * 800},
        {"role": "assistant", "content": "a" * 800},
    ]

    plan = build_chat_request_plan(
        system_prompt="Core prompt.",
        history_messages=history,
        current_user_content="current request must stay",
        allow_images=True,
        context_limit=180,
        recent_chat_context=None,
        python_auto_test_request=False,
    )

    assert plan.api_messages[-1] == {
        "role": "user",
        "content": "current request must stay",
    }
    assert any(
        section.startswith("old_chat_")
        for section in plan.context_budget.trimmed_sections
    )
    assert (
        plan.context_budget.prompt_tokens + plan.generation_settings.num_predict <= 180
    )

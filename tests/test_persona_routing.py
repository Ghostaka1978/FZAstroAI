from fzastro_ai.persona_routing import (
    ASSISTANT_PERSONA_PROMPT,
    is_assistant_persona_status_query,
)


def test_assistant_persona_prompt_is_short_llm_prompt():
    assert ASSISTANT_PERSONA_PROMPT == "What is your persona ?"
    assert not is_assistant_persona_status_query(ASSISTANT_PERSONA_PROMPT)


def test_unambiguous_assistant_persona_status_queries_route_locally():
    examples = [
        "What is your current profile?",
        "what is your current persona?",
        "show FZAstro AI's current persona",
        "What is my current persona / active calibration profile?",
    ]

    for text in examples:
        assert is_assistant_persona_status_query(text), text


def test_general_persona_questions_route_to_llm():
    examples = [
        "What is your persona ?",
        "What is your persona?",
        "what is your persona",
    ]

    for text in examples:
        assert not is_assistant_persona_status_query(text), text


def test_display_calibration_questions_do_not_route_to_persona():
    examples = [
        "What is my current monitor calibration profile?",
        "What is my current ICC profile?",
        "show my DisplayCAL calibration profile",
    ]

    for text in examples:
        assert not is_assistant_persona_status_query(text), text

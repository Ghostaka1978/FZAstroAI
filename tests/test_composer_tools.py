from pathlib import Path

from fzastro_ai.composer_tools import (
    empty_fenced_code_block,
    fenced_code_block,
    normalize_code_language,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_fenced_code_block_preserves_code_body_and_sanitises_language():
    block = fenced_code_block('print("ok")\n', "Python 3!")

    assert block == '```python3\nprint("ok")\n```'


def test_empty_fenced_code_block_returns_cursor_offset_inside_block():
    block, cursor_offset = empty_fenced_code_block("py")

    assert block == "```py\n\n```"
    assert cursor_offset == len("```py\n")


def test_composer_toolbar_is_wired_into_main_window():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    widget_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "message_widgets.py").read_text(
        encoding="utf-8-sig"
    )

    assert "composerToolbar" in app_text
    assert "composer_code_button" in app_text
    assert "composer_paste_code_button" in app_text
    assert "mark_input_selection_as_code" in app_text
    assert "paste_clipboard_as_code" in app_text
    assert "def wrap_selection_as_code" in widget_text
    assert "def paste_clipboard_text_as_code" in widget_text


def test_language_normalisation_removes_spaces_and_untrusted_punctuation():
    assert normalize_code_language("  C++  ") == "c++"
    assert normalize_code_language("python; rm -rf") == "pythonrm-rf"


from fzastro_ai.composer_actions import (
    COMPOSER_ACTION_BY_ID,
    build_composer_action_prompt,
    composer_actions_by_group,
)


def test_composer_actions_registry_contains_web_document_and_python_actions():
    grouped = composer_actions_by_group()

    assert list(grouped) == ["Text", "Web", "Documents", "Python"]
    assert [action.label for action in grouped["Text"]] == [
        "Summarize",
        "Rewrite clearer",
        "Make professional",
        "Make shorter",
        "Expand with details",
        "Turn into checklist",
        "Turn into release notes",
        "Turn into documentation",
        "Extract action items",
        "Ask clarifying questions",
    ]
    assert [action.label for action in grouped["Web"]] == [
        "Read page",
        "Summarize page",
        "Screenshot page",
    ]
    assert [action.label for action in grouped["Documents"]] == [
        "List imported documents",
        "Search knowledge library",
        "Search inside document",
        "Find in documents",
        "Brief document",
        "Open as book",
        "Ask about document",
        "Show page image",
    ]
    assert [action.label for action in grouped["Python"]] == [
        "Run input as Python",
        "Run selected code",
        "Explain this code",
        "Fix this error / debug code",
        "Refactor safely",
        "Add tests",
        "Optimize",
        "Convert to patch",
        "Create commit message",
        "Explain traceback / error",
    ]


def test_composer_action_prompt_templates():
    assert (
        build_composer_action_prompt(
            "web.read_page", {"url": "https://www.nasa.gov/blogs/artemis/"}
        )
        == "Read this page: https://www.nasa.gov/blogs/artemis/"
    )
    try:
        build_composer_action_prompt("documents.list_documents")
    except ValueError as exc:
        assert "does not insert a prompt" in str(exc)
    else:
        raise AssertionError("document list should run locally, not insert a prompt")
    assert (
        build_composer_action_prompt(
            "documents.search_documents", {"query": "lunar observing"}
        )
        == "Search my documents for: lunar observing"
    )
    for direct_document_action in (
        "documents.search_inside",
        "documents.brief_document",
        "documents.open_as_book",
        "documents.show_page_image",
    ):
        try:
            build_composer_action_prompt(
                direct_document_action,
                {
                    "title": "The Moon and How to Observe It",
                    "query": "Tycho crater",
                    "page": 42,
                },
            )
        except ValueError as exc:
            assert "does not insert a prompt" in str(exc)
        else:
            raise AssertionError(f"{direct_document_action} should run locally")
    assert (
        build_composer_action_prompt(
            "documents.find_in_documents", {"query": "Tycho crater"}
        )
        == "Find this in my documents: Tycho crater"
    )


def test_composer_action_prompt_rejects_blank_required_values():
    assert "documents.show_page_image" in COMPOSER_ACTION_BY_ID

    try:
        build_composer_action_prompt("documents.search_documents", {"query": "  "})
    except ValueError as exc:
        assert "query" in str(exc)
    else:
        raise AssertionError("blank composer action input should fail")


def test_python_composer_action_prompt_templates_use_selected_code():
    assert (
        build_composer_action_prompt("python.explain_code", {"code": "print('ok')"})
        == "Explain this Python code:\n\n```python\nprint('ok')\n```"
    )
    assert (
        build_composer_action_prompt("text.to_checklist", {"text": "Test then build"})
        == "Turn this into a practical checklist with clear steps and verification points:\n\nTest then build"
    )

    try:
        build_composer_action_prompt("python.run_input")
    except ValueError as exc:
        assert "does not insert a prompt" in str(exc)
    else:
        raise AssertionError("direct composer action should not build a prompt")


def test_composer_actions_menu_is_wired_into_main_window():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "composer_actions_button" in app_text
    assert "build_composer_code_menu" in app_text
    assert "build_composer_add_menu" in app_text
    assert "build_composer_actions_menu" in app_text
    assert "build_composer_library_menu" in app_text
    assert "run_composer_action" in app_text
    assert "insert_prompt_into_composer" in app_text
    assert "composer_context_button" in app_text
    assert "build_composer_context_menu" in app_text
    assert "composer_persona_button" in app_text
    assert "build_composer_persona_menu" in app_text
    assert "run_selected_python_from_composer" in app_text
    assert "try_handle_local_composer_command" in app_text
    assert "open_knowledge_document_reader_by_reference" in app_text
    assert "run_direct_composer_action" in app_text


def test_document_brief_display_label_does_not_drive_local_inventory_router():
    web_actions_text = (
        PROJECT_ROOT / "fzastro_ai" / "actions" / "web_news_actions.py"
    ).read_text(encoding="utf-8-sig")

    assert "routing_user_text = str(text or" in web_actions_text
    assert (
        "query_requests_document_inventory(\n                routing_user_text"
        in web_actions_text
    )
    assert "build_document_knowledge_query(routing_user_text)" in web_actions_text

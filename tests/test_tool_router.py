from fzastro_ai.routing.tool_router import (
    detect_deterministic_tool_plan,
    is_explicit_python_run_request,
    parse_tool_decision,
)
from fzastro_ai.tool_manifest import TOOL_CAPABILITY_BY_ID, build_tool_capability_prompt


class DummyKnowledgeLibrary:
    @staticmethod
    def query_is_direct_page_display_request(text):
        return "page 42" in text.lower() and "image" in text.lower()

    @staticmethod
    def query_requests_document_inventory(text):
        return text.strip().lower() in {
            "list imported documents.",
            "what books do we have?",
        }


def test_tool_manifest_contains_core_capabilities():
    assert "web.read_page" in TOOL_CAPABILITY_BY_ID
    assert "documents.show_page_image" in TOOL_CAPABILITY_BY_ID
    assert "python.run_explicit" in TOOL_CAPABILITY_BY_ID
    prompt = build_tool_capability_prompt()
    assert "APP TOOL CAPABILITIES" in prompt
    assert "documents.show_page_image" in prompt


def test_detects_url_page_tools():
    plan = detect_deterministic_tool_plan(
        "Summarize this page: https://example.com/news",
        web_enabled=True,
    )
    assert plan is not None
    assert plan.action == "web_read_page"
    assert plan.tool_id == "web.read_page"

    plan = detect_deterministic_tool_plan(
        "Take screenshot of https://example.com/news",
        web_enabled=True,
    )
    assert plan is not None
    assert plan.action == "web_screenshot_page"


def test_detects_document_inventory_and_page_image():
    plan = detect_deterministic_tool_plan(
        "What books do we have?",
        knowledge_library=DummyKnowledgeLibrary(),
    )
    assert plan is not None
    assert plan.action == "documents_direct"
    assert plan.tool_id == "documents.list"

    plan = detect_deterministic_tool_plan(
        "Show page 42 of Yearbook as an image",
        knowledge_library=DummyKnowledgeLibrary(),
    )
    assert plan is not None
    assert plan.action == "documents_direct"
    assert plan.tool_id == "documents.show_page_image"


def test_detects_document_search_and_brief():
    plan = detect_deterministic_tool_plan("Find polar alignment in my documents")
    assert plan is not None
    assert plan.action == "documents_search"

    plan = detect_deterministic_tool_plan("Brief this astronomy book")
    assert plan is not None
    assert plan.action == "documents_brief"


def test_detects_selected_document_overview_as_document_brief():
    plan = detect_deterministic_tool_plan(
        "Answer using only this imported document: Yearbook_of_Astronomy_2023.pdf\n\n"
        "Question: what is this book?",
        knowledge_library=DummyKnowledgeLibrary(),
    )

    assert plan is not None
    assert plan.action == "documents_brief"


def test_detects_explicit_python_run_and_risk():
    request = "Run this Python code:\n\n```python\nprint(2 + 2)\n```"
    assert is_explicit_python_run_request(request)
    plan = detect_deterministic_tool_plan(request)
    assert plan is not None
    assert plan.action == "python_run"
    assert plan.safe_auto_run
    assert not plan.requires_confirmation

    risky = "Run this Python code:\n\n```python\nimport os\nos.remove('x')\n```"
    plan = detect_deterministic_tool_plan(risky)
    assert plan is not None
    assert plan.action == "python_run"
    assert not plan.safe_auto_run
    assert plan.requires_confirmation


def test_parse_tool_decision_allows_document_actions():
    plan = parse_tool_decision(
        '{"action":"documents_search","query":"polar alignment","confidence":0.92,"reason":"local docs"}'
    )
    assert plan.action == "documents_search"
    assert plan.tool_id == "documents.search"
    assert plan.query == "polar alignment"

    plan = parse_tool_decision(
        '{"action":"answer","query":"","confidence":0.5,"reason":"stable"}'
    )
    assert plan.action == "answer"
    assert plan.query == ""

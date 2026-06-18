from fzastro_ai.routing.chat_route import collect_chat_route_facts, decide_chat_route
from fzastro_ai.routing.tool_router import ToolPlan


def test_daily_and_forced_web_routes_are_explicit():
    daily = decide_chat_route(daily_brief=True)
    assert daily.action == "daily_brief"
    assert daily.force_search
    assert not daily.include_document_knowledge

    forced = decide_chat_route(force_web_search=True)
    assert forced.action == "forced_web_search"
    assert forced.force_search
    assert not forced.include_document_knowledge


def test_deterministic_tool_wins_before_model_router():
    plan = ToolPlan(
        action="documents_search",
        tool_id="documents.search",
        query="polar alignment",
        reason="explicit document request",
    )

    route = decide_chat_route(
        deterministic_tool_plan=plan,
        web_mode="Auto",
        local_document_direct=True,
        web_image_request=True,
    )

    assert route.action == "deterministic_tool"
    assert route.tool_plan is plan
    assert route.reason == "explicit document request"


def test_local_document_direct_beats_generic_web_image():
    route = decide_chat_route(
        web_mode="Auto",
        local_document_direct=True,
        web_image_request=True,
    )

    assert route.action == "local_document_direct"
    assert route.include_document_knowledge


def test_web_off_stays_local_before_web_image_or_model_router():
    route = decide_chat_route(web_mode="Off", web_image_request=True)

    assert route.action == "local_chat"
    assert not route.force_search
    assert not route.include_document_knowledge


def test_web_off_blocks_current_info_before_plain_llm_answer():
    route = decide_chat_route(
        web_mode="Off",
        external_information_request=True,
    )

    assert route.action == "web_disabled_current_info"
    assert not route.include_document_knowledge


def test_local_document_direct_still_works_when_web_is_off():
    route = decide_chat_route(
        web_mode="Off",
        local_document_direct=True,
        external_information_request=True,
    )

    assert route.action == "local_document_direct"
    assert route.include_document_knowledge


def test_attachments_stay_local_unless_web_is_needed():
    local = decide_chat_route(
        web_mode="Auto",
        files=["C:/tmp/example.png"],
        attachment_needs_web=False,
    )
    assert local.action == "attachment_local"
    assert not local.include_document_knowledge

    external = decide_chat_route(
        web_mode="Auto",
        files=["C:/tmp/example.png"],
        attachment_needs_web=True,
    )
    assert external.action == "model_router"


def test_recent_image_followup_uses_recent_assistant_image_only_when_available():
    unavailable = decide_chat_route(
        recent_image_followup=True,
        latest_assistant_image_available=False,
    )
    assert unavailable.action == "model_router"

    available = decide_chat_route(
        recent_image_followup=True,
        latest_assistant_image_available=True,
    )
    assert available.action == "recent_image_followup"
    assert not available.include_document_knowledge


def test_always_mode_routes_directly_to_forced_web_search():
    route = decide_chat_route(web_mode="Always")

    assert route.action == "forced_web_search"
    assert route.force_search
    assert not route.include_document_knowledge


def test_obvious_url_request_gets_deterministic_tool_plan_before_model_router():
    facts = collect_chat_route_facts(
        "Summarize this page: https://example.com/news",
        web_mode="Auto",
    )
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_mode="Auto",
        files=[],
        local_document_direct=facts.local_document_direct,
        web_image_request=facts.web_image_request,
        external_information_request=facts.external_information_request,
        recent_image_followup=facts.recent_image_followup,
        latest_assistant_image_available=facts.latest_assistant_image_available,
        attachment_needs_web=facts.attachment_needs_web,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "web_read_page"
    assert route.action == "deterministic_tool"


def test_obvious_current_info_request_skips_model_router():
    facts = collect_chat_route_facts("What is the latest Python version?")
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        external_information_request=facts.external_information_request,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "web_search"
    assert route.action == "deterministic_tool"


def test_obvious_weather_request_skips_model_router():
    facts = collect_chat_route_facts("How is the weather today in Berlin?")
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        external_information_request=facts.external_information_request,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "weather_today"
    assert facts.deterministic_tool_plan.query == "Berlin"
    assert route.action == "deterministic_tool"


def test_obvious_market_compare_skips_model_router():
    facts = collect_chat_route_facts("Compare CRM and DBX stocks in a clean table")
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        external_information_request=facts.external_information_request,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "stock_compare"
    assert facts.deterministic_tool_plan.query == "CRM DBX"
    assert route.action == "deterministic_tool"


def test_weather_location_followup_uses_recent_context_without_model_router():
    facts = collect_chat_route_facts(
        "Athens",
        recent_context="AI: Please share your city, region, or coordinates for weather.",
    )
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        external_information_request=facts.external_information_request,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "weather_today"
    assert facts.deterministic_tool_plan.query == "Athens"
    assert route.action == "deterministic_tool"


def test_obvious_web_image_request_skips_model_router():
    facts = collect_chat_route_facts("Find me an image of M31")
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_image_request=facts.web_image_request,
    )

    assert facts.deterministic_tool_plan is None
    assert facts.web_image_request
    assert route.action == "web_image"


def test_attached_local_image_does_not_become_web_search():
    facts = collect_chat_route_facts(
        "show me the image",
        files=["C:/tmp/example.png"],
        web_mode="Auto",
    )
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_mode="Auto",
        files=["C:/tmp/example.png"],
        web_image_request=facts.web_image_request,
        external_information_request=facts.external_information_request,
        attachment_needs_web=facts.attachment_needs_web,
    )

    assert facts.deterministic_tool_plan is None
    assert not facts.external_information_request
    assert route.action == "attachment_local"


def test_attached_file_with_obvious_current_info_still_skips_model_router():
    facts = collect_chat_route_facts(
        "Compare this file with the latest Python release",
        files=["C:/tmp/example.txt"],
        web_mode="Auto",
    )
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_mode="Auto",
        files=["C:/tmp/example.txt"],
        external_information_request=facts.external_information_request,
        attachment_needs_web=facts.attachment_needs_web,
    )

    assert facts.deterministic_tool_plan is not None
    assert facts.deterministic_tool_plan.action == "web_search"
    assert route.action == "deterministic_tool"


def test_ambiguous_auto_request_still_uses_model_router():
    facts = collect_chat_route_facts("What do you think about this?")
    route = decide_chat_route(
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_mode="Auto",
        external_information_request=facts.external_information_request,
        recent_image_followup=facts.recent_image_followup,
        latest_assistant_image_available=facts.latest_assistant_image_available,
    )

    assert facts.deterministic_tool_plan is None
    assert route.action == "model_router"


def test_final_answer_prompt_does_not_advertise_raw_tool_calls():
    source = open("fzastro_ai/actions/web_news_actions.py", encoding="utf-8").read()

    assert "build_tool_capability_prompt" not in source
    assert "tool_capability_context" not in source


def test_document_context_is_not_auto_enabled_by_strong_local_match():
    source = open("fzastro_ai/actions/web_news_actions.py", encoding="utf-8").read()

    assert "include_document_knowledge = False" in source
    assert "find_strong_document_knowledge(text)" not in source
    assert "strong_local_match" not in source


def test_document_inventory_dump_is_not_in_chat_send_path():
    source = open("fzastro_ai/actions/web_news_actions.py", encoding="utf-8").read()
    router = open("fzastro_ai/routing/tool_router.py", encoding="utf-8").read()
    manifest = open("fzastro_ai/tool_manifest.py", encoding="utf-8").read()

    assert "Document inventory returned directly" not in source
    assert "format_document_inventory_response()" not in source
    assert "documents.list" not in router
    assert "documents.list" not in manifest

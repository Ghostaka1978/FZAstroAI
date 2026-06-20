"""Pure chat-route decisions for the main LLM send pipeline.

This module decides *which path* a chat request should take. It deliberately
does not touch Qt widgets, workers, files, network, or model clients. The app
controller supplies the facts it already knows, then executes the returned
decision through the existing UI/worker methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .intent_detection import (
    explicitly_requests_external_information,
    has_explicit_http_url,
    is_deterministic_url_tool_request,
    is_local_document_direct_request,
    is_web_image_request,
    references_recent_image,
)
from .tool_router import ToolPlan, detect_deterministic_tool_plan

ChatRouteAction = Literal[
    "daily_brief",
    "forced_web_search",
    "persona_status",
    "python_auto_test",
    "deterministic_tool",
    "local_chat",
    "web_disabled_current_info",
    "local_document_direct",
    "web_image",
    "recent_image_followup",
    "attachment_local",
    "model_router",
]


@dataclass(frozen=True)
class ChatRouteDecision:
    """A controller-neutral route decision for one user message."""

    action: ChatRouteAction
    reason: str = ""
    tool_plan: ToolPlan | None = None
    include_document_knowledge: bool = True
    force_search: bool = False


@dataclass(frozen=True)
class ChatRouteFacts:
    """Pure facts collected before choosing a chat route."""

    deterministic_tool_plan: ToolPlan | None = None
    local_document_direct: bool = False
    web_image_request: bool = False
    external_information_request: bool = False
    recent_image_followup: bool = False
    latest_assistant_image_available: bool = False
    attachment_needs_web: bool = True


def _web_mode_text(web_mode: str | None) -> str:
    return str(web_mode or "Auto").strip()


def collect_chat_route_facts(
    text: str,
    *,
    files=None,
    knowledge_library=None,
    web_mode: str | None = "Auto",
    force_web_search: bool = False,
    latest_assistant_image_available: bool = False,
    recent_context: str = "",
    log_exception_func=None,
) -> ChatRouteFacts:
    """Collect deterministic routing facts without touching UI or workers."""

    file_list = list(files or [])
    clean_web_mode = _web_mode_text(web_mode)
    web_enabled = clean_web_mode != "Off"

    deterministic_tool_plan = detect_deterministic_tool_plan(
        text,
        files=file_list,
        knowledge_library=knowledge_library,
        web_enabled=web_enabled,
        force_web_search=force_web_search,
        recent_context=recent_context,
    )
    local_document_direct = False

    if knowledge_library is not None:
        local_document_direct = is_local_document_direct_request(
            text,
            knowledge_library,
            files=file_list,
            log_exception_func=log_exception_func,
        )

    web_image_request = is_web_image_request(text)
    has_url = has_explicit_http_url(text)
    external_information_request = explicitly_requests_external_information(text)

    if web_image_request and not has_url and not force_web_search:
        external_information_request = False

    recent_image_followup = bool(not file_list and references_recent_image(text))
    attachment_needs_web = True

    if file_list and clean_web_mode != "Always":
        attachment_needs_web = bool(
            external_information_request
            or has_url
            or is_deterministic_url_tool_request(text)
        )

    return ChatRouteFacts(
        deterministic_tool_plan=deterministic_tool_plan,
        local_document_direct=local_document_direct,
        web_image_request=web_image_request,
        external_information_request=external_information_request,
        recent_image_followup=recent_image_followup,
        latest_assistant_image_available=bool(latest_assistant_image_available),
        attachment_needs_web=attachment_needs_web,
    )


def decide_chat_route(
    *,
    daily_brief: bool = False,
    force_web_search: bool = False,
    persona_status: bool = False,
    python_auto_test: bool = False,
    deterministic_tool_plan: ToolPlan | None = None,
    web_mode: str | None = "Auto",
    files=None,
    local_document_direct: bool = False,
    web_image_request: bool = False,
    external_information_request: bool = False,
    recent_image_followup: bool = False,
    latest_assistant_image_available: bool = False,
    attachment_needs_web: bool = True,
) -> ChatRouteDecision:
    """Return the next high-level route for a prepared chat request.

    The ordering mirrors the historical send pipeline, but makes it explicit:
    fixed app commands win first, deterministic tools beat model routing,
    local document/page-image requests beat generic web-image requests, and
    attachments stay local unless the user explicitly asks for external data.
    """

    file_list = list(files or [])
    clean_web_mode = _web_mode_text(web_mode)

    if daily_brief:
        return ChatRouteDecision(
            "daily_brief",
            reason="Daily briefing button/command requested fixed news feeds.",
            include_document_knowledge=False,
            force_search=True,
        )

    if force_web_search:
        return ChatRouteDecision(
            "forced_web_search",
            reason="Caller forced a web search route.",
            include_document_knowledge=False,
            force_search=True,
        )

    if persona_status:
        return ChatRouteDecision(
            "persona_status",
            reason="User asked for the active persona/calibration status.",
            include_document_knowledge=False,
        )

    if python_auto_test:
        return ChatRouteDecision(
            "python_auto_test",
            reason="User asked the model to generate Python and test it.",
            include_document_knowledge=False,
        )

    if deterministic_tool_plan is not None:
        return ChatRouteDecision(
            "deterministic_tool",
            reason=deterministic_tool_plan.reason,
            tool_plan=deterministic_tool_plan,
            include_document_knowledge=False,
            force_search=clean_web_mode == "Always",
        )

    if local_document_direct:
        return ChatRouteDecision(
            "local_document_direct",
            reason="Request targets the local document library directly.",
            include_document_knowledge=True,
        )

    if clean_web_mode == "Off" and external_information_request:
        return ChatRouteDecision(
            "web_disabled_current_info",
            reason="Current/external information was requested while Web mode is Off.",
            include_document_knowledge=False,
        )

    if clean_web_mode == "Off":
        return ChatRouteDecision(
            "local_chat",
            reason="Web mode is Off; answer through local chat context.",
            include_document_knowledge=False,
        )

    if web_image_request and not file_list:
        return ChatRouteDecision(
            "web_image",
            reason="Request is an explicit web image retrieval.",
            include_document_knowledge=False,
            force_search=clean_web_mode == "Always",
        )

    if recent_image_followup and latest_assistant_image_available and not file_list:
        return ChatRouteDecision(
            "recent_image_followup",
            reason="Request refers to a recent assistant image.",
            include_document_knowledge=False,
        )

    if clean_web_mode == "Always":
        return ChatRouteDecision(
            "forced_web_search",
            reason="Web mode is Always; use web search without model routing.",
            include_document_knowledge=False,
            force_search=True,
        )

    if file_list and clean_web_mode != "Always" and not attachment_needs_web:
        return ChatRouteDecision(
            "attachment_local",
            reason="Attached local files can be handled without web routing.",
            include_document_knowledge=False,
        )

    return ChatRouteDecision(
        "model_router",
        reason="No deterministic route matched; use the model/web router.",
        include_document_knowledge=False,
        force_search=clean_web_mode == "Always",
    )


def decide_chat_route_from_facts(
    facts: ChatRouteFacts,
    *,
    daily_brief: bool = False,
    force_web_search: bool = False,
    persona_status: bool = False,
    python_auto_test: bool = False,
    web_mode: str | None = "Auto",
    files=None,
) -> ChatRouteDecision:
    """Choose a route from precomputed deterministic facts."""

    return decide_chat_route(
        daily_brief=daily_brief,
        force_web_search=force_web_search,
        persona_status=persona_status,
        python_auto_test=python_auto_test,
        deterministic_tool_plan=facts.deterministic_tool_plan,
        web_mode=web_mode,
        files=files,
        local_document_direct=facts.local_document_direct,
        web_image_request=facts.web_image_request,
        external_information_request=facts.external_information_request,
        recent_image_followup=facts.recent_image_followup,
        latest_assistant_image_available=facts.latest_assistant_image_available,
        attachment_needs_web=facts.attachment_needs_web,
    )


def plan_chat_route(
    text: str,
    *,
    files=None,
    knowledge_library=None,
    web_mode: str | None = "Auto",
    daily_brief: bool = False,
    force_web_search: bool = False,
    persona_status: bool = False,
    python_auto_test: bool = False,
    latest_assistant_image_available: bool = False,
    recent_context: str = "",
    log_exception_func=None,
) -> ChatRouteDecision:
    """Collect deterministic facts and return the high-level chat route."""

    facts = collect_chat_route_facts(
        text,
        files=files,
        knowledge_library=knowledge_library,
        web_mode=web_mode,
        force_web_search=force_web_search,
        latest_assistant_image_available=latest_assistant_image_available,
        recent_context=recent_context,
        log_exception_func=log_exception_func,
    )
    return decide_chat_route_from_facts(
        facts,
        daily_brief=daily_brief,
        force_web_search=force_web_search,
        persona_status=persona_status,
        python_auto_test=python_auto_test,
        web_mode=web_mode,
        files=files,
    )


__all__ = [
    "ChatRouteAction",
    "ChatRouteDecision",
    "ChatRouteFacts",
    "collect_chat_route_facts",
    "decide_chat_route",
    "decide_chat_route_from_facts",
    "plan_chat_route",
]

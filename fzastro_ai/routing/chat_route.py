"""Pure chat-route decisions for the main LLM send pipeline.

This module decides *which path* a chat request should take. It deliberately
does not touch Qt widgets, workers, files, network, or model clients. The app
controller supplies the facts it already knows, then executes the returned
decision through the existing UI/worker methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .tool_router import ToolPlan


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


def _web_mode_text(web_mode: str | None) -> str:
    return str(web_mode or "Auto").strip()


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

    if (
        recent_image_followup
        and latest_assistant_image_available
        and not file_list
    ):
        return ChatRouteDecision(
            "recent_image_followup",
            reason="Request refers to a recent assistant image.",
            include_document_knowledge=False,
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


__all__ = ["ChatRouteAction", "ChatRouteDecision", "decide_chat_route"]

"""Tool-aware deterministic routing helpers.

This module does not execute tools. It converts obvious user requests into a
small tool plan that the application can validate and execute through its
existing worker paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from .intent_detection import (
    explicitly_requests_external_information,
    has_explicit_http_url,
    is_deterministic_url_tool_request,
    is_python_execution_request,
    is_rendered_page_request,
    is_website_screenshot_request,
    references_document_knowledge,
    python_code_has_risky_auto_actions,
    extract_python_code_from_text,
    looks_like_python_code,
)

ToolAction = Literal[
    "answer",
    "web_search",
    "web_read_page",
    "web_screenshot_page",
    "documents_direct",
    "documents_search",
    "documents_brief",
    "python_run",
]


@dataclass(frozen=True)
class ToolPlan:
    action: ToolAction
    tool_id: str
    query: str = ""
    confidence: float = 1.0
    reason: str = ""
    safe_auto_run: bool = True
    requires_confirmation: bool = False


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s<>'\"]+", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]")


def is_explicit_python_run_request(text: str) -> bool:
    """Return True for non-slash natural-language execution requests."""
    clean = _normalise_text(text).casefold()

    if not clean:
        return False

    if is_python_execution_request(text):
        return True

    has_fence = bool(re.search(r"```(?:python|py)?\s*\n", str(text or ""), re.I))
    mentions_python = bool(re.search(r"\b(?:python|py)\b", clean))
    mentions_code = bool(re.search(r"\b(?:code|script|snippet|program)\b", clean))
    asks_run = bool(
        re.search(r"\b(?:run|execute|test|try|launch)\b", clean)
        or re.search(r"\buse\s+python\s+to\b", clean)
    )

    if asks_run and has_fence and (mentions_python or mentions_code):
        return True

    if asks_run and looks_like_python_code(text) and mentions_python:
        return True

    return False


def detect_deterministic_tool_plan(
    text: str,
    *,
    files=None,
    knowledge_library=None,
    web_enabled: bool = True,
    force_web_search: bool = False,
) -> ToolPlan | None:
    """Return a safe deterministic tool plan for explicit app-tool requests."""
    clean_text = str(text or "").strip()

    if not clean_text:
        return None

    file_list = list(files or [])

    if not file_list and is_explicit_python_run_request(clean_text):
        code = extract_python_code_from_text(clean_text, force=False)
        if not code and looks_like_python_code(clean_text):
            code = clean_text

        if code.strip():
            risky = python_code_has_risky_auto_actions(code)
            return ToolPlan(
                action="python_run",
                tool_id="python.run_explicit",
                query=code.strip(),
                confidence=0.96,
                reason="User explicitly asked to execute Python code.",
                safe_auto_run=not risky,
                requires_confirmation=risky,
            )

    if (
        knowledge_library is not None
        and not file_list
        and not has_explicit_http_url(clean_text)
    ):
        try:
            if knowledge_library.query_is_direct_page_display_request(clean_text):
                return ToolPlan(
                    action="documents_direct",
                    tool_id="documents.show_page_image",
                    query=clean_text,
                    confidence=0.99,
                    reason="User asked for a local PDF page image/display.",
                )

            if knowledge_library.query_requests_document_inventory(clean_text):
                return ToolPlan(
                    action="documents_direct",
                    tool_id="documents.list",
                    query=clean_text,
                    confidence=0.99,
                    reason="User asked to list imported documents.",
                )
        except Exception:
            # Caller logs local-library failures; routing must stay conservative.
            pass

    if not file_list and not has_explicit_http_url(clean_text):
        lowered = clean_text.casefold()

        if references_document_knowledge(clean_text):
            overview_question = bool(
                re.search(
                    r"\b(?:what\s+(?:is|are)|what\s+does|tell\s+me\s+about|describe|explain)\b"
                    r".*\b(?:this|that|the|selected|current)?\s*"
                    r"(?:book|manual|document|doc|pdf|file)s?\b",
                    lowered,
                )
            )

            if (
                re.search(r"\b(?:brief|summari[sz]e|overview|recap)\b", lowered)
                or overview_question
            ):
                return ToolPlan(
                    action="documents_brief",
                    tool_id="documents.brief",
                    query=clean_text,
                    confidence=0.88,
                    reason="User asked for a brief/summary from imported documents.",
                )

            if re.search(
                r"\b(?:find|search|look\s+for|where\s+does|which\s+page|specific)\b",
                lowered,
            ):
                return ToolPlan(
                    action="documents_search",
                    tool_id="documents.search",
                    query=clean_text,
                    confidence=0.84,
                    reason="User asked to find information in imported documents.",
                )

    if web_enabled and not file_list:
        if is_website_screenshot_request(clean_text):
            return ToolPlan(
                action="web_screenshot_page",
                tool_id="web.screenshot_page",
                query=clean_text,
                confidence=0.99,
                reason="User asked for a website screenshot.",
            )

        if is_rendered_page_request(clean_text):
            return ToolPlan(
                action="web_read_page",
                tool_id="web.read_page",
                query=clean_text,
                confidence=0.98,
                reason="User asked to read/extract/summarize a URL.",
            )

        if force_web_search or explicitly_requests_external_information(clean_text):
            if not references_document_knowledge(clean_text):
                return ToolPlan(
                    action="web_search",
                    tool_id="web.search",
                    query=clean_text,
                    confidence=0.86 if not force_web_search else 0.99,
                    reason="User asked for current/external web information.",
                )

    return None


def parse_tool_decision(raw_text: str) -> ToolPlan:
    """Parse a model-planner JSON response into a constrained ToolPlan."""
    import json

    if not isinstance(raw_text, str):
        raise ValueError("The tool decision response is not text.")

    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    object_start = cleaned.find("{")
    object_end = cleaned.rfind("}")

    if object_start == -1 or object_end == -1 or object_end < object_start:
        raise ValueError("The tool decision response does not contain a JSON object.")

    try:
        decision = json.loads(cleaned[object_start : object_end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"The tool decision response contains invalid JSON: {exc}"
        ) from exc

    if not isinstance(decision, dict):
        raise ValueError("The tool decision response must be a JSON object.")

    action = str(decision.get("action", "")).strip().lower()
    query = _normalise_text(decision.get("query", ""))
    reason = _normalise_text(decision.get("reason", ""))

    try:
        confidence = float(decision.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    action_to_tool = {
        "answer": "answer",
        "web_search": "web.search",
        "documents_search": "documents.search",
        "documents_brief": "documents.brief",
    }

    if action not in action_to_tool:
        raise ValueError("The tool decision action is not allowed.")

    if action == "answer":
        return ToolPlan(
            action="answer",
            tool_id="answer",
            query="",
            confidence=max(0.0, min(1.0, confidence)),
            reason=reason,
        )

    if not query:
        raise ValueError("A tool decision must include a non-empty query.")

    return ToolPlan(
        action=action,  # type: ignore[arg-type]
        tool_id=action_to_tool[action],
        query=query[:300],
        confidence=max(0.0, min(1.0, confidence)),
        reason=reason,
        safe_auto_run=True,
        requires_confirmation=False,
    )

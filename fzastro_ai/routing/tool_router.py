"""Tool-aware deterministic routing helpers.

This module does not execute tools. It converts obvious user requests into a
small tool plan that the application can validate and execute through its
existing worker paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from ..weather_tools import extract_weather_location, is_weather_request
from .intent_detection import (
    explicitly_requests_external_information,
    has_explicit_http_url,
    is_deterministic_url_tool_request,
    is_python_execution_request,
    is_rendered_page_request,
    is_web_image_request,
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
    "weather_today",
    "market_pulse",
    "stock_quote",
    "stock_compare",
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


MARKET_SYMBOL_ALIASES = {
    "crm": "CRM",
    "salesforce": "CRM",
    "dbx": "DBX",
    "dropbox": "DBX",
    "oil": "CL=F",
    "crude": "CL=F",
    "crude oil": "CL=F",
    "gold": "GC=F",
}


def _extract_market_symbols(text: str) -> list[str]:
    raw_text = str(text or "")
    lowered = raw_text.casefold()
    symbols: list[str] = []

    for ticker in ("CRM", "DBX", "CL=F", "GC=F"):
        if re.search(
            rf"(?<![A-Z0-9=^.\-]){re.escape(ticker)}(?![A-Z0-9=^.\-])",
            raw_text,
            flags=re.IGNORECASE,
        ):
            symbols.append(ticker)

    for alias, ticker in MARKET_SYMBOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered) and ticker not in symbols:
            symbols.append(ticker)

    return symbols


def _is_global_market_pulse_request(text: str) -> bool:
    lowered = str(text or "").casefold()

    if re.search(
        r"\b(?:global\s+market|market\s+pulse|markets?\s+summary|stock\s+indicators|"
        r"market\s+indicators|indices|commodities)\b",
        lowered,
    ):
        return True

    broad_assets = sum(
        1
        for pattern in (
            r"\boil\b|\bcrude\b",
            r"\bgold\b",
            r"\bs&p\b|\bsp500\b|\bs&p\s*500\b",
            r"\bnasdaq\b",
            r"\bdax\b",
            r"\bftse\b",
            r"\bnikkei\b",
            r"\bcrypto\b|\bbitcoin\b|\bbtc\b",
        )
        if re.search(pattern, lowered)
    )
    return broad_assets >= 3 and re.search(
        r"\b(?:market|markets|summary|table)\b", lowered
    )


def _market_tool_plan(clean_text: str) -> ToolPlan | None:
    lowered = clean_text.casefold()

    if re.search(r"https?://", clean_text):
        return None

    symbols = _extract_market_symbols(clean_text)
    wants_compare = bool(
        re.search(r"\b(?:compare|comparison|versus|vs\.?|against|table)\b", lowered)
    )

    if len(symbols) >= 2 and wants_compare:
        return ToolPlan(
            action="stock_compare",
            tool_id="market.compare",
            query=" ".join(symbols[:6]),
            confidence=0.94,
            reason="User asked to compare market symbols using current quote data.",
        )

    if _is_global_market_pulse_request(clean_text):
        return ToolPlan(
            action="market_pulse",
            tool_id="market.pulse",
            query="global_market_pulse",
            confidence=0.92,
            reason="User asked for a current global market summary.",
        )

    if len(symbols) == 1 and re.search(
        r"\b(?:stock|share|quote|price|market|ticker)\b", lowered
    ):
        return ToolPlan(
            action="stock_quote",
            tool_id="market.quote",
            query=symbols[0],
            confidence=0.92,
            reason="User asked for a current market quote.",
        )

    return None


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
    recent_context: str = "",
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

        except Exception:
            # Caller logs local-library failures; routing must stay conservative.
            pass

    if not file_list and not has_explicit_http_url(clean_text):
        lowered = clean_text.casefold()

        if references_document_knowledge(clean_text):
            document_followup = bool(
                re.search(
                    r"\b(?:first|second|third|fourth|fifth|last|other|another|same|"
                    r"1st|2nd|3rd|4th|5th)\s+"
                    r"(?:book|manual|document|doc|pdf|file)s?\b",
                    lowered,
                )
            )
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
                or document_followup
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

    if web_enabled and is_weather_request(clean_text, recent_context=recent_context):
        return ToolPlan(
            action="weather_today",
            tool_id="weather.today",
            query=extract_weather_location(clean_text, recent_context=recent_context),
            confidence=0.95,
            reason="User asked for current weather or today's forecast.",
        )

    if web_enabled:
        market_plan = _market_tool_plan(clean_text)

        if market_plan is not None:
            return market_plan

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

        external_information_request = explicitly_requests_external_information(
            clean_text
        )

        if (
            is_web_image_request(clean_text)
            and not has_explicit_http_url(clean_text)
            and not force_web_search
        ):
            external_information_request = False

        if force_web_search or external_information_request:
            if file_list or not references_document_knowledge(clean_text):
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

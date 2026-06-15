"""Central registry of app tools exposed to routing and UI helpers.

The registry is intentionally Qt-free so deterministic routers, workers, tests,
and composer UI builders can share the same capability descriptions without
pulling in PySide at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ToolSafety = Literal["safe", "confirm", "manual"]


@dataclass(frozen=True)
class ToolCapability:
    tool_id: str
    group: str
    label: str
    description: str
    arguments: tuple[str, ...] = ()
    safety: ToolSafety = "safe"
    auto_route: bool = True


TOOL_CAPABILITIES: tuple[ToolCapability, ...] = (
    ToolCapability(
        "web.search",
        "Web",
        "Search web",
        "Search current public web sources for recent or externally verified information.",
        ("query",),
    ),
    ToolCapability(
        "web.read_page",
        "Web",
        "Read web page",
        "Open a URL with the rendered-page extractor and summarize or answer from the page content.",
        ("url",),
    ),
    ToolCapability(
        "web.screenshot_page",
        "Web",
        "Screenshot web page",
        "Capture a rendered website screenshot and attach the image to the chat.",
        ("url",),
    ),
    ToolCapability(
        "documents.list",
        "Documents",
        "List documents",
        "List documents currently imported in the local Document Knowledge Library.",
    ),
    ToolCapability(
        "documents.search",
        "Documents",
        "Search documents",
        "Search imported local documents and answer with document-grounded context.",
        ("query",),
    ),
    ToolCapability(
        "documents.brief",
        "Documents",
        "Brief document",
        "Create a concise brief or summary of an imported document/book.",
        ("document_hint",),
    ),
    ToolCapability(
        "documents.show_page_image",
        "Documents",
        "Show page image",
        "Render one or more PDF pages from the local library as images.",
        ("document_hint", "page"),
    ),
    ToolCapability(
        "python.run_explicit",
        "Python",
        "Run explicit Python",
        "Run Python code only when the user explicitly asks the app to execute it.",
        ("code",),
        safety="confirm",
    ),
)


TOOL_CAPABILITY_BY_ID = {
    capability.tool_id: capability for capability in TOOL_CAPABILITIES
}


def build_tool_capability_prompt() -> str:
    """Return a compact capability prompt for model-facing system messages."""
    grouped: dict[str, list[ToolCapability]] = {}

    for capability in TOOL_CAPABILITIES:
        grouped.setdefault(capability.group, []).append(capability)

    lines = [
        "APP TOOL CAPABILITIES:",
        "FZAstro AI can use local app tools when the user asks for them. Do not claim you lack these tools.",
        "When a request asks for URLs, current web information, local imported documents, PDF pages, or explicit Python execution, the app router may call a tool before you answer.",
        "If the app has already supplied web/document/Python results in the conversation context, answer directly from those results.",
        "Never output raw tool-call syntax such as documents.brief(...), documents.search(...), JSON tool plans, or code blocks whose only purpose is to invoke an app tool.",
        "Available tools:",
    ]

    for group, capabilities in grouped.items():
        lines.append(f"- {group}:")
        for capability in capabilities:
            argument_text = ""
            if capability.arguments:
                argument_text = " Args: " + ", ".join(capability.arguments) + "."
            lines.append(
                f"  - {capability.tool_id}: {capability.description}{argument_text}"
            )

    lines.extend(
        [
            "Python execution safety:",
            "- Python is a real local interpreter, not a sandbox.",
            "- Run Python only when the user explicitly asks to execute code or when the app has already executed it and supplied the result.",
            "- For document/library questions, prefer document-grounded answers over memory or guesses.",
        ]
    )

    return "\n".join(lines)

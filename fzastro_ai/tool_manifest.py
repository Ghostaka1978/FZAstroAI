"""Central registry of app tools exposed to routing and UI helpers."""

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
        "Read and summarize a specific web page or URL when the user provides one.",
        ("url",),
    ),
    ToolCapability(
        "news.latest",
        "Web",
        "Latest news",
        "Fetch recent news context for a user-requested topic.",
        ("query",),
    ),
    ToolCapability(
        "market.quote",
        "Market",
        "Market quote",
        "Fetch current market quote or basic market context for a symbol.",
        ("symbol",),
    ),
    ToolCapability(
        "documents.search",
        "Documents",
        "Search documents",
        "Search imported local documents and answer with document-grounded context.",
        ("query",),
    ),
    ToolCapability(
        "documents.list",
        "Documents",
        "List documents",
        "List imported documents from the local knowledge library.",
    ),
    ToolCapability(
        "documents.show_page_image",
        "Documents",
        "Show document page image",
        "Render or open a specific imported document page as an image for visual inspection.",
        ("document_id", "page"),
    ),
    ToolCapability(
        "python.run_explicit",
        "Python",
        "Run explicit Python",
        "Run Python code only when the user explicitly asks to execute it.",
        ("code",),
        safety="confirm",
    ),
    ToolCapability(
        "astro.lookup",
        "Astro",
        "Lookup astronomy target",
        "Look up an astronomy object and return coordinates or observing context.",
        ("target",),
    ),
    ToolCapability(
        "astro.seeing",
        "Astro",
        "Check seeing planner",
        "Check cloud, moon, darkness, and imaging-window context.",
    ),
    ToolCapability(
        "astro.targets",
        "Astro",
        "Find imaging targets",
        "Find suitable astrophotography targets for a site and time window.",
    ),
    ToolCapability(
        "imaging.launch",
        "Imaging",
        "Launch imaging app",
        "Launch the bundled FZAstro Imaging/N.I.N.A. application.",
        safety="manual",
    ),
    ToolCapability(
        "imaging.plan_target",
        "Imaging",
        "Plan imaging target",
        "Create a safe imaging plan for a target using astronomy lookup and seeing planner context.",
        ("target", "exposure_seconds", "gain"),
        safety="confirm",
    ),
    ToolCapability(
        "imaging.plan_next_target",
        "Imaging",
        "Plan next best imaging target",
        "Use SEEING and TARGETS to choose the next safe target window and create a review-only FZAstro Imaging/N.I.N.A. plan.",
        ("exposure_seconds", "gain"),
        safety="confirm",
    ),
    ToolCapability(
        "imaging.export_nina_review_plan",
        "Imaging",
        "Export N.I.N.A. review plan",
        "Export a review-only plan file for FZAstro Imaging/N.I.N.A. without moving hardware or starting capture.",
        ("plan_id",),
        safety="confirm",
    ),
    ToolCapability(
        "imaging.export_sequence",
        "Imaging",
        "Export imaging sequence",
        "Export a planned imaging sequence for review in the bundled imaging app.",
        ("plan_id",),
        safety="confirm",
    ),
)


TOOL_CAPABILITY_BY_ID: dict[str, ToolCapability] = {
    capability.tool_id: capability for capability in TOOL_CAPABILITIES
}


def build_tool_capability_prompt() -> str:
    lines = [
        "APP TOOL CAPABILITIES:",
        "FZAstro AI can use local app tools when the user asks for them.",
        "Do not output raw tool-call syntax.",
        "Use tools only when they match the user's request.",
        "Available tools:",
    ]

    for capability in TOOL_CAPABILITIES:
        args = ""
        if capability.arguments:
            args = " Args: " + ", ".join(capability.arguments) + "."
        safety = f" Safety: {capability.safety}."
        lines.append(f"- {capability.tool_id}: {capability.description}{args}{safety}")

    return "\n".join(lines)


__all__ = [
    "ToolCapability",
    "ToolSafety",
    "TOOL_CAPABILITIES",
    "TOOL_CAPABILITY_BY_ID",
    "build_tool_capability_prompt",
]

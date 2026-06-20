from __future__ import annotations

import json
from typing import Any

from .types import ToolName, ToolRequest, ToolResult


class ToolProtocolError(ValueError):
    """Raised when a model emits malformed Developer Agent JSON."""


def _extract_first_json_object(text: str) -> str:
    """Extract the first balanced JSON object from model text.

    Local coding models often wrap JSON in prose or fenced blocks. This helper
    keeps the protocol tolerant while still validating the parsed object later.
    """

    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    start = raw.find("{")
    if start < 0:
        raise ToolProtocolError("No JSON object found in model response")

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(raw[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]

    raise ToolProtocolError("Unbalanced JSON object in model response")


def parse_tool_request(payload: str | dict[str, Any]) -> ToolRequest:
    """Parse and validate a single structured tool request."""

    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ToolProtocolError(f"Invalid JSON tool request: {exc}") from exc
    else:
        data = dict(payload)

    tool_value = data.get("tool")
    args = data.get("args", {})
    reason = str(data.get("reason", ""))
    if not isinstance(args, dict):
        raise ToolProtocolError("Tool request args must be an object")
    try:
        tool = ToolName(tool_value)
    except Exception as exc:
        raise ToolProtocolError(f"Unsupported tool: {tool_value!r}") from exc
    return ToolRequest(tool=tool, args=args, reason=reason)


def parse_tool_request_from_response(text: str) -> ToolRequest:
    """Parse a tool request even when the model wraps JSON in prose."""

    return parse_tool_request(_extract_first_json_object(text))


def tool_result_to_json(result: ToolResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "tool": result.tool.value,
            "message": result.message,
            "data": result.data,
            "requires_approval": result.requires_approval,
        },
        indent=2,
        sort_keys=True,
    )

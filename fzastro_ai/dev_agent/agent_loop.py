from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .action_executor import DevAgentToolExecutor
from .dev_session import DevAgentSession
from .tool_protocol import (
    ToolProtocolError,
    parse_tool_request_from_response,
    tool_result_to_json,
)
from .types import (
    AgentMode,
    PatchProposal,
    SafetyMode,
    ToolName,
    ToolRequest,
    ToolResult,
)


class AgentChatClient(Protocol):
    def chat(self, messages: list[dict[str, str]], *, format_json: bool = False): ...


class AgentLoopCancelled(RuntimeError):
    """Raised when the visible Developer Agent run is stopped by the user."""


@dataclass(frozen=True)
class AgentLoopEvent:
    kind: str
    message: str
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentLoopResult:
    ok: bool
    task: str
    final_text: str
    events: tuple[AgentLoopEvent, ...]
    tool_results: tuple[ToolResult, ...]
    patch_proposal: PatchProposal | None = None
    prompt_package: str = ""
    system_prompt: str = ""
    messages: tuple[dict[str, str], ...] = ()


PATCH_FAST_CONTEXT_MAX_CHARS = 32_000
PATCH_PREFLIGHT_FILE_MAX_CHARS = 10_000
PATCH_PREFLIGHT_MAX_IMPL_FILES = 2
PATCH_PREFLIGHT_MAX_TEST_FILES = 2


REVIEW_AUDIT_COVERAGE_AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "entry/app integration",
        ("main.py", "fzastro_ai/app.py"),
    ),
    (
        "runtime/model integration",
        (
            "fzastro_ai/runtime.py",
            "fzastro_ai/model_controls.py",
            "fzastro_ai/model_discovery_worker.py",
            "fzastro_ai/llm/request_builder.py",
        ),
    ),
    (
        "shutdown/worker lifecycle",
        (
            "fzastro_ai/controllers/shutdown_controller.py",
            "fzastro_ai/shutdown_controller.py",
            "fzastro_ai/workers/chat_worker.py",
            "fzastro_ai/chat_worker.py",
        ),
    ),
    (
        "developer-agent safety",
        (
            "fzastro_ai/dev_agent/safety.py",
            "fzastro_ai/dev_agent/action_executor.py",
            "fzastro_ai/dev_agent/agent_loop.py",
            "fzastro_ai/dev_agent/patch_applier.py",
            "fzastro_ai/dev_agent/test_runner.py",
        ),
    ),
    (
        "web companion boundary",
        (
            "fzastro_ai/web_companion/launcher.py",
            "fzastro_ai/web_companion/server.py",
        ),
    ),
    (
        "nina/hardware boundary",
        (
            "fzastro_ai/nina/nina_bridge.py",
            "fzastro_ai/actions/nina_actions.py",
            "fzastro_ai/ui/nina_control_dialog.py",
        ),
    ),
    (
        "astro planning/data",
        (
            "fzastro_ai/astro_tools/seeing_data.py",
            "fzastro_ai/astro_tools/target_planner.py",
            "fzastro_ai/nina/imaging_plan.py",
        ),
    ),
    (
        "state/data persistence",
        (
            "fzastro_ai/controllers/app_state_controller.py",
            "fzastro_ai/history_store.py",
            "fzastro_ai/memory_store.py",
            "fzastro_ai/json_store.py",
            "fzastro_ai/knowledge_library.py",
        ),
    ),
    (
        "command/tool execution",
        (
            "fzastro_ai/command_router.py",
            "fzastro_ai/tool_manifest.py",
            "fzastro_ai/python_execution_worker.py",
            "fzastro_ai/workers/python_execution_worker.py",
        ),
    ),
)


TOOL_RESULT_CONTINUE_INSTRUCTION = """
Continue from this tool result. If the result is enough to answer the user's latest request, return final markdown now. Do not end the turn with only tool progress. If more evidence is necessary, output exactly one more JSON tool action and no prose. In final markdown, cite the inspected file paths and clearly say what remains unverified.
""".strip()

TOOL_LIMIT_FINAL_INSTRUCTION = """
You have reached the Developer Agent tool-step limit for this turn. Do not request another tool. Produce the best evidence-backed final markdown answer using the tool results already available. Clearly list inspected files, conclusions, and anything unverified.
""".strip()

INVALID_TOOL_RECOVERY_INSTRUCTION = """
The previous tool request was invalid or blocked. Do not repeat the same invalid tool request. If you can recover, request exactly one valid tool with complete arguments. If not, return final markdown explaining what blocked the turn, what evidence is already available, and what specific user input is needed next.
""".strip()

AGENT_ACTION_SCHEMA = """
Return either exactly one JSON tool action or final markdown.

Tool action format; when using a tool, output ONLY this JSON object and no prose:
{
  "tool": "list_files | search_text | read_file | read_file_range | show_symbol | propose_patch | apply_patch | run_tests | run_command_safe | read_test_output | summarize_changes",
  "args": { ... },
  "reason": "short reason for the tool call"
}

Patch proposal args:
{
  "unified_diff": "--- a/path\n+++ b/path\n@@ ...",
  "reason": "specific reason",
  "risk_level": "low | medium | high",
  "suggested_tests": ["Compile Only", "Feature Tests"]
}

Rules:
- Do not reveal hidden chain-of-thought, private reasoning, or tool-selection narration.
- Use inspection tools before propose_patch.
- Do not call apply_patch unless the UI explicitly asks for approved apply.
- Prefer final markdown once you have enough inspected evidence to state a plan.
- In final markdown, summarize evidence and uncertainty; do not include raw tool JSON.
- If you need more direction from the user, ask one clear question in final markdown.
- Never call search_text with an empty query and never call show_symbol with an empty symbol.
- For patch tasks, inspect at least one implementation file containing the target behavior and at least one related test file when available before proposing a patch. Use task terms, search evidence, imports, and nearest test names to choose files; do not rely on domain-specific hardcoded file lists.
- When the user replies, continue from the prior conversation and do not repeat the whole analysis unless needed.
- Never claim validation passed unless a run_tests/read_test_output result proves it.
""".strip()


def build_initial_agent_messages(
    session_result, *, request: str, steering: str | None = None
) -> list[dict[str, str]]:
    system = session_result.system_prompt + "\n\n" + AGENT_ACTION_SCHEMA
    steering_block = ""
    if steering and str(steering).strip():
        steering_block = (
            "User steering/guidance for visible reasoning direction:\n"
            + str(steering).strip()
            + "\n\n"
        )
    user = (
        "User task:\n"
        f"{request}\n\n"
        f"{steering_block}"
        "Context package selected by the app; broad audit tasks include a full Python file index and focused deep-read excerpts:\n"
        f"{session_result.context.prompt_package}\n\n"
        "Start with exactly one useful inspection tool action, or return concise final markdown if the provided excerpts are enough. "
        "If you use a tool, output only the JSON tool action."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class DevAgentLoop:
    """Controlled local LLM loop for inspect -> plan -> patch proposal.

    This loop intentionally previews patch proposals only. Applying patches and
    running unsafe commands remain UI-gated unless explicit approval is supplied
    by a caller that already obtained user consent.
    """

    def __init__(
        self,
        project_root,
        chat_client: AgentChatClient,
        *,
        mode: AgentMode | str = AgentMode.PATCH_FILES,
        safety_mode: SafetyMode | str = SafetyMode.ASK_BEFORE_EDITING,
        max_steps: int = 8,
    ):
        self.project_root = project_root
        self.chat_client = chat_client
        self.mode = AgentMode(mode)
        self.safety_mode = SafetyMode(safety_mode)
        self.max_steps = max(1, int(max_steps))

    def _append_event(
        self,
        events: list[AgentLoopEvent],
        event: AgentLoopEvent,
        event_callback: Callable[[AgentLoopEvent], None] | None,
    ) -> None:
        events.append(event)
        if event_callback is not None:
            event_callback(event)

    def _is_review_project_audit(self, prepared) -> bool:
        task = getattr(prepared, "task", None)
        return (
            self.mode == AgentMode.REVIEW_ONLY
            and getattr(task, "scope", "") == "project_audit"
        )

    def _audit_coverage_paths(self) -> tuple[tuple[str, str | None], ...]:
        """Choose one existing file for each broad-review coverage area."""

        from pathlib import Path

        root = Path(self.project_root)
        selected: list[tuple[str, str | None]] = []
        for area, candidates in REVIEW_AUDIT_COVERAGE_AREAS:
            match: str | None = None
            for candidate in candidates:
                try:
                    if (root / candidate).is_file():
                        match = candidate
                        break
                except OSError:
                    continue
            selected.append((area, match))
        return tuple(selected)

    def _is_patch_generation_task(self, prepared) -> bool:
        task = getattr(prepared, "task", None)
        return (
            self.mode
            in {
                AgentMode.PATCH_FILES,
                AgentMode.PATCH_RUN_TESTS,
                AgentMode.FULL_LOOP,
            }
            and getattr(task, "mode", "") == "patch"
        )

    @staticmethod
    def _patch_preflight_paths(
        prepared, *, max_impl: int = 2, max_tests: int = 2
    ) -> tuple[str, ...]:
        """Choose implementation/test files to read before patch generation.

        This is generic patch-readiness evidence. It uses the context builder's
        evidence ranking and source/test pairing, not domain-specific filenames.
        """

        files = list(getattr(getattr(prepared, "context", None), "files", ()) or ())
        implementation: list[str] = []
        tests: list[str] = []
        support: list[str] = []
        for item in files:
            path = str(getattr(item, "path", "") or "")
            role = str(getattr(item, "role", "") or "")
            if not path:
                continue
            if role == "test":
                tests.append(path)
            elif path.endswith(
                (
                    ".py",
                    ".ps1",
                    ".json",
                    ".toml",
                    ".yaml",
                    ".yml",
                    ".ini",
                    ".cfg",
                    ".spec",
                )
            ):
                if role in {"docs"}:
                    support.append(path)
                else:
                    implementation.append(path)
            elif path.endswith((".md", ".txt")):
                support.append(path)
        chosen = implementation[:max_impl] + tests[:max_tests]
        if len(chosen) < max_impl + max_tests:
            for path in support:
                if path not in chosen:
                    chosen.append(path)
                if len(chosen) >= max_impl + max_tests:
                    break
        return tuple(dict.fromkeys(chosen))

    @staticmethod
    def _patch_preflight_instruction(paths: Sequence[str]) -> str:
        lines = [
            "Patch-readiness evidence has been preloaded by safe inspection tools.",
            "Use the inspected implementation/test evidence before proposing changes.",
            "If the evidence is sufficient, return exactly one `propose_patch` JSON action with a unified diff and no prose.",
            "If evidence is insufficient, request exactly one more valid inspection tool with complete arguments.",
            "Do not apply the patch; the UI approval step handles application.",
            "Preloaded files:",
            *(f"- `{path}`" for path in paths),
        ]
        return "\n".join(lines)

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        clean = str(text or "")
        if len(clean) <= max_chars:
            return clean
        head = max_chars // 2
        tail = max_chars - head
        return (
            clean[:head].rstrip()
            + "\n\n# ... trimmed for fast patch generation ...\n\n"
            + clean[-tail:].lstrip()
        )

    def _build_fast_patch_messages(
        self,
        *,
        prepared,
        request: str,
        preloaded_results: Sequence[ToolResult],
        paths: Sequence[str],
    ) -> tuple[list[dict[str, str]], int]:
        """Build a compact post-inspection prompt for fast PatchProposal generation."""

        system = prepared.system_prompt + "\n\n" + AGENT_ACTION_SCHEMA
        sections = [
            "Patch-readiness evidence has been preloaded by safe inspection tools.",
            "Generate the patch from the inspected evidence below.",
            "Return exactly one `propose_patch` JSON action and no prose if the change is clear.",
            "Request at most one more read/search tool only if the inspected evidence is genuinely insufficient.",
            "Do not apply the patch; the UI approval step handles application.",
            "",
            "## User task",
            str(request or "").strip(),
            "",
            "## Context sanity",
            f"- Mode: {getattr(getattr(prepared, 'task', None), 'mode', 'patch')}",
            f"- Preloaded files: {len(paths)}",
            f"- Context cap: {PATCH_FAST_CONTEXT_MAX_CHARS} chars",
            "- Backup/cache/generated files are not valid patch targets unless explicitly requested.",
        ]
        used = len("\n".join(sections))
        for result in preloaded_results:
            if result.tool != ToolName.READ_FILE or not result.ok:
                continue
            data = result.data or {}
            if not isinstance(data, dict):
                continue
            path = str(data.get("path") or "").strip()
            text = str(data.get("text") or "")
            if not path or path not in paths:
                continue
            remaining = PATCH_FAST_CONTEXT_MAX_CHARS - used - 240
            if remaining <= 1200:
                break
            excerpt = self._truncate_text(
                text, min(PATCH_PREFLIGHT_FILE_MAX_CHARS, remaining)
            )
            block = f"\n\n## Inspected file: {path}\n```\n{excerpt}\n```"
            sections.append(block)
            used += len(block)
        sections.append(
            "\n\n## Required output\n"
            "Return exactly one JSON tool action using `propose_patch` with a unified diff, "
            "risk level, reason, and suggested validation commands."
        )
        user = "\n".join(sections).strip()
        return (
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            len(user),
        )

    def _preload_patch_evidence(
        self,
        *,
        prepared,
        executor: DevAgentToolExecutor,
        messages: list[dict[str, str]],
        events: list[AgentLoopEvent],
        tool_results: list[ToolResult],
        event_callback: Callable[[AgentLoopEvent], None] | None,
        stream_callback: Callable[[str], None] | None,
        stop_requested: Callable[[], bool] | None,
    ) -> None:
        """Read ranked implementation/test files before asking for a patch.

        The objective is Codex-like behavior without domain-specific routes:
        inspect evidence first, then let the model generate a PatchProposal.
        """

        def _check_stop() -> None:
            if stop_requested is not None and stop_requested():
                raise AgentLoopCancelled("Developer Agent run stopped by user.")

        paths = self._patch_preflight_paths(
            prepared,
            max_impl=PATCH_PREFLIGHT_MAX_IMPL_FILES,
            max_tests=PATCH_PREFLIGHT_MAX_TEST_FILES,
        )
        if not paths:
            return
        self._append_event(
            events,
            AgentLoopEvent(
                "patch_preflight",
                f"Patch evidence preload: reading {len(paths)} ranked file(s) before patch generation.",
                {"paths": list(paths)},
            ),
            event_callback,
        )
        self._emit_visible_text(
            "\n\n> Patch evidence preload: reading implementation/test files before asking the model for a diff.\n",
            stream_callback,
        )
        for path in paths:
            _check_stop()
            request_action = ToolRequest(
                tool=ToolName.READ_FILE,
                args={"path": path, "max_chars": PATCH_PREFLIGHT_FILE_MAX_CHARS},
                reason="Patch evidence preload from ranked context.",
            )
            result = executor.execute(request_action, approved=False)
            tool_results.append(result)
            self._append_event(
                events,
                AgentLoopEvent(
                    "tool_result",
                    f"Patch evidence `{path}`: {result.message}",
                    {"ok": result.ok, "path": path, "preload": True},
                ),
                event_callback,
            )
            self._emit_visible_text(self._tool_progress_text(result), stream_callback)
            messages.append(
                {
                    "role": "assistant",
                    "content": self._tool_request_message(request_action),
                }
            )
            self._append_tool_result_message(messages, result)
        compact_messages, context_chars = self._build_fast_patch_messages(
            prepared=prepared,
            request=getattr(getattr(prepared, "task", None), "request", ""),
            preloaded_results=tool_results,
            paths=paths,
        )
        messages[:] = compact_messages
        self._append_event(
            events,
            AgentLoopEvent(
                "context_sanity",
                (
                    "Fast patch context prepared: "
                    f"{len(paths)} file(s), about {context_chars:,} chars before model generation."
                ),
                {"read_files": list(paths), "context_chars": context_chars},
            ),
            event_callback,
        )
        self._append_event(
            events,
            AgentLoopEvent(
                "patch_preflight",
                "Patch evidence preload complete; asking active model for compact PatchProposal generation.",
                {"read_files": list(paths), "context_chars": context_chars},
            ),
            event_callback,
        )

    @staticmethod
    def _audit_coverage_instruction(coverage: Sequence[tuple[str, str | None]]) -> str:
        verified = [f"- {area}: `{path}`" for area, path in coverage if path]
        missing = [
            f"- {area}: no matching file found in this project"
            for area, path in coverage
            if not path
        ]
        lines = [
            "Codex-style review audit coverage has been preloaded by safe read-only tools.",
            "You are still in Review Only / Read-only mode: inspection is allowed; editing, validation runs, and dangerous commands are not allowed unless the UI mode changes.",
            "When producing the final report:",
            "- Separate evidence-backed findings from unverified areas.",
            "- Name the files actually inspected.",
            "- Do not claim full-project proof beyond indexed files and tool-read contents.",
            "- For broad risk reviews, include risks, severity, evidence, and recommended next inspections or patches.",
            "",
            "Preloaded coverage:",
            *(verified or ["- none"]),
        ]
        if missing:
            lines.extend(["", "Unverified coverage areas:", *missing])
        return "\n".join(lines)

    def _preload_review_audit_coverage(
        self,
        *,
        executor: DevAgentToolExecutor,
        messages: list[dict[str, str]],
        events: list[AgentLoopEvent],
        tool_results: list[ToolResult],
        event_callback: Callable[[AgentLoopEvent], None] | None,
        stream_callback: Callable[[str], None] | None,
        stop_requested: Callable[[], bool] | None,
    ) -> None:
        """Read representative files before the first model answer for broad reviews.

        Review Only is not a passive summary mode. It may perform safe read-only
        inspection, just like Codex, while still blocking edits, validation runs,
        and dangerous commands. This preload prevents a broad request such as
        "deep analyse my app for risks" from stopping after only one narrow area.
        """

        def _check_stop() -> None:
            if stop_requested is not None and stop_requested():
                raise AgentLoopCancelled("Developer Agent run stopped by user.")

        coverage = self._audit_coverage_paths()
        self._append_event(
            events,
            AgentLoopEvent(
                "audit_coverage",
                "Review-only project audit: preloading representative files before final analysis.",
                {"areas": [area for area, _path in coverage]},
            ),
            event_callback,
        )
        self._emit_visible_text(
            "\n\n> Review-only audit preload: reading representative files across the app before asking the model for a final report.\n",
            stream_callback,
        )
        for area, path in coverage:
            _check_stop()
            if not path:
                self._append_event(
                    events,
                    AgentLoopEvent(
                        "audit_coverage",
                        f"Coverage area `{area}` has no matching file in this project.",
                        {"area": area, "path": None},
                    ),
                    event_callback,
                )
                continue
            request_action = ToolRequest(
                tool=ToolName.READ_FILE,
                args={"path": path, "max_chars": 18000},
                reason=f"Review-only project audit coverage: {area}.",
            )
            result = executor.execute(request_action, approved=False)
            tool_results.append(result)
            self._append_event(
                events,
                AgentLoopEvent(
                    "tool_result",
                    f"Audit coverage `{area}`: {result.message}",
                    {"ok": result.ok, "area": area, "path": path, "preload": True},
                ),
                event_callback,
            )
            self._emit_visible_text(self._tool_progress_text(result), stream_callback)
            messages.append(
                {
                    "role": "assistant",
                    "content": self._tool_request_message(request_action),
                }
            )
            self._append_tool_result_message(messages, result)
        messages.append(
            {
                "role": "user",
                "content": self._audit_coverage_instruction(coverage),
            }
        )
        self._append_event(
            events,
            AgentLoopEvent(
                "audit_coverage",
                "Review-only project audit preload complete; asking active model for evidence-backed analysis.",
                {"read_files": [path for _area, path in coverage if path]},
            ),
            event_callback,
        )

    def _model_text(
        self,
        messages: list[dict[str, str]],
        *,
        prefer_stream_transport: bool = True,
        stop_requested: Callable[[], bool] | None = None,
    ) -> str:
        """Return a complete model message without immediately exposing it.

        The loop must first determine whether the model emitted a tool request.
        If raw streaming were sent directly to the UI, users would see hidden
        tool JSON and tool-selection narration before the app can execute it.
        Running this in the worker thread still keeps the Qt UI responsive.
        """

        def _check_stop() -> None:
            if stop_requested is not None and stop_requested():
                raise AgentLoopCancelled("Developer Agent run stopped by user.")

        _check_stop()
        stream_chat = getattr(self.chat_client, "stream_chat", None)
        if prefer_stream_transport and callable(stream_chat):
            parts: list[str] = []
            for delta in stream_chat(messages, format_json=False):
                _check_stop()
                if delta:
                    parts.append(str(delta))
            _check_stop()
            return "".join(parts).strip()

        response = self.chat_client.chat(messages, format_json=False)
        _check_stop()
        return str(getattr(response, "text", response) or "").strip()

    @staticmethod
    def _tool_request_message(request_action: ToolRequest) -> str:
        return json.dumps(
            {
                "tool": request_action.tool.value,
                "args": request_action.args,
                "reason": request_action.reason,
            },
            indent=2,
            sort_keys=True,
        )

    @staticmethod
    def _tool_progress_text(result: ToolResult) -> str:
        detail = ""
        data = result.data or {}
        if isinstance(data, dict):
            path = data.get("path")
            if path:
                detail = f" `{path}`"
            elif data.get("files") is not None:
                detail = f" ({len(data.get('files') or [])} files)"
            elif data.get("matches") is not None:
                detail = f" ({len(data.get('matches') or [])} matches)"
            elif data.get("symbols") is not None:
                detail = f" ({len(data.get('symbols') or [])} symbols)"
        status = "ok" if result.ok else "blocked"
        return f"\n\n> Tool `{result.tool.value}`{detail}: {status}. {result.message}\n"

    @staticmethod
    def _clean_visible_final_text(text: str) -> str:
        """Remove common local-model scratchpad/tool fragments from visible chat."""
        raw = str(text or "").strip()
        if not raw:
            return ""
        lines = raw.splitlines()
        cleaned: list[str] = []
        skip_prefixes = (
            "the user wants",
            "i need to",
            "i should",
            "since the user",
            "we need to",
            "let's start",
            "let's read",
        )
        for line in lines:
            stripped = line.strip()
            lower = stripped.casefold()
            if not cleaned and any(
                lower.startswith(prefix) for prefix in skip_prefixes
            ):
                continue
            if '"tool"' in stripped and '"args"' in stripped:
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip() or raw

    @staticmethod
    def _emit_visible_text(text: str, callback: Callable[[str], None] | None) -> None:
        if callback is None or not text:
            return
        # Emit by line so the UI can render progress without showing hidden
        # tool calls. The model transport may still stream internally.
        for line in text.splitlines(keepends=True):
            callback(line)

    def _append_tool_result_message(
        self,
        messages: list[dict[str, str]],
        result: ToolResult,
        *,
        force_final: bool = False,
        invalid_recovery: bool = False,
    ) -> None:
        if force_final:
            instruction = TOOL_LIMIT_FINAL_INSTRUCTION
        elif invalid_recovery:
            instruction = INVALID_TOOL_RECOVERY_INSTRUCTION
        else:
            instruction = TOOL_RESULT_CONTINUE_INSTRUCTION
        messages.append(
            {
                "role": "user",
                "content": "Tool result JSON:\n"
                + tool_result_to_json(result)
                + "\n\n"
                + instruction,
            }
        )

    @staticmethod
    def _is_invalid_tool_result(result: ToolResult) -> bool:
        if result.ok:
            return False
        message = str(result.message or "").casefold()
        return any(
            marker in message
            for marker in (
                "search query is empty",
                "symbol name is empty",
                "file not found:",
                "invalid line range",
            )
        )

    @staticmethod
    def _deterministic_invalid_tool_final(result: ToolResult) -> str | None:
        """Return an immediate user-facing final for non-recoverable bad tool args.

        Empty search/symbol requests are model mistakes. Asking the model to
        recover can produce another empty request and make the UI appear stuck,
        so stop deterministically with actionable guidance.
        """

        message = str(result.message or "")
        lower = message.casefold()
        if "search query is empty" in lower:
            return (
                "The agent tried to run `search_text` without a query, so I stopped this turn before it could loop. "
                "Retry with a specific file or phrase, for example: `inspect fzastro_ai/web_companion/launcher.py and propose a patch for the LAN token fallback`."
            )
        if "symbol name is empty" in lower:
            return (
                "The agent tried to run `show_symbol` without a symbol name, so I stopped this turn before it could loop. "
                "Retry with a concrete symbol or ask it to read a specific file first."
            )
        return None

    def _force_final_after_invalid_tool(
        self,
        messages: list[dict[str, str]],
        *,
        stream_callback: Callable[[str], None] | None,
        stop_requested: Callable[[], bool] | None,
    ) -> str:
        text = self._model_text(
            messages,
            prefer_stream_transport=True,
            stop_requested=stop_requested,
        )
        if not text:
            final = (
                "The previous tool request was invalid and the active model returned no recovery answer. "
                "Use a more specific request or name the file/symbol/query to inspect."
            )
            self._emit_visible_text(final, stream_callback)
            return final
        try:
            parse_tool_request_from_response(text)
        except ToolProtocolError:
            cleaned = self._clean_visible_final_text(text)
        else:
            cleaned = (
                "The active model tried to continue with another tool request after an invalid tool call. "
                "I stopped the turn to avoid an empty-query loop. Please retry with a more specific instruction, "
                "for example: `read fzastro_ai/web_companion/launcher.py and propose a patch`."
            )
        self._emit_visible_text(cleaned, stream_callback)
        return cleaned

    def _force_final_after_tool_limit(
        self,
        messages: list[dict[str, str]],
        *,
        stream_callback: Callable[[str], None] | None,
        stop_requested: Callable[[], bool] | None,
    ) -> str:
        text = self._model_text(
            messages,
            prefer_stream_transport=True,
            stop_requested=stop_requested,
        )
        if not text:
            return (
                "Tool inspection completed, but the active model returned an empty final response. "
                "Review the tool progress above and ask a narrower follow-up, or click Stop Agent and retry."
            )
        try:
            # At the hard tool limit, do not execute another tool request.
            parse_tool_request_from_response(text)
        except ToolProtocolError:
            cleaned = self._clean_visible_final_text(text)
        else:
            cleaned = (
                "Tool inspection completed, but the active model requested another tool after the configured step limit. "
                "Ask a narrower follow-up or increase the agent step budget in a later build. "
                "The inspected evidence is shown above."
            )
        self._emit_visible_text(cleaned, stream_callback)
        return cleaned

    def run(
        self,
        request: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        event_callback: Callable[[AgentLoopEvent], None] | None = None,
        conversation_messages: Sequence[dict[str, str]] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        steering: str | None = None,
        steering_note_callback: Callable[[], Sequence[str]] | None = None,
    ) -> AgentLoopResult:
        session = DevAgentSession(
            self.project_root,
            mode=self.mode,
            safety_mode=self.safety_mode,
        )
        prepared = session.prepare(request)
        executor = DevAgentToolExecutor(
            self.project_root,
            mode=self.mode,
            safety_mode=self.safety_mode,
        )
        if conversation_messages:
            messages = [dict(message) for message in conversation_messages]
            context_message = "Prepared context package for follow-up."
        else:
            messages = build_initial_agent_messages(
                prepared, request=request, steering=steering
            )
            context_message = "Prepared context package."
        events: list[AgentLoopEvent] = []
        self._append_event(
            events,
            AgentLoopEvent(
                "context", context_message, {"summary": prepared.context.summary}
            ),
            event_callback,
        )
        tool_results: list[ToolResult] = []
        final_text = ""

        try:
            if not conversation_messages and self._is_review_project_audit(prepared):
                self._preload_review_audit_coverage(
                    executor=executor,
                    messages=messages,
                    events=events,
                    tool_results=tool_results,
                    event_callback=event_callback,
                    stream_callback=stream_callback,
                    stop_requested=stop_requested,
                )
            elif not conversation_messages and self._is_patch_generation_task(prepared):
                self._preload_patch_evidence(
                    prepared=prepared,
                    executor=executor,
                    messages=messages,
                    events=events,
                    tool_results=tool_results,
                    event_callback=event_callback,
                    stream_callback=stream_callback,
                    stop_requested=stop_requested,
                )
        except AgentLoopCancelled as exc:
            final_text = str(exc)
            self._emit_visible_text("\n\n> " + final_text + "\n", stream_callback)
            messages.append({"role": "assistant", "content": final_text})
            self._append_event(
                events, AgentLoopEvent("stop", final_text), event_callback
            )
            return AgentLoopResult(
                False,
                request,
                final_text,
                tuple(events),
                tuple(tool_results),
                patch_proposal=None,
                prompt_package=prepared.context.prompt_package,
                system_prompt=prepared.system_prompt,
                messages=tuple(messages),
            )

        def _check_stop() -> None:
            if stop_requested is not None and stop_requested():
                raise AgentLoopCancelled("Developer Agent run stopped by user.")

        def _apply_queued_steering(step: int) -> None:
            if steering_note_callback is None:
                return
            notes = [
                str(note).strip()
                for note in (steering_note_callback() or ())
                if str(note).strip()
            ]
            if not notes:
                return
            content = (
                "Developer Agent steering update from the user; apply this to the next visible reasoning step:\n"
                + "\n".join(f"- {note}" for note in notes)
            )
            messages.append({"role": "user", "content": content})
            self._append_event(
                events,
                AgentLoopEvent(
                    "steering",
                    f"Step {step}/{self.max_steps}: applied {len(notes)} steering note(s).",
                    {"step": step, "max_steps": self.max_steps, "count": len(notes)},
                ),
                event_callback,
            )

        try:
            _check_stop()
            for step in range(1, self.max_steps + 1):
                _check_stop()
                _apply_queued_steering(step)
                self._append_event(
                    events,
                    AgentLoopEvent(
                        "model",
                        f"Step {step}/{self.max_steps}: requesting active model response.",
                        {"step": step, "max_steps": self.max_steps},
                    ),
                    event_callback,
                )
                text = self._model_text(
                    messages,
                    prefer_stream_transport=True,
                    stop_requested=stop_requested,
                )
                _check_stop()
                if not text:
                    final_text = "Model returned an empty response."
                    messages.append({"role": "assistant", "content": final_text})
                    self._emit_visible_text(final_text, stream_callback)
                    self._append_event(
                        events, AgentLoopEvent("model", final_text), event_callback
                    )
                    break

                try:
                    request_action: ToolRequest = parse_tool_request_from_response(text)
                except ToolProtocolError:
                    final_text = self._clean_visible_final_text(text)
                    messages.append({"role": "assistant", "content": final_text})
                    self._emit_visible_text(final_text, stream_callback)
                    self._append_event(
                        events,
                        AgentLoopEvent("final", "Model returned final text."),
                        event_callback,
                    )
                    break

                self._append_event(
                    events,
                    AgentLoopEvent(
                        "tool_request",
                        f"Step {step}/{self.max_steps}: {request_action.tool.value}",
                        {
                            "step": step,
                            "max_steps": self.max_steps,
                            "reason": request_action.reason,
                            "args": request_action.args,
                        },
                    ),
                    event_callback,
                )
                _check_stop()
                result = executor.execute(request_action, approved=False)
                _check_stop()
                tool_results.append(result)
                self._append_event(
                    events,
                    AgentLoopEvent(
                        "tool_result",
                        result.message,
                        {
                            "ok": result.ok,
                            "requires_approval": result.requires_approval,
                        },
                    ),
                    event_callback,
                )
                self._emit_visible_text(
                    self._tool_progress_text(result), stream_callback
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": self._tool_request_message(request_action),
                    }
                )
                invalid_tool_result = self._is_invalid_tool_result(result)
                self._append_tool_result_message(
                    messages,
                    result,
                    force_final=(step == self.max_steps),
                    invalid_recovery=invalid_tool_result,
                )

                if invalid_tool_result:
                    deterministic_final = self._deterministic_invalid_tool_final(result)
                    if deterministic_final is not None:
                        final_text = deterministic_final
                        self._emit_visible_text(final_text, stream_callback)
                        messages.append({"role": "assistant", "content": final_text})
                        self._append_event(
                            events,
                            AgentLoopEvent(
                                "final",
                                "Stopped after invalid tool request without asking the model to repeat it.",
                                {"step": step, "max_steps": self.max_steps},
                            ),
                            event_callback,
                        )
                        break
                    self._append_event(
                        events,
                        AgentLoopEvent(
                            "model",
                            f"Step {step}/{self.max_steps}: recovering from invalid tool request.",
                            {"step": step, "max_steps": self.max_steps},
                        ),
                        event_callback,
                    )
                    final_text = self._force_final_after_invalid_tool(
                        messages,
                        stream_callback=stream_callback,
                        stop_requested=stop_requested,
                    )
                    messages.append({"role": "assistant", "content": final_text})
                    self._append_event(
                        events,
                        AgentLoopEvent("final", "Recovered from invalid tool request."),
                        event_callback,
                    )
                    break

                if (
                    step == self.max_steps
                    and request_action.tool.value != "propose_patch"
                    and not result.requires_approval
                ):
                    self._append_event(
                        events,
                        AgentLoopEvent(
                            "model",
                            f"Step {step}/{self.max_steps}: forcing final answer after tool limit.",
                            {"step": step, "max_steps": self.max_steps},
                        ),
                        event_callback,
                    )
                    final_text = self._force_final_after_tool_limit(
                        messages,
                        stream_callback=stream_callback,
                        stop_requested=stop_requested,
                    )
                    messages.append({"role": "assistant", "content": final_text})
                    self._append_event(
                        events,
                        AgentLoopEvent(
                            "final", "Forced final answer after tool limit."
                        ),
                        event_callback,
                    )
                    break

                if request_action.tool.value == "propose_patch" and result.ok:
                    proposal = executor.latest_proposal
                    final_text = "Patch proposal prepared for preview. Review the diff, then apply manually if approved."
                    self._emit_visible_text(final_text, stream_callback)
                    messages.append({"role": "assistant", "content": final_text})
                    return AgentLoopResult(
                        True,
                        request,
                        final_text,
                        tuple(events),
                        tuple(tool_results),
                        patch_proposal=proposal,
                        prompt_package=prepared.context.prompt_package,
                        system_prompt=prepared.system_prompt,
                        messages=tuple(messages),
                    )

                if result.requires_approval:
                    final_text = result.message
                    self._emit_visible_text(final_text, stream_callback)
                    messages.append({"role": "assistant", "content": final_text})
                    break

            else:
                final_text = "Stopped after the configured maximum tool steps."
                self._emit_visible_text(final_text, stream_callback)
                messages.append({"role": "assistant", "content": final_text})
                self._append_event(
                    events, AgentLoopEvent("stop", final_text), event_callback
                )
        except AgentLoopCancelled as exc:
            final_text = str(exc)
            self._emit_visible_text("\n\n> " + final_text + "\n", stream_callback)
            messages.append({"role": "assistant", "content": final_text})
            self._append_event(
                events, AgentLoopEvent("stop", final_text), event_callback
            )

        return AgentLoopResult(
            bool(final_text) and "stopped by user" not in final_text.casefold(),
            request,
            final_text,
            tuple(events),
            tuple(tool_results),
            patch_proposal=executor.latest_proposal,
            prompt_package=prepared.context.prompt_package,
            system_prompt=prepared.system_prompt,
            messages=tuple(messages),
        )

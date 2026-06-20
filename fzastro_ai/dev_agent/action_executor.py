from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .file_tools import DeveloperFileTools, DevFileToolError
from .patch_applier import (
    PatchPathError,
    apply_patch_proposal,
    make_patch_proposal,
    save_patch_exports,
)
from .safety import DevAgentSafetyError
from .test_runner import (
    CheckResult,
    ValidationPreset,
    run_command_safe,
    run_validation_preset,
)
from .types import (
    AgentMode,
    PatchProposal,
    SafetyMode,
    ToolName,
    ToolRequest,
    ToolResult,
)


class DevAgentActionError(ValueError):
    """Raised when a model-requested action is not valid for the current session."""


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise DevAgentActionError("Expected a string or list of strings")


def _check_result_payload(result: CheckResult) -> dict[str, Any]:
    summary = result.failure_summary()
    return {
        "command": list(result.command),
        "command_text": result.command_text,
        "returncode": result.returncode,
        "ok": result.ok,
        "elapsed_seconds": result.elapsed_seconds,
        "stdout_tail": result.stdout[-6000:],
        "stderr_tail": result.stderr[-6000:],
        "failure_summary": {
            "headline": summary.headline,
            "files": list(summary.files),
            "hints": list(summary.hints),
        },
    }


class DevAgentToolExecutor:
    """Validate and execute structured Developer Agent tool requests."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        mode: AgentMode | str = AgentMode.REVIEW_ONLY,
        safety_mode: SafetyMode | str = SafetyMode.READ_ONLY,
    ):
        self.project_root = Path(project_root).resolve()
        self.mode = AgentMode(mode)
        self.safety_mode = SafetyMode(safety_mode)
        self.file_tools = DeveloperFileTools(self.project_root)
        self.latest_proposal: PatchProposal | None = None
        self.latest_check: CheckResult | None = None

    def _mutation_allowed(self) -> bool:
        return self.mode in {
            AgentMode.PATCH_FILES,
            AgentMode.PATCH_RUN_TESTS,
            AgentMode.FULL_LOOP,
        }

    def _auto_edit_allowed(self) -> bool:
        return self.safety_mode == SafetyMode.AUTO_EDIT_PROJECT_ONLY

    def execute(self, request: ToolRequest, *, approved: bool = False) -> ToolResult:
        try:
            return self._execute(request, approved=approved)
        except (
            DevAgentActionError,
            DevAgentSafetyError,
            DevFileToolError,
            PatchPathError,
            ValueError,
        ) as exc:
            return ToolResult(False, request.tool, str(exc))

    def _execute(self, request: ToolRequest, *, approved: bool = False) -> ToolResult:
        tool = request.tool
        args = request.args or {}

        if tool == ToolName.LIST_FILES:
            files = self.file_tools.list_files(
                role=args.get("role"),
                pattern=args.get("pattern"),
                limit=int(args.get("limit", 250)),
            )
            return ToolResult(
                True, tool, f"Listed {len(files)} file(s).", {"files": files}
            )

        if tool == ToolName.SEARCH_TEXT:
            matches = self.file_tools.search_text(
                str(args.get("query") or ""),
                case_sensitive=bool(args.get("case_sensitive", False)),
                limit=int(args.get("limit", 100)),
                context_lines=int(args.get("context_lines", 1)),
            )
            return ToolResult(
                True, tool, f"Found {len(matches)} match(es).", {"matches": matches}
            )

        if tool == ToolName.READ_FILE:
            path = str(args.get("path") or args.get("relative_path") or "")
            text = self.file_tools.read_file(
                path, max_chars=int(args.get("max_chars", 50000))
            )
            return ToolResult(True, tool, f"Read {path}.", {"path": path, "text": text})

        if tool == ToolName.READ_FILE_RANGE:
            path = str(args.get("path") or args.get("relative_path") or "")
            text = self.file_tools.read_file_range(
                path,
                int(args.get("start_line", 1)),
                int(args.get("end_line", 80)),
            )
            return ToolResult(
                True, tool, f"Read range from {path}.", {"path": path, "text": text}
            )

        if tool == ToolName.SHOW_SYMBOL:
            symbol = str(args.get("symbol") or "")
            symbols = self.file_tools.show_symbol(
                symbol, limit=int(args.get("limit", 20))
            )
            return ToolResult(
                True,
                tool,
                f"Found {len(symbols)} symbol location(s).",
                {"symbols": symbols},
            )

        if tool == ToolName.PROPOSE_PATCH:
            diff = str(args.get("unified_diff") or args.get("diff") or "")
            if not self._mutation_allowed():
                return ToolResult(
                    False,
                    tool,
                    f"Patch proposals are disabled in {self.mode.value} mode.",
                    requires_approval=True,
                )
            proposal = make_patch_proposal(
                diff,
                reason=str(
                    args.get("reason") or request.reason or "model patch proposal"
                ),
                risk_level=str(args.get("risk_level") or "medium"),
                suggested_tests=_tuple_of_strings(args.get("suggested_tests")),
            )
            self.latest_proposal = proposal
            return ToolResult(
                True,
                tool,
                f"Prepared patch proposal for {proposal.changed_file_count} file(s). No files changed.",
                {"proposal": asdict(proposal)},
                requires_approval=True,
            )

        if tool == ToolName.APPLY_PATCH:
            if not self._mutation_allowed():
                return ToolResult(
                    False, tool, f"Apply is disabled in {self.mode.value} mode."
                )
            if self.safety_mode == SafetyMode.READ_ONLY:
                return ToolResult(
                    False, tool, "Apply is blocked by Read-only safety mode."
                )
            diff = str(args.get("unified_diff") or args.get("diff") or "")
            proposal = self.latest_proposal
            if diff:
                proposal = make_patch_proposal(
                    diff,
                    reason=str(
                        args.get("reason")
                        or request.reason
                        or "model patch apply request"
                    ),
                    risk_level=str(args.get("risk_level") or "medium"),
                    suggested_tests=_tuple_of_strings(args.get("suggested_tests")),
                )
            if proposal is None:
                raise DevAgentActionError("No patch proposal is available to apply")
            if not (approved or self._auto_edit_allowed()):
                return ToolResult(
                    False,
                    tool,
                    "Patch apply requires explicit UI approval.",
                    {"proposal": asdict(proposal)},
                    requires_approval=True,
                )
            result = apply_patch_proposal(
                self.project_root,
                proposal,
                approved=True,
                label="developer_agent_model",
            )
            data = {"ok": result.ok, "stdout": result.stdout, "stderr": result.stderr}
            if result.snapshot:
                data["snapshot"] = asdict(result.snapshot)
            return ToolResult(result.ok, tool, result.message, data)

        if tool == ToolName.RUN_TESTS:
            if self.mode not in {AgentMode.PATCH_RUN_TESTS, AgentMode.FULL_LOOP}:
                return ToolResult(
                    False,
                    tool,
                    f"Validation runs are disabled in {self.mode.value} mode.",
                )
            preset = ValidationPreset(
                str(args.get("preset") or ValidationPreset.COMPILE_ONLY.value)
            )
            changed_paths = _tuple_of_strings(args.get("changed_paths"))
            result = run_validation_preset(
                self.project_root,
                preset,
                changed_paths=changed_paths,
                approved=approved,
                timeout_seconds=args.get("timeout_seconds"),
            )
            self.latest_check = result
            return ToolResult(
                result.ok,
                tool,
                f"{preset.value}: {'PASS' if result.ok else 'FAIL'} ({result.returncode})",
                _check_result_payload(result),
            )

        if tool == ToolName.RUN_COMMAND_SAFE:
            raw_command = args.get("command")
            if not isinstance(raw_command, (list, tuple)):
                raise DevAgentActionError("run_command_safe requires command as a list")
            result = run_command_safe(
                self.project_root,
                tuple(str(part) for part in raw_command),
                approved=approved,
                timeout_seconds=int(args.get("timeout_seconds", 180)),
            )
            self.latest_check = result
            return ToolResult(
                result.ok, tool, "Command finished.", _check_result_payload(result)
            )

        if tool == ToolName.READ_TEST_OUTPUT:
            if self.latest_check is None:
                return ToolResult(False, tool, "No validation output is available yet.")
            return ToolResult(
                True,
                tool,
                "Returned latest validation output.",
                _check_result_payload(self.latest_check),
            )

        if tool == ToolName.SUMMARIZE_CHANGES:
            paths = _tuple_of_strings(args.get("paths") or args.get("changed_paths"))
            summary = self.file_tools.summarize_changes(paths)
            return ToolResult(True, tool, "Summarized changed files.", summary)

        raise DevAgentActionError(f"Unsupported tool: {tool.value}")

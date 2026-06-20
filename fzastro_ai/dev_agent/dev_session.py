from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context_builder import DevContext, build_dev_context
from .file_tools import DeveloperFileTools
from .memory import load_developer_agent_memory
from .project_scanner import ProjectScan, scan_project
from .prompt import build_agent_system_prompt
from .task_classifier import DevTask, classify_dev_task
from .types import AgentMode, SafetyMode


@dataclass(frozen=True)
class DevSessionResult:
    task: DevTask
    scan: ProjectScan
    context: DevContext
    plan_markdown: str
    system_prompt: str
    mode: AgentMode = AgentMode.REVIEW_ONLY
    safety_mode: SafetyMode = SafetyMode.READ_ONLY


class DevAgentSession:
    """Orchestrates visible, safe Developer Agent preparation steps."""

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
        self.scan: ProjectScan | None = None
        self.file_tools = DeveloperFileTools(self.project_root)

    def refresh_scan(self) -> ProjectScan:
        self.scan = scan_project(self.project_root)
        self.file_tools._last_scan = self.scan
        return self.scan

    def classify(self, request: str) -> DevTask:
        return classify_dev_task(request)

    def build_context(self, request: str, *, extra_text: str = "") -> DevContext:
        if self.scan is None:
            self.refresh_scan()
        return build_dev_context(
            self.project_root,
            request,
            scan=self.scan,
            extra_text=extra_text,
        )

    def build_system_prompt(self) -> str:
        memory = load_developer_agent_memory()
        return build_agent_system_prompt(
            mode=self.mode,
            safety_mode=self.safety_mode,
            project_rules=memory.rules,
        )

    def create_visible_plan(self, context: DevContext) -> str:
        task = context.task
        lines = [
            "# FZAstro AI Developer Agent Plan",
            "",
            f"Agent mode: **{self.mode.value}**",
            f"Safety mode: **{self.safety_mode.value}**",
            f"Task class: **{task.mode.upper()}**",
            f"Context scope: **{task.scope}**",
            "",
            "## Goal",
            task.request
            or "Prepare a focused developer context for the current project.",
            "",
        ]

        if task.scope == "project_audit":
            deep_files = [file for file in context.files if file.excerpt]
            lines.extend(
                [
                    "## Project audit coverage",
                    f"- Indexed **{context.audit_file_count}** Python files from the current scan.",
                    "- The full Python file index is in the Context tab and included in the model prompt.",
                    f"- Deep-read excerpts are initially included for the top **{len(deep_files)}** files below; ask follow-up questions to inspect more files or directories.",
                    "",
                    "## Initial deep-read files",
                ]
            )
            for file in deep_files:
                modified = (
                    " · modified"
                    if any(
                        scan_file.path == file.path and scan_file.modified
                        for scan_file in (self.scan.files if self.scan else ())
                    )
                    else ""
                )
                lines.append(f"- `{file.path}` — {file.reason}{modified}")
        else:
            lines.append("## Selected files to inspect")
            for file in context.files:
                modified = (
                    " · modified"
                    if any(
                        scan_file.path == file.path and scan_file.modified
                        for scan_file in (self.scan.files if self.scan else ())
                    )
                    else ""
                )
                lines.append(f"- `{file.path}` — {file.reason}{modified}")

        lines.extend(
            [
                "",
                "## Tool workflow",
                "1. Inspect selected files with read/search tools before proposing edits.",
                "2. Produce an implementation plan and risk explanation.",
                "3. Generate a `PatchProposal` unified diff only; do not rewrite arbitrary files.",
                "4. Preview changed files and diff in the UI.",
                "5. Apply only after approval unless safety mode explicitly permits auto-edit inside project root.",
                "6. Run validation preset: `Compile Only` after Python changes, then targeted pytest.",
                "7. Parse failures, propose a follow-up patch, and stop after the configured iteration limit.",
                "8. Produce final report with changed files, commands, pass/fail status, limitations, and EXE rebuild requirement.",
                "",
                "## Hard safety boundaries",
                "- No file claim without reading that file.",
                "- No test claim without validation output.",
                "- No edit without patch preview unless auto-edit is explicitly enabled.",
                "- No dangerous command without approval.",
                "- No hardware, N.I.N.A. sequence start, guiding, capture, or power action from OpenClaude.",
                "- No modifying `external/` or `bundled_apps/` by default.",
                "",
                "## Acceptance criteria",
                "- The patch is small, reviewable, and inside the selected project root.",
                "- Relevant compile/tests pass, or failures are reported with exact output summary.",
                "- The final summary states whether a rebuilt EXE is required.",
            ]
        )
        return "\n".join(lines)

    def prepare(self, request: str, *, extra_text: str = "") -> DevSessionResult:
        scan = self.refresh_scan()
        context = self.build_context(request, extra_text=extra_text)
        return DevSessionResult(
            task=context.task,
            scan=scan,
            context=context,
            plan_markdown=self.create_visible_plan(context),
            system_prompt=self.build_system_prompt(),
            mode=self.mode,
            safety_mode=self.safety_mode,
        )

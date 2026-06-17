from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context_builder import DevContext, build_dev_context
from .project_scanner import ProjectScan, scan_project
from .task_classifier import DevTask, classify_dev_task


@dataclass(frozen=True)
class DevSessionResult:
    task: DevTask
    scan: ProjectScan
    context: DevContext
    plan_markdown: str


class DevAgentSession:
    """Orchestrates the safe, visible developer-workbench preparation steps."""

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root).resolve()
        self.scan: ProjectScan | None = None

    def refresh_scan(self) -> ProjectScan:
        self.scan = scan_project(self.project_root)
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

    def create_visible_plan(self, context: DevContext) -> str:
        task = context.task
        lines = [
            "# AI Developer Workbench Plan",
            "",
            f"Mode: **{task.mode.upper()}**",
            "",
            "## Goal",
            task.request
            or "Prepare a focused developer context for the current project.",
            "",
            "## Selected files",
        ]
        for file in context.files:
            lines.append(f"- `{file.path}` — {file.reason}")

        lines.extend(
            [
                "",
                "## Execution steps",
                "1. Review the selected files and confirm the change boundary.",
                "2. Produce a unified diff instead of rewriting unrelated files.",
                "3. Keep a rollback snapshot before applying any patch.",
                "4. Run `python -m compileall -q fzastro_ai tests`.",
                "5. Run targeted `pytest` first, then broader release checks if needed.",
                "6. Summarize changed files, tests, and a suggested git command.",
                "",
                "## Acceptance criteria",
                "- The requested behavior is implemented or explained clearly.",
                "- Existing production features remain unchanged unless requested.",
                "- Relevant tests pass or failures are summarized with next fix steps.",
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
        )

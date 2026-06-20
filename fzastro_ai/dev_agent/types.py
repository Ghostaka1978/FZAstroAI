from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentMode(str, Enum):
    """Visible operating modes for Developer Agent Mode."""

    REVIEW_ONLY = "Review Only"
    PLAN_ONLY = "Plan Only"
    PATCH_FILES = "Patch Files"
    PATCH_RUN_TESTS = "Patch + Run Tests"
    FULL_LOOP = "Full Loop"


class SafetyMode(str, Enum):
    """Safety gates that decide whether tools may mutate files or run commands."""

    READ_ONLY = "Read-only"
    ASK_BEFORE_EDITING = "Ask Before Editing"
    AUTO_EDIT_PROJECT_ONLY = "Auto-edit Inside Project Only"
    ADVANCED_UNSAFE_APPROVAL = "Advanced/Unsafe Commands Require Approval"


class ToolName(str, Enum):
    LIST_FILES = "list_files"
    SEARCH_TEXT = "search_text"
    READ_FILE = "read_file"
    READ_FILE_RANGE = "read_file_range"
    SHOW_SYMBOL = "show_symbol"
    PROPOSE_PATCH = "propose_patch"
    APPLY_PATCH = "apply_patch"
    RUN_TESTS = "run_tests"
    RUN_COMMAND_SAFE = "run_command_safe"
    READ_TEST_OUTPUT = "read_test_output"
    SUMMARIZE_CHANGES = "summarize_changes"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolRequest:
    """Structured JSON-style tool request from a local/cloud coding model."""

    tool: ToolName
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class ToolResult:
    """Validated tool result passed back into the agent loop."""

    ok: bool
    tool: ToolName
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False


@dataclass(frozen=True)
class PatchProposal:
    """Reviewable patch object produced before any file mutation."""

    target_files: tuple[str, ...]
    unified_diff: str
    reason: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    suggested_tests: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed_file_count(self) -> int:
        return len(self.target_files)


@dataclass(frozen=True)
class AgentRunReport:
    """Final engineering summary for one visible agent run."""

    task: str
    mode: AgentMode
    safety_mode: SafetyMode
    changed_files: tuple[str, ...] = field(default_factory=tuple)
    validation_commands: tuple[str, ...] = field(default_factory=tuple)
    validation_passed: bool | None = None
    known_limitations: tuple[str, ...] = field(default_factory=tuple)
    exe_rebuild_required: bool = False

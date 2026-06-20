"""FZAstro AI Developer Agent backend primitives.

This package is UI-agnostic. It provides safe project scanning, focused context
selection, project-root-bounded file tools, patch proposal/apply helpers,
validation presets, persistent project rules, and the structured types used by
Developer Agent Mode.
"""

from .context_builder import ContextFile, DevContext, build_dev_context
from .dev_session import DevAgentSession, DevSessionResult
from .agent_loop import AgentLoopEvent, AgentLoopResult, DevAgentLoop
from .action_executor import DevAgentToolExecutor
from .llm_client import (
    AgentModelResponse,
    DevAgentLLMError,
    OllamaAgentClient,
    OllamaAgentConfig,
)
from .file_tools import DeveloperFileTools
from .patch_applier import PatchApplyResult, PatchSnapshot, make_patch_proposal
from .project_scanner import ProjectFile, ProjectScan, scan_project
from .prompt import (
    LOCAL_CODING_AGENT_SYSTEM_PROMPT,
    PROJECT_RULES,
    build_agent_system_prompt,
)
from .task_classifier import DevTask, classify_dev_task
from .test_runner import ValidationPreset, run_validation_preset
from .types import (
    AgentMode,
    AgentRunReport,
    PatchProposal,
    RiskLevel,
    SafetyMode,
    ToolName,
    ToolRequest,
    ToolResult,
)

__all__ = [
    "AgentLoopEvent",
    "AgentLoopResult",
    "AgentModelResponse",
    "DevAgentLLMError",
    "DevAgentLoop",
    "DevAgentToolExecutor",
    "OllamaAgentClient",
    "OllamaAgentConfig",
    "AgentMode",
    "AgentRunReport",
    "ContextFile",
    "DevAgentSession",
    "DevContext",
    "DevSessionResult",
    "DevTask",
    "DeveloperFileTools",
    "LOCAL_CODING_AGENT_SYSTEM_PROMPT",
    "PROJECT_RULES",
    "PatchApplyResult",
    "PatchProposal",
    "PatchSnapshot",
    "ProjectFile",
    "ProjectScan",
    "RiskLevel",
    "SafetyMode",
    "ToolName",
    "ToolRequest",
    "ToolResult",
    "ValidationPreset",
    "build_agent_system_prompt",
    "build_dev_context",
    "classify_dev_task",
    "make_patch_proposal",
    "run_validation_preset",
    "scan_project",
]

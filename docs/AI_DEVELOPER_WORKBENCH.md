# Developer Agent Mode

Developer Agent Mode is the local, preview-first coding-agent cockpit inside FZAstro AI. It replaces the early Developer Workbench direction with a safer Claude-Code-style workflow: inspect real project files, build a plan, request structured tools, preview patches, apply only after approval, and run real validation output.

## Current workflow

```text
request -> scan project -> build focused context or project-audit index -> active app model -> hidden JSON tool loop -> visible streamed Markdown/tool progress -> follow-up replies as needed -> plan or PatchProposal -> preview diff -> approved apply -> validation -> final report
```

The feature is still intentionally bounded. The local model can inspect, plan, and prepare a patch proposal, but patch application, build scripts, release validation, and unsafe commands remain visible approval-gated actions.

## Backend modules

```text
fzastro_ai/dev_agent/
  __init__.py
  action_executor.py      # validates and executes JSON tool actions
  agent_loop.py           # controlled inspect/plan/patch-proposal loop
  context_builder.py      # focused context and project-audit package builder
  dev_session.py          # session preparation and visible plan generation
  error_analyzer.py       # validation-output summarizer
  file_tools.py           # project-root-bounded read/search/symbol tools
  git_tools.py            # git status helpers
  llm_client.py           # active FZAstro runtime client with streaming; never auto-starts Ollama
  memory.py               # persistent project rules
  patch_applier.py        # unified diff proposal/apply/export helpers
  project_scanner.py      # scanner with ignored/generated folder rules
  prompt.py               # local coding-agent system prompt and project rules
  safety.py               # path and command safety gates
  session_store.py        # session persistence helpers
  task_classifier.py      # task/path/role classifier
  test_runner.py          # compile/pytest/build validation presets
  tool_protocol.py        # structured JSON action parsing
  types.py                # shared dataclasses/enums

fzastro_ai/ui/dev_workbench_dialog.py
fzastro_ai/actions/dev_actions.py
```

## UI entry point

Click **DEV** in the quick actions bar. The cockpit includes:

- project root selector that restores the last valid folder from Developer Agent memory when the DEV panel opens
- agent mode selector
- safety mode selector
- compact one-line project/mode/safety selector row
- active runtime status copied from the main FZAstro model controls
- task/reply input
- steering input for visible guidance such as focus areas, exclusions, depth, or risk priorities; it steers the next agent step without exposing hidden chain-of-thought
- compact telemetry/status strip mirroring the main app where available: agent state, GPU/VRAM, and CPU/RAM
- progress bar for scan, context build, streaming/tool-loop, patch preview/apply, validation, and report phases
- numbered workflow buttons: **1 Scan Project**, **2 Build Plan**, **3 Ask / Reply**, **Stop Agent**, **4 Preview Patch**, **5 Apply Patch**, **6 Compile**, **7 Final Report**. The next recommended action is highlighted as `NEXT`, blocked actions are visually muted, and tooltips explain when an action is waiting for a task, diff, preview, or approval.
- a reusable **New Chat** control for clearing the agent conversation while keeping the scan/context available
- a single rendered Markdown **Agent Workspace** timeline for plans, answers, tool progress, patch proposal cards, patch preview cards, validation cards, and final reports so normal work does not require tab switching
- minimized **Evidence** panel for selected/scanned files; it is collapsed by default and can be expanded only when the user wants to inspect file selection
- right-side **Advanced Diagnostics** drawer for tool log, context package, raw patch diff, validation output, and report output; it opens on demand as a resizable side panel with its own scroll area so technical trace detail does not push the main workspace down
- hidden tool loop execution: raw JSON actions are parsed, validated, executed, and stored in conversation history instead of being printed into the chat
- conversation memory for follow-up replies: when the agent asks a question, type the reply in the task box and click **3 Ask / Reply** again
- visible stop/timeout handling: **Stop Agent** requests cooperative cancellation and the status strip shows loop step, stopped, timeout, error, and done states
- patch preview with inline workspace guidance when no unified diff exists; **4 Preview Patch** is a validator for an existing patch, not a patch generator
- project-aware validation cards shown inline in the workspace, with full raw output retained under Advanced Diagnostics. FZAstro repos use the known FZAstro validation profile; generic Python folders use project-root compileall/pytest automatically.
- hardened patch apply semantics: `/dev/null` new-file diffs are supported, already-applied sections can be safely skipped while still applying remaining valid sections, failed apply attempts list failed paths plus `git apply` details, and malformed diffs are preflighted before Apply is enabled.
- generic-project validation and reporting: Compile on non-FZAstro Python folders runs compile plus pytest/clean skip, final reports show the detected profile, and EXE rebuild is required only for FZAstro application Python changes.
- chat-like composer UX: submitted Ask/Reply text is moved into the Agent Workspace and the composer is cleared for the next reply.

## Focused context vs project audit

**Build Plan** has two context scopes:

- **Focused context** for specific requests such as `fix app.py` or `explain shutdown_controller.py`. It selects a small ranked file set and includes deeper excerpts.
- **Project audit** for broad requests such as `analyse all my Python files`, `analyse my app`, `full codebase review`, or `identify risks`. It indexes every scanned Python file in the Context tab and includes deep-read excerpts only for the highest-ranked files so the prompt stays bounded. The agent must use follow-up read/search tools before claiming detailed body-level findings for non-excerpted files.

This prevents the misleading behavior where a request for all Python files silently selected only a small focused set.

In **Review Only** mode, broad project audits are still allowed to use safe read-only tools. For tasks such as `Deep analyse my app for risks`, the agent now preloads representative files before asking the active model for a final answer. This is the Codex-style behavior: inspect evidence first, then report.

## Patch preview flow

**4 Preview Patch** only validates a generated or pasted unified diff. It does not ask the model to create a patch. If no diff exists, the Agent Workspace shows inline guidance instead of a modal warning.

Recommended patch flow:

1. Switch **Mode** to **Patch Files** or **Patch + Run Tests**.
2. Keep **Safety** on **Ask Before Editing** unless intentionally using a stricter read-only review.
3. Ask through **3 Ask / Reply**: `Propose a safe patch for <issue>. Do not apply it yet.`
4. Review the generated diff in the Agent Workspace. Raw diff details remain available under **Advanced Diagnostics -> Patch Diff**.
5. Click **4 Preview Patch** to validate patch paths, risk, and changed files.
6. Click **5 Apply Patch** only after the diff is acceptable.

In **Review Only** or **Plan Only**, Step 4 explains that a patch is unavailable and tells the user how to switch modes when they want a diff.

Follow-up inspection turns are evidence-first. If the model asks for a `read_file` or search tool during a follow-up, the app executes the safe tool, appends the tool result back into the conversation, and explicitly asks the model to continue with a final answer or one more justified tool call. This prevents a turn from ending with only `Tool read_file ... ok` and no conclusion. Invalid tool calls such as an empty `search_text` query are converted into a recovery turn instead of looping until timeout.

The read-only preload covers these areas where matching files exist: entry/app integration, runtime/model integration, shutdown/worker lifecycle, Developer Agent safety, Web Companion boundary, N.I.N.A./hardware boundary, astro planning/data, state/data persistence, and command/tool execution. The final report must name inspected files, separate evidence-backed findings from unverified areas, and avoid claiming full-body inspection for files that were only indexed.

## Structured tool protocol

The local model must emit one JSON tool action at a time when it wants the app to do something. The UI hides raw JSON tool calls, executes the validated action, shows a short tool-progress line, and feeds the tool result back to the model:

```json
{
  "tool": "read_file",
  "args": {"path": "fzastro_ai/runtime.py"},
  "reason": "Inspect runtime shutdown handling before proposing a patch."
}
```

Supported tools:

```text
list_files
search_text
read_file
read_file_range
show_symbol
propose_patch
apply_patch
run_tests
run_command_safe
read_test_output
summarize_changes
```

Patch proposals use unified diffs only:

```json
{
  "tool": "propose_patch",
  "args": {
    "unified_diff": "--- a/fzastro_ai/runtime.py\n+++ b/fzastro_ai/runtime.py\n@@ ...",
    "reason": "Small targeted runtime fix.",
    "risk_level": "low",
    "suggested_tests": ["Compile Only", "Feature Tests"]
  },
  "reason": "Prepare reviewable diff; do not apply yet."
}
```

## Safety model

Hard boundaries:

1. No file claim without reading or searching that file.
2. No test claim without validation output.
3. No direct file rewrite from model text; patches must be `PatchProposal` unified diffs.
4. No patch apply in Read-only mode.
5. No patch apply without explicit approval unless Auto-edit Inside Project Only is selected.
6. No mutation of `external/`, `bundled_apps/`, `.venv`, build output, caches, or generated areas by default.
7. No dangerous shell command unless explicitly approved.
8. No hardware, N.I.N.A. sequence start, guiding, capture, or power action from Developer Agent Mode.
9. Local Ollama is never auto-started by the agent client; Developer Agent Mode uses the active main-app runtime and only sends requests when that runtime is already available.

## Validation commands

Core validation for Developer Agent Mode:

```powershell
python -m compileall -q main.py fzastro_ai tests
python -m pytest -q tests/test_dev_agent_project_scanner.py tests/test_dev_agent_context_builder.py tests/test_dev_agent_patch_applier.py tests/test_dev_agent_error_analyzer.py tests/test_dev_agent_file_tools.py tests/test_dev_agent_test_runner.py tests/test_dev_agent_prompt_and_memory.py tests/test_dev_agent_tool_protocol.py tests/test_dev_agent_action_executor_and_loop.py
```

Build EXE and Release Validation remain approval-gated because they execute PowerShell scripts.

## Remaining work

Next stages are controlled auto-fix loops, deeper persistent memory/rule editing, richer UI state, and optional cloud fallback through the same main-app runtime. Full autonomy is not enabled by default.


### Developer Agent UX polish

- Developer Agent remembers the last valid project root and restores it on reopen.
- The cockpit shows a progress bar plus telemetry/status while scanning, planning, streaming, patching, and validating.
- Stop Agent uses cooperative cancellation with shorter model-read timeouts and clearer progress/status text.
- File planning is generic and evidence-driven: task-management words such as `PatchProposal`, `unified`, `diff`, `summary`, `validation`, and `risk` are filtered from relevance scoring so patch tasks select implementation/test evidence instead of Developer Agent meta-files.
- Invalid empty tool requests stop with actionable guidance instead of looping until timeout.


### Single-workspace layout

Developer Agent normal workflow now uses one chat-like **Agent Workspace** instead of a Log/Chat/Context/Patch/Validation/Report tab hunt. Evidence files and Advanced Diagnostics open in an on-demand resizable right-side drawer with internal scrolling, while patch/validation/report outcomes are appended as inline cards in the workspace. Runtime/model details and the separate Steering Prompt were removed from the drawer; the main app model bar and the single task/reply composer are the user-facing controls. Validation is project-aware, so generic Python folders run from their selected root instead of inheriting FZAstro-specific commands.

### Next-action workflow controls

The workflow row now marks one primary next action at a time. Examples: after scanning, **2 Build Plan** is marked as next; after context is built, **3 Ask / Reply** is marked as next; after a patch proposal exists, **4 Preview Patch** is marked as next; after preview succeeds, **5 Apply Patch** becomes available. This keeps the cockpit explicit without enabling hidden edits.

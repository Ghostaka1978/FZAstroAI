# OpenClaude

OpenClaude is the dedicated coding workspace in FZAstro AI v2.4.0. This release retires the old experimental Developer Workbench / legacy DEV testbed from the normal UI and replaces it with a terminal-first OpenClaude experience.

FZAstro now acts as a workspace-aware OpenClaude host:

- **Session** contains setup/defaults only: workspace folder, selected model and endpoint, git repository details, AGENTS.md status, terminal frontend/backend status, and internal tools.
- **Claude Terminal** is the primary interface. Type directly into the embedded OpenClaude terminal exactly as in the standalone CLI.
- FZAstro supplies environment variables, working directory, terminal hosting, telemetry, and setup/deploy checks.
- OpenClaude owns the coding conversation, file inspection, file creation/editing, command execution, tests, and git interaction inside the selected workspace.

## What was removed from the normal UI

The old legacy DEV surface is not part of the production OpenClaude workspace:

- no Timeline tab
- no Evidence drawer
- no Advanced Diagnostics drawer
- no External Terminal button
- no Manual Input control
- no mode/safety controls
- no legacy scan/plan/ask controls
- no separate FZAstro Task/reply composer
- no bottom hard-boundary footer

Those controls belonged to the earlier internal testbed. The production UX is a real OpenClaude terminal with a small setup panel.

## Workspace and git awareness

Session makes the selected workspace explicit before OpenClaude starts. This is important because OpenClaude can create files, edit files, run Python/tests/scripts, and use git in that folder. Session is scrollable so long diagnostics remain reachable; it shows the selected path, workspace boundary, git ceiling, full git root path, branch, selected-clone remote, dirty/clean state, API endpoint/model, hidden Git API token status, AGENTS.md status, and terminal frontend state.

The **Git API Token** field is for repository API access, not the model endpoint. FZAstro stores that token only under `AppData\Roaming\FZAstroAI\openclaude\openclaude_settings.json`, exposes it to the OpenClaude process as `GITHUB_TOKEN`/`GH_TOKEN`, and never writes it to the selected workspace, `AGENTS.md`, generated context, terminal diagnostics, or launcher script. The visible environment uses `FZASTRO_OPENCLAUDE_GIT_TOKEN_FILE`, not the misleading old `FZASTRO_OPENCLAUDE_API_KEY_FILE` name. OpenClaude Git commands also run with `GIT_CEILING_DIRECTORIES`, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`, and an empty `credential.helper` override so the terminal does not silently use machine/global Git credentials from another checkout.

Git identity shown in Session comes only from the selected workspace `.git/config`. If a test clone still shows the production remote, that means the selected clone's own `origin` points at the same GitHub repository; it does not mean FZAstro queried a parent or sibling checkout.

## Project rules

FZAstro can create `AGENTS.md` in the selected workspace when missing. This file stores stable project rules such as small patches, inspect relevant files before editing, run tests after code changes, and ask before destructive commands or hardware/N.I.N.A. operations.

## Normal workflow

1. Open **OpenClaude**.
2. In **Session**, select the intended workspace. Do not point at a live repo unless that is intentional.
3. Confirm model, endpoint, git status, and terminal backend/frontend readiness.
4. Open **Claude Terminal** and press **Start**.
5. Type directly into the OpenClaude prompt.

Example prompts typed directly in the terminal:

```text
/help
Inspect this repository and summarize the important files.
Create one empty Python file named openclaude_test.py and verify it exists.
Run python -m compileall -q main.py fzastro_ai tests and summarize the result.
```

## Windows OpenClaude prerequisites

FZAstro setup/deploy prepares the embedded OpenClaude path. For a source checkout, the expected Windows tools are:

```powershell
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Git.Git
winget install -e --id BurntSushi.ripgrep.MSVC
npm install -g @gitlawb/openclaude@latest
```

Then verify:

```powershell
node -v
npm -v
git --version
rg --version
openclaude --version
```

The embedded terminal uses the selected FZAstro model/provider. For Ollama this means the main app-selected model is passed as `OPENAI_MODEL` with `OPENAI_BASE_URL=http://localhost:11434/v1`.

## Embedded OpenClaude

OpenClaude is now the visible coding workspace for the OpenClaude tab. FZAstro does not expose the old internal scan/plan/ask controls, Timeline, Evidence drawer, Advanced Diagnostics drawer, External Terminal action, or separate Manual Input row in the normal UI.

The intended interaction is Codex-style:

1. open **Session** once and choose the workspace folder,
2. confirm model/endpoint/git/AGENTS.md/terminal status in Session,
3. switch to **Claude Terminal**,
4. click **Start** if OpenClaude is not already running,
5. type directly into the embedded terminal exactly as in the standalone OpenClaude CLI.

The Session tab is setup/status-only. The Claude Terminal tab stays clean and owns only live terminal controls:

- **Start** starts OpenClaude inside the selected workspace.
- **Restart** restarts OpenClaude when it is already running.
- **Stop** requests terminal cancellation.
- **Clear** clears the visible terminal buffer.
- **Paste** sends clipboard text to the running terminal.
- **Page Up** and **Bottom** let the user inspect scrollback without forcing live output back to the bottom.
- **Screenshot** saves a visible terminal PNG and copies the saved path.
- **Paste Image** saves a clipboard screenshot/image under `.fzastro/openclaude_attachments` in the selected workspace and sends OpenClaude a path handoff prompt.
- **Attach Image** copies a selected PNG/JPG/WebP/BMP into that workspace attachment folder and sends the same path handoff.
- **Send Shot** captures the current terminal view into the workspace attachment folder and sends its path to OpenClaude.

There is no separate **Status** button in the terminal header. Diagnostics are refreshed in Session so status text cannot pollute the OpenClaude terminal transcript. Session also reports the active terminal start settings and warns when the running process is stale after a workspace/model/endpoint/Git-token change.

There is no separate FZAstro chat box in the OpenClaude screen. The terminal is the input. Commands such as `/help`, normal coding requests, shell instructions, and OpenClaude shortcuts are typed directly into the terminal renderer.

FZAstro writes minimal setup/status files under `AppData\Roaming\FZAstroAI\openclaude` for audit/debugging. Stable workspace rules are placed in `AGENTS.md` when missing, so OpenClaude can behave like a normal Codex/Claude-Code-style agent without FZAstro pasting a hidden prompt into the terminal.

The preferred renderer is a real terminal frontend: Qt WebEngine + local `xterm.js` assets connected to Windows ConPTY through `pywinpty`. If WebEngine or the `xterm.js` assets are missing, FZAstro falls back to a basic transcript view and reports that the real terminal frontend is unavailable. Prepare the frontend during setup/deploy with `scripts\setup_openclaude_companion.ps1 -InstallTerminalFrontend`.

OpenClaude can inspect/create/edit files, run Python/tests/scripts, and inspect/update git inside the selected workspace according to the user conversation and `AGENTS.md`. FZAstro no longer exposes separate mode/safety controls for OpenClaude; those behaviors belong to OpenClaude and the project rules.

Packaging note: true embedded terminal mode requires `pywinpty` on Windows. Runtime package setup is intentionally not exposed as an app button. `requirements.txt`, `DEPLOY.bat`, `scripts/deploy.ps1`, `scripts/setup_openclaude_companion.ps1`, `scripts/build_exe.ps1`, and `FZAstroAI.spec` prepare and package the backend during source setup/build/deploy. The app reports backend readiness instead of installing packages at runtime.

## Focused context vs project audit

**OpenClaude project context** has two scopes:

- **Focused context** for specific requests such as `fix app.py` or `explain shutdown_controller.py`. It selects a small ranked file set and includes deeper excerpts.
- **Project audit** for broad requests such as `analyse all my Python files`, `analyse my app`, `full codebase review`, or `identify risks`. It indexes every scanned Python file in the Context tab and includes deep-read excerpts only for the highest-ranked files so the prompt stays bounded. The agent must use follow-up read/search tools before claiming detailed body-level findings for non-excerpted files.

This prevents the misleading behavior where a request for all Python files silently selected only a small focused set.

In **Review Only** mode, broad project audits are still allowed to use safe read-only tools. For tasks such as `Deep analyse my app for risks`, the agent now preloads representative files before asking the active model for a final answer. This is the Codex-style behavior: inspect evidence first, then report.

## Patch preview flow

**4 Preview Patch** only validates a generated or pasted unified diff. It does not ask the model to create a patch. If no diff exists, the Agent Workspace shows inline guidance instead of a modal warning.

Recommended patch flow:

1. Start OpenClaude in the **Claude Terminal** tab.
2. Type the task directly in the terminal, for example: `Propose a safe patch for <issue>. Do not apply it yet.`
3. Let OpenClaude inspect files and produce a changed-file summary or diff.
4. Use **Session -> Tools -> Preview Diff** when a local diff exists.
5. Click **Preview Diff** to validate patch paths, risk, and changed files.
6. Click **Apply Diff** only after the diff is acceptable.

Review/patch/test behavior is driven by OpenClaude, the user prompt, and `AGENTS.md`; FZAstro no longer exposes separate OpenClaude mode/safety controls.

Follow-up inspection turns are evidence-first. If the model asks for a `read_file` or search tool during a follow-up, the app executes the safe tool, appends the tool result back into the conversation, and explicitly asks the model to continue with a final answer or one more justified tool call. This prevents a turn from ending with only `Tool read_file ... ok` and no conclusion. Invalid tool calls such as an empty `search_text` query are converted into a recovery turn instead of looping until timeout.

The read-only preload covers these areas where matching files exist: entry/app integration, runtime/model integration, shutdown/worker lifecycle, OpenClaude safety, Web Companion boundary, N.I.N.A./hardware boundary, astro planning/data, state/data persistence, and command/tool execution. The final report must name inspected files, separate evidence-backed findings from unverified areas, and avoid claiming full-body inspection for files that were only indexed.

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
8. No hardware, N.I.N.A. sequence start, guiding, capture, or power action from OpenClaude.
9. Local Ollama is never auto-started by the agent client; OpenClaude uses the active main-app runtime and only sends requests when that runtime is already available.

## Validation commands

Core validation for OpenClaude:

```powershell
python -m compileall -q main.py fzastro_ai tests
python -m pytest -q tests/test_dev_agent_project_scanner.py tests/test_dev_agent_context_builder.py tests/test_dev_agent_patch_applier.py tests/test_dev_agent_error_analyzer.py tests/test_dev_agent_file_tools.py tests/test_dev_agent_test_runner.py tests/test_dev_agent_prompt_and_memory.py tests/test_dev_agent_tool_protocol.py tests/test_dev_agent_action_executor_and_loop.py
```

Build EXE and Release Validation remain approval-gated because they execute PowerShell scripts.

## Remaining work

Next stages are controlled auto-fix loops, deeper persistent memory/rule editing, richer UI state, and optional cloud fallback through the same main-app runtime. Full autonomy is not enabled by default.


### OpenClaude UX polish

- OpenClaude remembers the last valid project root and restores it on reopen.
- The OpenClaude page shows compact telemetry plus a colored running/stopped state indicator; the old progress bar is removed so the terminal keeps maximum space.
- Terminal ergonomics include text paste, stable scrollback, terminal screenshot capture, clipboard image handoff, file image handoff, and current-terminal screenshot handoff into `.fzastro/openclaude_attachments`. The terminal remains raw; screenshots are passed as workspace-local files plus an explicit prompt so non-vision models must say when they cannot decode pixels.
- Stop Agent uses cooperative cancellation with shorter model-read timeouts and clearer progress/status text.
- File planning is generic and evidence-driven: task-management words such as `PatchProposal`, `unified`, `diff`, `summary`, `validation`, and `risk` are filtered from relevance scoring so patch tasks select implementation/test evidence instead of OpenClaude meta-files.
- Invalid empty tool requests stop with actionable guidance instead of looping until timeout.


### Single-workspace layout

OpenClaude normal workflow now uses a compact two-tab workspace: **Session** for setup/details and **Claude Terminal** for direct interaction. The main app model bar and embedded terminal are the user-facing controls. Session includes the terminal state, workspace boundary, git identity source, and stale-process warning; the terminal header no longer includes a diagnostic status action that can write into the active TUI. Validation is project-aware, so generic Python folders run from their selected root instead of inheriting FZAstro-specific commands.

### Next-action workflow controls

The workflow now keeps one primary visible path: type directly in **Claude Terminal**. Session keeps setup and tools available without taking terminal space.


### OpenClaude session cleanup

Session is setup/status only and scrollable: workspace, provider/environment, Git API token storage state, git state, AGENTS.md, terminal frontend/backend readiness, and terminal running/stopped state. Patch/test/report controls from the old DEV testbed are not exposed in Session; normal work happens directly in the Claude Terminal. Dirty git checkouts are shown with a warning so live workspace changes are visible before using OpenClaude.

# AI Developer Workbench

This bundle adds the first production-safe foundation for a ChatGPT-style coding workflow inside FZAstro AI.

## Goal

The workbench turns a coding request into a structured workflow:

```text
request -> classify -> scan project -> select relevant files -> build context package -> create visible plan -> run checks -> prepare safe patch workflow
```

The first milestone is intentionally **preview-first**. It does not silently edit project files. It gives the app the backend and UI needed to inspect the project like a careful coding assistant before patches are applied.

## Added modules

```text
fzastro_ai/dev_agent/
  __init__.py
  project_scanner.py
  task_classifier.py
  context_builder.py
  dev_session.py
  error_analyzer.py
  patch_applier.py
  test_runner.py
  git_tools.py
  session_store.py

fzastro_ai/ui/dev_workbench_dialog.py
fzastro_ai/actions/dev_actions.py
```

## UI entry point

A new `DEV` button appears in the top skills bar. It opens the Developer Workbench window.

The window provides:

- project root selection
- project scanning
- developer request input
- relevant-file selection
- visible plan output
- context package output
- compile check runner
- pytest runner
- copy-plan and copy-context buttons

## Safety model

The backend includes `patch_applier.py`, but the UI does not auto-apply patches yet. Patch application should remain guarded by:

1. unified diff only
2. changed path extraction
3. rollback snapshot under `.fzastro_ai_patches/`
4. `git apply --check`
5. explicit user action

## Recommended next milestone

Add a second-stage `Generate Patch` button that sends the context package to the selected local/OpenAI-compatible model and asks for a unified diff only.

Then add:

```text
Preview Diff -> Apply Patch -> Run Checks -> Analyze Failure -> Generate Repair Patch
```

## Validation commands

```powershell
python -m compileall -q fzastro_ai tests
pytest -q tests/test_dev_agent_project_scanner.py tests/test_dev_agent_context_builder.py tests/test_dev_agent_patch_applier.py tests/test_dev_agent_error_analyzer.py
```

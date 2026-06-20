# FZAstro AI v2.4.0 - OpenClaude Terminal Production

Release tag: `v2.4.0`

## Summary

FZAstro AI v2.4.0 is a major OpenClaude release. The old experimental Developer Workbench / legacy DEV testbed has been removed from the normal UI and replaced by a dedicated OpenClaude workspace.

## Highlights

- Dedicated **OpenClaude** quick-action tab.
- Real embedded terminal-first OpenClaude workflow.
- Session panel shows workspace, model/endpoint, git branch/remote/dirty state, hidden API-key state, AGENTS.md status, and terminal frontend/backend status.
- Claude Terminal provides maximum terminal space with compact Start/Restart, Stop, Clear, and Status controls.
- OpenClaude uses the selected workspace directly and can inspect/create/edit files, run Python/tests/scripts, and interact with git according to the user prompt and project rules.
- FZAstro setup/deploy prepares OpenClaude prerequisites including Node/npm lookup, global OpenClaude install checks, pywinpty/ConPTY backend, and local xterm.js frontend assets.
- Help, About, README, validation docs, and release workflow now identify this as **OpenClaude Terminal Production**.

## Removed from the normal UI

- Legacy DEV scan/plan/ask controls.
- Timeline tab.
- Evidence and Advanced Diagnostics drawers.
- External Terminal button.
- Manual Input control.
- Mode/Safety controls from the legacy testbed.
- Separate Task/reply composer below the terminal.
- Bottom hard-boundary footer.

## Validation expectation

Before tagging/pushing, run:

```powershell
python -m compileall -q main.py fzastro_ai tests
python -m pytest -q tests/test_openclaude_bridge.py tests/test_openclaude_embedded_terminal.py tests/test_version_and_docs.py
```

Full deploy path:

```powershell
.\DEPLOY.bat
.\DEPLOY.bat -GitPush
```


### OpenClaude session cleanup

Session is setup/status only: workspace, provider/environment, git state, AGENTS.md, and terminal frontend/backend readiness. Patch/test/report controls from the old DEV testbed are not exposed in Session; normal work happens directly in the Claude Terminal. Dirty git checkouts are shown with a warning so live workspace changes are visible before using OpenClaude.

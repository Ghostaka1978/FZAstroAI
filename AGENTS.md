# FZAstro / OpenClaude Workspace Rules

- Inspect relevant files before editing.
- Prefer small, reviewable patches over broad rewrites.
- Do not modify unrelated files.
- Run appropriate validation after code changes when practical.
- For Python changes in FZAstro AI, prefer:
  - `python -m compileall -q main.py fzastro_ai tests`
  - `pytest -q` or the smallest relevant pytest target.
- Report concrete command output and remaining risks.
- Ask before destructive commands, deployment actions, or large refactors.
- Do not start astronomy hardware, N.I.N.A. sequences, guiding, capture, or power actions from this workspace.
- Use normal OpenClaude judgment for review, editing, tests, and git work unless the user gives stricter instructions.

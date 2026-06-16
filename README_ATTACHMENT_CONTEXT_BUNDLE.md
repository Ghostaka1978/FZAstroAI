# FZAstro AI Attachment Context Bundle

This bundle fixes the case where the UI shows an attached text/code file, but the local model replies as if no file was attached.

## What it changes

- Makes non-image attachments explicit in the model prompt.
- Adds metadata for filename, size, extracted characters, and extracted line count.
- Wraps code/text attachments in a clear `BEGIN ATTACHED FILE` / `END ATTACHED FILE` block.
- Keeps the legacy `Attached file:` marker so existing memory/history extraction still works.
- Adds compact recent-chat context to the system prompt so follow-up references like “last chat”, “above”, or “that file” are easier for local models to follow.
- Adds diagnostic logging: `MODEL ATTACHMENT CONTEXT count=..., files=..., chars=...`.

## Files changed

```text
fzastro_ai/file_tools.py
fzastro_ai/conversation_context.py
fzastro_ai/actions/web_news_actions.py
tests/test_file_tools.py
tests/test_conversation_context.py
```

## Apply

From your FZAstro AI source root:

```powershell
powershell -ExecutionPolicy Bypass -File "PATH_TO_BUNDLE\apply_attachment_context_bundle.ps1"
```

Or pass the source folder explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File "PATH_TO_BUNDLE\apply_attachment_context_bundle.ps1" -ProjectRoot "D:\Dropbox\AI"
```

## Validate

```powershell
.\.venv\Scripts\python.exe -m compileall -q fzastro_ai tests
.\.venv\Scripts\python.exe -m pytest -q tests\test_file_tools.py tests\test_conversation_context.py tests\test_startup_imports.py
```

## Test in the app

Launch from source:

```powershell
.\.venv\Scripts\python.exe main.py
```

Attach a `.py` file and ask:

```text
Inspect the attached Python file. Tell me the first function name and summarize what the file does. Do not rewrite it.
```

Expected result: the model should mention the file and analyze its actual code instead of saying no file was attached.

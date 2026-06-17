# FZAstro AI Option A UI + failure fixes patch

This bundle applies three changes together:

1. Option A UI polish: removes the permanent skills/top quick row from the main surface and moves skills/model/web controls into a bottom expandable Skills drawer.
2. Release validation doc cleanup: `docs/RELEASE_VALIDATION.md` becomes the canonical file, and tests/scripts stop requiring `RELEASE_VALIDATION.md` in project root.
3. Exit temp cleanup: known FZAstro-owned temp folders are removed best-effort on app shutdown.

## Apply with full-file copy

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\APPLY_OPTION_A_PATCH.ps1 -ProjectRoot "D:\Dropbox\AI"
```

Or copy the contents of `modified_files/` into the matching project paths and remove root `RELEASE_VALIDATION.md` manually.

## Apply as patch

The unified patch is also included as:

```text
fzastro_option_a_ui_temp_release_docs.patch
```

## Validate

```powershell
python -m pytest
```

The patch was validated in the sandbox with:

```text
195 passed, 5 skipped
```

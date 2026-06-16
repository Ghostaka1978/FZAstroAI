# FZAstro AI Developer Workbench Bundle

This bundle adds the first stage of an **AI Developer Workbench** to FZAstro AI.

## What it adds

- `DEV` button in the skills bar
- project scanner
- task classifier
- relevant-file context builder
- visible implementation-plan generator
- failure-output analyzer
- compile/pytest runner helpers
- safe patch snapshot primitives
- first-stage Developer Workbench UI
- regression tests for the backend modules
- documentation: `docs/AI_DEVELOPER_WORKBENCH.md`

## Recommended install

Copy or keep this bundle anywhere, then run this from your FZAstro AI project root:

```powershell
powershell -ExecutionPolicy Bypass -File "PATH_TO_BUNDLE\apply_dev_workbench_bundle.ps1"
```

The script uses:

```powershell
git apply --check
git apply
python -m compileall -q fzastro_ai tests
```

## If Git is unavailable

You can use the overlay fallback:

```powershell
powershell -ExecutionPolicy Bypass -File "PATH_TO_BUNDLE\apply_dev_workbench_bundle.ps1" -OverlayFallback
```

The fallback copies the `overlay/` tree into your project and creates backups under:

```text
.fzastro_ai_patches/dev_workbench_overlay_<timestamp>/backups/
```

Use the fallback only if your project still matches the uploaded RC3 state closely.

## Validation

After applying:

```powershell
python -m compileall -q fzastro_ai tests
python -m pytest -q tests/test_dev_agent_project_scanner.py tests/test_dev_agent_context_builder.py tests/test_dev_agent_patch_applier.py tests/test_dev_agent_error_analyzer.py
```

## Current scope

This is milestone 1: scan, classify, build context, plan, and run checks.

It does **not** yet auto-generate or auto-apply patches from the model. That should be milestone 2:

```text
Generate Patch -> Preview Diff -> Apply Patch -> Run Checks -> Repair Failure
```

# FZAstro AI TARGETS native window + OpenNGC-ready catalog patch

This patch moves TARGETS out of the main chat path and into a native PySide6 planner window, matching the newer Astro tool pattern.

## What it adds

- `fzastro_ai/ui/targets_dialog.py`
  - Native TARGETS dialog
  - Date, minimum altitude, limit, catalog source, object type, minimum size, optional max magnitude filters
  - Results table, target detail panel, Open in LOOKUP, copy name, CSV export
  - OpenNGC CSV import button

- `fzastro_ai/workers/targets_worker.py`
  - Runs target planning away from the Qt UI thread

- `fzastro_ai/astro_tools/target_catalog.py`
  - Local SQLite catalog at app data path: `target_catalog.sqlite3`
  - Seeds the existing curated target list
  - Imports OpenNGC-style CSV files as a local catalog source

- `fzastro_ai/astro_tools/target_planner.py`
  - Structured planner API around the existing `fzastro/target.py` scoring logic
  - Returns dictionaries for the UI instead of terminal text

- Updates `astro_actions.py`
  - TARGETS button opens the native dialog
  - `/targets` opens the native dialog too

- Updates README/help/release validation notes

## Apply

From your project root:

```powershell
patch -p1 < .\fzastro_targets_native_openngc.patch
```

If Git for Windows is installed, `patch.exe` is usually available from Git Bash. Alternative:

```powershell
git apply .\fzastro_targets_native_openngc.patch
```

## Validate

```powershell
python -m py_compile fzastro_ai\astro_tools\target_catalog.py fzastro_ai\astro_tools\target_planner.py fzastro_ai\workers\targets_worker.py fzastro_ai\ui\targets_dialog.py fzastro_ai\actions\astro_actions.py fzastro_ai\workers\__init__.py
python -m pytest
```

Manual app check:

1. Launch FZAstro AI.
2. Click **TARGETS**.
3. Confirm it opens its own window and does not post the planner table into main chat.
4. Run default planner.
5. Test filters: date, min altitude, object type, source, min size.
6. Select a target and click **Open in LOOKUP**.
7. Export CSV.
8. Optional: import an OpenNGC CSV and re-run with `Auto local catalog` or `OpenNGC only`.

## OpenNGC use

The patch does not commit a giant OpenNGC data dump into the repo. It provides a local importer so the app can bundle/use OpenNGC only for TARGETS without affecting LOOKUP, SEEING, SOLAR MAP, or other Astro tools.

Recommended flow:

1. Download OpenNGC CSV separately.
2. Open TARGETS.
3. Click **Import OpenNGC CSV**.
4. The imported objects are cached locally in the app data SQLite catalog.


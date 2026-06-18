# FZAstro Imaging / N.I.N.A. Bundle Integration

FZAstro AI treats the N.I.N.A.-based imaging application as a side-by-side bundled app instead of requiring a separate N.I.N.A. installation or merging C# source into the Python package.

This document covers the **v2.3.1 Imaging Production** workflow: launch the bundled app, build it quietly from source, create safe review-only imaging plans from Astro context, and attempt to open generated Advanced Sequencer plans for user review.

## Bundle identity rule

Keep the branding thin:

```text
FZAstroImaging.exe  = branded launcher filename
NINA.exe            = preserved internal apphost
NINA.dll            = preserved internal WPF assembly
```

Do not rename the internal WPF assembly to `FZAstroImaging`. N.I.N.A. XAML/resource references expect the internal assembly name `NINA`, and startup can fail if `NINA.dll` is missing.

## First-stage launcher behavior

- Adds a top-bar **N.I.N.A.** / imaging-control entry.
- Opens a dedicated **FZASTRO IMAGING CONTROL** window.
- Stores the executable path in `AppData/Roaming/FZAstroAI/nina_integration.json`.
- Launches `bundled_apps/FZAstroImaging/FZAstroImaging.exe`.
- Does not search `Program Files` for a separately installed N.I.N.A. copy.
- Checks a configured update feed automatically when the panel opens.
- Downloads update packages into `AppData/Roaming/FZAstroAI/downloads/fzastro_imaging`.
- Does not overwrite the imaging executable while an equipment session may be running.

## Build the bundled imaging app

Do not install external N.I.N.A. for the FZAstro bundle workflow. Use the source N.I.N.A. tree as build input and produce a local bundled runtime:

```powershell
.\scripts\prepare_fzastro_imaging_bundle.ps1 -NinaSourceDir .\external\nina -AutoInstallDotNetSdk
```

Or as part of deployment:

```powershell
.\scripts\deploy.ps1 -BuildImagingBundle -NinaSourceDir .\external\nina -AutoInstallDotNetSdk
```

The build workflow should:

- run quietly with a progress bar,
- write detailed dotnet logs under `..\FZAstroAI_BUILD\logs`,
- build with .NET 10 on Windows,
- find output under `NINA\bin\Release\net10.0-windows\win-x64`,
- copy the full runtime folder to `bundled_apps\FZAstroImaging`,
- verify `FZAstroImaging.exe`, `NINA.exe`, and `NINA.dll`.

Some N.I.N.A. source archives do not include optional vendor-native DLLs such as Altair or AllPro binaries. Device support that depends on a missing vendor DLL requires that DLL to be present in the source bundle.

## Safe predefined imaging-plan commands

FZAstro AI can create review-only imaging plans from predefined commands. These commands combine the current Astro SITE settings, current IMAGING profile, SEEING forecast rows, and TARGETS planner picks.

Supported commands include:

```text
/nina-plan next
/nina-plan next 60s gain 200
/nina-plan target M13 60s gain 200
/imaging-plan target NGC 7000 exposure 120s gain 100 frames 80
```

Natural safe aliases such as `what target should I image next` and `make a NINA plan for best target` are routed to the same review-only workflow.

## Plan output location

Generated plans are stored in a visible documents folder:

```text
Documents\FZAstroAI\Imaging Plans\<plan_id>\
```

Each plan includes:

- `<plan>.nina-sequence.json` — real N.I.N.A. Advanced Sequencer JSON filled from the bundled OSC template
- `<plan>.nina-plan.xml` — review/helper XML
- `<plan>.nina-target.csv` — target/sequence review helper
- `<plan>.nina-review.json` — FZAstro review metadata
- `<plan>.json` — FZAstro internal metadata
- `<plan>.md` — readable summary

The file to open/import in N.I.N.A. Advanced Sequencer is:

```text
<plan>.nina-sequence.json
```

If a file picker hides the custom extension, use **All files** or copy the sequence JSON content into a `.json` filename.

## Real Advanced Sequencer template

FZAstro fills a real N.I.N.A. Advanced Sequencer JSON structure from:

```text
fzastro_ai/resources/nina_templates/osc_advanced_sequence_template.json
```

Fields filled by FZAstro include:

- target name,
- target RA/Dec,
- start time,
- end/loop-until time,
- exposure seconds,
- gain,
- frame count,
- repeated coordinate blocks used by center/platesolve, horizon, and drift logic.

## Auto-launch/open handoff

After creating a plan, FZAstro can launch the bundled imaging app and attempt to open the generated `.nina-sequence.json` for review.

This is a handoff only. FZAstro does not start sequence execution.

## Safety boundary

This stage does **not**:

- slew,
- center,
- start guiding,
- run autofocus,
- start capture,
- start a sequence,
- schedule automatic hardware execution.

Even if a user says “start automatically,” FZAstro records that intent in the plan and keeps the output review-only.

## Planning buttons

The bundled imaging control panel includes a polished safe Planning section with uppercase actions:

- **PLAN NEXT TARGET** — creates a review-only plan for the next best practical target using default 60s / gain 200 settings.
- **PLAN SPECIFIC TARGET** — asks for target, exposure, and gain, then creates a review-only plan.
- **OPEN LATEST PLAN IN IMAGING** — launches FZAstro Imaging and attempts to open the latest generated `.nina-sequence.json`.
- **OPEN PLANS FOLDER** — opens generated plan folders.
- **COMMAND HELP** — shows supported `/nina-plan` command syntax.

The same actions are exposed from the **ASTRO** skill menu so users do not need to type slash commands manually.

## Update feed format

The updater accepts either a GitHub latest-release API response or a small JSON manifest:

```json
{
  "version": "3.2.1-fzastro.1",
  "download_url": "https://example.com/FZAstroImaging-3.2.1.zip",
  "sha256": "optional checksum",
  "release_notes": "Optional notes",
  "published_at": "2026-06-17"
}
```

`auto_check_updates` is enabled by default, but no feed URL is hardcoded. This keeps the update channel under FZAstro control and avoids silently pulling the wrong upstream build.

## Bundle update rule

FZAstro AI may check and download FZAstro Imaging bundle updates automatically, but installation/replacement should remain a reviewable step:

1. Close the imaging app.
2. Back up the previous bundled folder.
3. Install or extract the downloaded update.
4. Reopen FZAstro AI and launch the imaging app.

This preserves safety for cameras, mounts, focusers, filter wheels, and active sequences.

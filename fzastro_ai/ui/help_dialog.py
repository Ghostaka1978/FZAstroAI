import html

import markdown
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..logging_utils import log_exception


HELP_CHEAT_SHEET_MARKDOWN = r"""# FZAstro AI v1.0.0 RC 3 Final Production Help

This guide shows the exact things you can ask FZAstro AI to do and which mode/source should be used. Version 1 RC 3 Final Production is the final production release-candidate baseline for the Windows desktop app. Click the **FZ** square in the header to open the project GitHub repository in your external browser.

## 1. RC 3 Final Production status

FZAstro AI v1.0.0 RC 3 Final Production is the Windows desktop release baseline for local AI chat, document research, web research, Python execution, persistent memory, LLM benchmarking, and the integrated Astro Tools Suite. Before distributing a build, run the automated tests and the release validation checklist.

```powershell
python -m pytest
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```

## 2. The main idea

FZAstro AI can answer from different places:

| Source chip | Meaning |
|---|---|
| **LLM** | The selected local model answered from its own reasoning and current prompt context. |
| **Docs** | The answer used your imported Document Knowledge Library. |
| **App** | The app handled the request directly, without needing the model to rewrite it. |
| **Web** | The answer used internet search or webpage extraction. |
| **News** | The answer came from the news workflow. |
| **Market** | The answer came from a structured market quote. |
| **Memory** | The answer used saved persistent memory. |
| **Files** | The answer used an attached file. |
| **Vision** | An image-capable model inspected an image. |
| **Python** | Local Python code was executed and returned stdout/stderr. |

Good rule:

```text
Ask normally for model knowledge.
Mention my documents / PDF title / page number for local documents.
Mention web / latest / current / URL for internet work.
Mention remember / memory for persistent memory.
Mention run / test / execute for Python.
```

## 3. Normal chat

Use normal chat for explanations, reasoning, coding help, astrophotography questions, planning, and writing.

```text
Explain dithering in astrophotography.
Help me debug this Python error.
Compare OSC and mono cameras for deep-sky imaging.
Create a simple imaging checklist for tonight.
```

Expected source chip:

```text
LLM
```

## 4. Choosing models

Use the model selector near the chat controls to choose the active local model. Use the refresh button beside it after adding or deleting Ollama models. If the default local Ollama endpoint is selected and Ollama is installed but stopped, FZAstro AI tries to start `ollama serve` automatically. If Ollama cannot be reached, the selector shows an `Ollama unavailable` status item. Auto-started Ollama is left running on exit by default; set `FZASTRO_STOP_OLLAMA_ON_EXIT=1` to stop only the Ollama process started by FZAstro AI.

The status line can show:

```text
active model • response time • output size • context left • token speed
```

The lower hardware row can show GPU/VRAM, CPU and RAM. GPU temperature is shown when `nvidia-smi` reports it. CPU temperature is best-effort and may be unavailable on Windows unless a sensor provider exposes it.

Example:

```text
ai-12b:latest • 6.6s • out ~371 tok • ctx left ~28.2k/32.8k • ~55.7 tok/s
```

Meaning:

| Status item | Meaning |
|---|---|
| `out ~371 tok` | Estimated generated output tokens. |
| `ctx left` | Estimated remaining context window. |
| `32.8k` | Active model context size. |
| `tok/s` | Estimated generation speed. |

## 5. Web search

Use web search when you need current information, recent events, current prices, or internet results.

```text
Search the web for latest Artemis news.
Find recent news about NASA and SpaceX.
What is the latest price of gold?
Get the current CRM stock price.
```

Expected source chip:

```text
Web
```

## 6. Daily news

Use the Daily News button for a quick news brief. You can also ask directly:

```text
Give me the daily news brief.
Give me astronomy and space news today.
Give me the latest science and technology headlines.
```

Expected source chip:

```text
News
```

## 7. Market buttons

Use the market quick buttons for structured quotes such as CRM, DBX, crude oil, or gold.

You can also ask:

```text
Get CRM stock price.
Get DBX stock price.
Get crude oil price.
Get gold price.
```

Expected source chip:

```text
Market
```

## 8. Read a webpage

Use this when you want text from one real webpage.

```text
Read this page: https://www.nasa.gov/blogs/artemis/
Give me the visible text from https://www.nasa.gov/blogs/artemis/
Extract the page text from https://www.nasa.gov/blogs/artemis/
```

Expected source chip:

```text
Web
```

## 9. Summarize or analyze a webpage

Use this when you want the app to open a URL, extract the rendered page text, and then ask the model to work on it.

```text
Summarize this article: https://www.nasa.gov/blogs/artemis/
Analyze this webpage: https://www.nasa.gov/blogs/artemis/
Give me the important points from https://www.nasa.gov/blogs/artemis/
Extract the main claims from this page: https://www.nasa.gov/blogs/artemis/
```

Expected source chips:

```text
Web + LLM
```

## 10. Website screenshot

Use this when you want the visual webpage, not extracted text.

```text
Take screenshot https://www.nasa.gov/blogs/artemis/
Screenshot this page: https://www.nasa.gov/blogs/artemis/
Capture website screenshot of https://www.nasa.gov/blogs/artemis/
```

Expected source chip:

```text
Web
```

## 11. Extract images, links, and tables from a webpage

Use this when you want page assets or page structure.

```text
Extract images from https://www.nasa.gov/blogs/artemis/
Extract all links from https://www.nasa.gov/blogs/artemis/
Extract tables from https://www.nasa.gov/blogs/artemis/
Extract images, links, and tables from https://www.nasa.gov/blogs/artemis/
```

Expected source chip:

```text
Web
```

## 12. Web image search

Use this when the image should come from the internet.

```text
Find a web image of M31.
Show me an actual astrophotography image of M82 from the web.
Find an image of the Orion Nebula from the internet.
```

Important wording:

```text
web image / from the internet = internet image search
PDF page image / from my document = local document image
```

Expected source chip:

```text
Web
```

## 13. Attach files to chat

Use attachments for small files you want the model to read directly.

```text
Attach a Python file and ask: explain this file.
Attach a small text file and ask: summarize this.
Attach an image and ask: analyze this image.
```

Expected source chips can include:

```text
Files
Vision
LLM
```

For large PDFs/books, use the Document Knowledge Library instead of normal attachment chat.


## Composer toolbar

Use the toolbar above the message box to prepare pasted technical content before sending.

```text
Code Lab   Code composer tools, Python runner actions, review, tests, patches, and commit messages.
Add        Paste code, attach files, import documents, or inspect active context.
Skills     Open all grouped skill menus from the composer.
Knowledge  Document library, document search, PDF/book reader, and persistent memory tools.
Model Lab  Model refresh, benchmark, persona/calibration, runtime status, and memory tools.
Clear      Clear the input box and pending attachments.
```

Skills currently includes:

```text
Research: Daily News, Read page, Summarize page, Screenshot page
Knowledge: Document Library, Search knowledge, Brief/Open/Ask document, Memory, Active context
Code Lab: Paste/wrap code, Run input/selection, Explain, Debug, Refactor, Tests, Patch, Commit message
Astro: SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, SOLAR MAP, distance-ladder lookup details
Markets: CRM, DBX, OIL, GOLD
Model Lab: Refresh models, LLM Benchmark, Runtime status, Persona, System Prompt Editor
Workspace: New chat, History, Active context, Diagnostics, Help, About, GitHub repository
```

Prompt actions are inserted into the composer and are not sent automatically. Use **Code Lab** or **Add → Paste code** for Python, logs, JSON, shell commands, tracebacks, and config files. Python Run actions execute through the existing local Python runner.

## Offline voice commands

Use the **Voice** button beside the composer for local push-to-talk commands. This feature uses optional Vosk + sounddevice packages and does not send microphone audio to a cloud service.

```text
open seeing
show targets
solar map
sun now
site settings
imaging settings
open help
model benchmark
lookup M31
lookup Andromeda
lookup North America Nebula
```

Safe UI-opening commands execute immediately. Uncertain speech is inserted into the composer for review instead of being sent.

Setup:

```powershell
.\.venv\Scripts\python.exe -m pip install vosk sounddevice
```

Extract a Vosk model to `%APPDATA%\FZAstroAIoice_models\` or set `FZASTRO_VOSK_MODEL` to the extracted model folder.

## 14. Document Knowledge Library

Use the Document Knowledge Library for imported PDFs, books, notes, manuals, and technical documents.

```text
What does The Astrophotography Manual say about choosing equipment?
Search my knowledge documents for polar alignment.
Find pages about image calibration.
What does my document library say about dithering?
```

Expected source chip:

```text
Docs
```

## 15. Import documents

Use the Document Knowledge Library window to import documents. During import, the app can show:

```text
Imported documents
Updated documents
Extracted text
Searchable chunks
Rendered PDF visual pages
OCR warnings
```

When you click **Clear Library**, FZAstro removes indexed rows, clears document assets, then compacts `document_knowledge.sqlite3` and its WAL storage so disk usage shrinks instead of only marking SQLite pages free.

OCR note:

```text
Normal PDF text can be indexed without OCR.
OCR is mainly needed for scanned pages or text trapped inside images.
```

## 16. Exact PDF page text

Use this when you want the text from one exact PDF page.

```text
Give me all the text from page 271 from The Astrophotography Manual.
Extract exact text from page 40 of The Astrophotography Manual.
Give me the text only from page 12 of this PDF.
```

Expected source chips:

```text
App + Docs
```

## 17. PDF page image

Use this when you want the real rendered PDF page image.

```text
Give me the image from page 270 from The Astrophotography Manual.
Show page 40 as an image.
Render page 98 from this PDF.
```

Expected source chips:

```text
App + Docs
```

## 18. PDF page image plus text

Use this when you want both the rendered page and extracted text.

```text
Give me the image and the text from page 270 from The Astrophotography Manual.
Show page 40 as an image and extract the text.
Render page 98 and give me the page text.
```

Expected source chips:

```text
App + Docs
```

## 19. Search matching PDF pages as images

Use this when you want the app to search your local documents and display matching pages as images.

```text
Search The 100 Best Targets for Astrophotography.pdf and display as images the M82 galaxy.
Find pages about M31 in The 100 Best Targets for Astrophotography.pdf and show them as images.
Search my document library for polar alignment and display matching pages as images.
```

Expected source chips:

```text
App + Docs
```

## 20. Crop an embedded PDF image

Use this when you want only the photo or figure from inside a PDF page, not the full page.

```text
Find M82 in The 100 Best Targets for Astrophotography.pdf and crop only the galaxy photo.
Search The 100 Best Targets for Astrophotography.pdf and show the actual embedded image of M82, not the full page.
Find the page with M31 and display only the galaxy image crop.
```

If the app cannot find a reliable crop, it may fall back to the full rendered PDF page.

Expected source chips:

```text
App + Docs
```

## 21. Avoid web/document confusion

Use this wording when you want a local PDF result:

```text
from my document
from my knowledge library
from page 270
from The Astrophotography Manual PDF
show the PDF page image
render the PDF page
```

Use this wording when you want an internet result:

```text
from the web
from the internet
latest
current
search online
web image
```

If you ask for a local PDF page and see `Web`, rephrase with the PDF title and page number.

## 22. Persistent memory

Use memory for durable notes, project facts, preferences, telescope setups, procedures, and decisions.

```text
Remember this project note.
Save this to persistent memory.
Search persistent memory for my telescope setup.
What do you remember about my imaging workflow?
```

Expected source chip:

```text
Memory
```

## 23. Memory review

Use the memory review tools to inspect, clean, or reuse saved memory items.

```text
Open persistent memory.
Search memory for calibration.
Delete this memory entry.
Remember selected history items.
```

## 24. Chat history

Use history when you want to reload, review, clean, or reuse previous chats.

```text
Open chat history.
Reload this chat.
Delete this response before saving.
Save this chat to history.
```

## 25. Run Python from a code block

When a Python code block appears in chat, use the **Run** button beside **Copy code**.

```text
Ask: Write a Python script that lists all FITS files in a folder.
Then: click Run on the Python code block.
```

Expected source chip after execution:

```text
Python
```

## 26. Run Python from the input box

Paste code after one of these commands:

```text
/run-python
print("hello from FZAstro AI")
```

```text
/run-py
print(2 + 2)
```

```text
/py
for i in range(3):
    print(i)
```

The result card shows:

```text
Status: Completed / Failed / Timed out / Stopped
Exit code: 0 means success
Elapsed: runtime in seconds
Output: stdout from print statements
Errors: stderr and tracebacks
```

## 27. Ask the app to generate and test Python

Use clear wording when you want the model to write code and the app to run it.

```text
Write a Python script and test it.
Generate a small Python example and run it.
Create a factorial function and check the output.
Give me 10 lines of Python code and test that it works.
```

The model should produce one runnable Python block. The app then executes it and posts the real Python result separately.

Safety note:

```text
The Python runner is local subprocess execution, not a secure sandbox.
Only run code you trust.
```

## 28. Astro Tools Suite — production astronomy workspace

Use **Skills → Astro** for the RC 3 Astro Tools Suite. These tools are integrated production app windows, not loose helper scripts.

```text
Skills   Astro   SITE   IMAGING   LOOKUP   SUN NOW   SEEING   TARGETS   SOLAR MAP
```

| Button | What it does |
|---|---|
| **SITE** | Pick/save observing latitude, longitude, elevation, timezone, and optional SQM/Bortle sky-quality values for SEEING and TARGETS. |
| **IMAGING** | Select camera preset, focal length, calculated FOV, image size, and rotation for LOOKUP images. |
| **LOOKUP** | Open a compact object lookup window for M31, NGC 7000, IC 5146, planets, comets, stars, spacecraft, nebulae, and galaxies. Result text, distance details, and sky preview render in the LOOKUP window. |
| **SUN NOW** | Show latest NASA/SDO solar images with channel/size selectors, Helioviewer closest-image metadata, and cached fallback. |
| **SEEING** | Open the Astro Night Planner: daily forecast cards, current local day/time context, 7Timer ASTRO seeing/transparency, cloud gauges, Moon periods, astronomical darkness, night-first forecast points, cloud-aware nightly scoring, and SQM/Bortle sky quality. |
| **TARGETS** | Open the native target-planner window with date, altitude, object-type, size, catalog-source, CSV export, and optional OpenNGC CSV import. |
| **SOLAR MAP** | Open the native 2D interactive solar-system map with zoom, pan, Full/Inner/Outer modes, orbit/label/grid toggles, and planet data. |

LOOKUP uses the selected **IMAGING** setup, so choose your camera preset and focal length before running object lookup when you want the sky image framed correctly. LOOKUP runs as its own dialog and does not need the main chat to display the object result.

SEEING uses the saved **SITE** location. SQM/Bortle can come from manual SITE values or a successful automatic LightPollutionMap.app lookup; when no reliable source is available, SEEING should show the value as not set rather than inventing one. The SEEING top bar tints by Bortle class: 8–9 white/urban, 6–7 yellow, 4–5 green, 2–3 blue, and 1 violet.


### Distance ladder calculations

LOOKUP also exposes the distance calculation path instead of only showing a final distance. When data is available, the distance block can identify whether the value came from direct parallax, Gaia-based fallback estimates, redshift-independent NED-D galaxy distances, or a conservative Hubble-law estimate from redshift/radial velocity.

This is a practical astronomy helper for transparency inside the app. It is not meant to replace catalogue data or professional distance-measurement pipelines. To force strict fast Sesame/SIMBAD lookup behavior, set `FZASTRO_USE_DISTANCE_LADDER=0`.

The LOOKUP dialog includes the migrated FZASTRO object dropdown catalogs:

```text
Planets/Sun · Moons · Comets · Spacecraft
Brightest Stars · Famous Nebulae · Messier Catalog · Virgo Supercluster Members
Closest Stars · Famous Galaxies · Local Group Galaxies · Local Superclusters
```

Examples:

```text
/astro M31
/astro NGC 7000
/astro IC 5146
/astro-image 10.6847 41.269
/see
/targets
/solar-map
```

Manual SEEING validation: open SEEING, confirm daily forecast cards are visible, the top bar shows the current local day/time and relevant current/tonight night window, Forecast Points prioritize night/imaging rows, cloud cover affects nightly scores, Moon and astronomical-dark periods are visible, the Bortle tint matches SITE values, and selecting a forecast point updates the selected-hour card.

Expected source chips/source labels:

```text
App + Astro API
Source: Migrated FZASTRO LOOKUP tool.
```

## 29. LLM Benchmark Dashboard

Use **Skills → Model Lab → LLM Benchmark** when you want to measure model accuracy, speed, trust, and compare local/Ollama/OpenAI-compatible endpoints. The dashboard uses the current app endpoint, mirrors the main app model-list behavior, auto-refreshes its model selector, keeps the local list if refresh fails, includes **Refresh Models** and **Use Active Model**, mirrors the main GPU/VRAM and CPU/RAM telemetry, lets you select Raw model or a persona/calibration profile, and keeps benchmark controls readable.

```text
Skills -> Model Lab -> LLM Benchmark -> choose model -> choose Raw model/persona -> choose benchmark preset -> Run Selected
```

The dashboard has three tabs; benchmark controls, preset selection, custom prompt entry, and live telemetry stay in the shared top panel:

| Tab | What it shows |
|---|---|
| **Dashboard** | Total runs, tested models, average accuracy, average trust, average speed, latency, stability, and generation time. |
| **History** | Saved benchmark runs from `llm_benchmark_history.json`, with **Delete Selected**, Delete key, and right-click deletion for removing individual records. |
| **Compare** | Per-model + persona comparison by preset coverage, accuracy, speed, trust, instruction following, stability, composite score, tokens/sec, and latency. |

Built-in presets include:

```text
Quick Q&A (short)
Math Reasoning
Code Generation
Creative Writing
Logical Reasoning
Data Analysis
Translation & Multilingual
Summarization
Instruction Following
```

Metrics meaning:

| Metric | Meaning |
|---|---|
| **Tokens/sec** | Estimated completion-token generation throughput. |
| **Time to first token** | Streaming latency before the first generated token arrives. |
| **Total time** | Full request runtime. |
| **Generation time** | Time spent after the first token starts arriving. |
| **Input tokens** | Estimated user prompt plus selected persona/system-prompt token count. |
| **Completion tokens** | Estimated generated output token count. |

For fair comparisons, use the same preset, persona/calibration, temperature, endpoint, repeat count, and background GPU load for each model; the telemetry row helps you spot background load while testing. Deterministic grader rows show why a score passed or failed, while the trust score rewards auditable runs with raw prompt/response evidence and repeat metadata. Raw model mode gives the cleanest speed baseline; a selected persona/profile measures how the app's system prompt changes quality, latency, and output length. **Run Selected** tests the visible preset or custom prompt. **Run All Presets** executes the full built-in suite in one pass and stores each preset separately in History. Select models directly from the benchmark window; use **Use Active Model** when you want to return to the main app's selected model. Use **Delete Selected**, Delete, or right-click to remove individual saved rows, **Export JSON** to save a copy of the benchmark history, or **Clear History** to reset all local benchmark results.

## 30. Stop a running task

Use **Stop** when a model reply, web task, memory extraction, document import, or Python execution is taking too long.

```text
Stop = interrupt the active process when supported.
```

## 31. Good prompt patterns

For documents:

```text
Search my knowledge documents for [topic].
Give me exact text from page [number] of [PDF title].
Show page [number] of [PDF title] as an image.
Give me the image and text from page [number] of [PDF title].
```

For web:

```text
Search the web for [topic].
Read this page: [URL].
Summarize this article: [URL].
Take screenshot [URL].
```

For memory:

```text
Remember this: [note].
Search memory for [topic].
What do you remember about [topic]?
```

For Python:

```text
Write Python code for [task] and test it.
/run-python
[code]
```

## 32. Quick troubleshooting

| Problem | What to try |
|---|---|
| Local PDF request goes to web | Include the PDF title, page number, and words like `from my document` or `PDF page image`. |
| Model is slow | Choose a smaller model, reduce context, run LLM BENCH for baseline throughput, or stop the current reply. |
| No models appear | If Ollama is installed, press refresh beside the model selector; the app can auto-start local Ollama. If the selector says `Ollama unavailable`, install/start Ollama or check `FZASTRO_AUTO_START_OLLAMA`. In LLM BENCH, use **Refresh Models** after changing endpoints or downloading models. |
| Ollama stays running after exit | This is the safe default. Set `FZASTRO_STOP_OLLAMA_ON_EXIT=1` to stop only an Ollama process launched by FZAstro AI. |
| Webpage text is poor | Try screenshot mode or ask for rendered webpage extraction. |
| PDF text is missing | The page may be scanned; OCR may be needed. |
| Python does not run in EXE | Set `FZASTRO_PYTHON` to a real Python interpreter path. |
| Answer source is unclear | Check the source chips above the answer. |

## 33. Fast cheat sheet

```text
Normal answer: ask normally.
Current info: say web/latest/current.
One URL: say read/summarize/analyze this URL.
Website visual: say screenshot URL.
Internet image: say web image/from internet.
Local PDF answer: say from my documents/PDF title.
Exact PDF text: say text from page number.
PDF visual page: say image/render page number.
PDF text + visual: say image and text from page number.
Memory: say remember/search memory.
Python: say run/test/execute or use /run-python.
Benchmark speed/quality: click LLM BENCH, choose a model directly in the dialog or refresh the model list, choose Raw model or a persona/calibration profile, then Run Selected or Run All Presets.
Astro distance path: use Skills -> Astro -> LOOKUP and check the distance method line for parallax, Gaia proxy, NED-D, or Hubble-law style estimates where available.
```
"""

from .window_utils import apply_window_defaults


def open_help_cheat_sheet_dialog(parent):
    """Open the built-in routing and prompt cheat sheet."""
    dialog = QDialog(parent)
    apply_window_defaults(dialog)
    dialog.setObjectName("helpDialog")
    dialog.setWindowTitle("FZAstro AI v1.0.0 RC 3 Final Production Help")
    dialog.resize(900, 760)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("FZAstro AI v1.0.0 RC 3 Final Production Help")
    title.setObjectName("helpDialogTitle")

    subtitle = QLabel(
        "RC 3 Final Production guide for chat, models, web, news, market quotes, documents, "
        "PDF page images/text, memory, history, attachments, Python execution, LLM benchmarking, tests, the Astro Tools Suite, and distance-ladder lookup details."
    )
    subtitle.setObjectName("helpDialogSubtitle")
    subtitle.setWordWrap(True)

    help_view = QTextBrowser()
    help_view.setObjectName("helpCheatSheetBrowser")
    help_view.setOpenExternalLinks(True)
    help_view.setReadOnly(True)

    try:
        help_html = markdown.markdown(
            HELP_CHEAT_SHEET_MARKDOWN,
            extensions=["fenced_code", "tables", "sane_lists"],
        )
    except Exception as exc:
        log_exception("open_help_cheat_sheet_dialog", exc)
        help_html = html.escape(HELP_CHEAT_SHEET_MARKDOWN).replace("\n", "<br>")

    help_view.setHtml(help_html)

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 0, 0, 0)
    button_row.setSpacing(8)

    copy_button = QPushButton("Copy Cheat Sheet")
    copy_button.setObjectName("primaryActionButton")
    copy_button.setToolTip("Copy the full cheat sheet as Markdown text")

    close_button = QPushButton("Close")
    close_button.setToolTip("Close help")

    def copy_cheat_sheet():
        QApplication.clipboard().setText(HELP_CHEAT_SHEET_MARKDOWN.strip())
        copy_button.setText("Copied")
        QTimer.singleShot(1600, lambda: copy_button.setText("Copy Cheat Sheet"))

    copy_button.clicked.connect(copy_cheat_sheet)
    close_button.clicked.connect(dialog.accept)

    button_row.addStretch(1)
    button_row.addWidget(copy_button)
    button_row.addWidget(close_button)

    layout.addWidget(title)
    layout.addWidget(subtitle)
    layout.addWidget(help_view, 1)
    layout.addLayout(button_row)

    dialog.exec()

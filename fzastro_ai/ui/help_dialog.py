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


HELP_CHEAT_SHEET_MARKDOWN = r"""# FZAstro AI v2.0.0 Help

This guide shows what FZAstro AI can do and which source/mode is usually used. Version 2 Production is the cleaned production baseline with the integrated Astro Tools Suite, Web Companion, LLM Benchmark Dashboard, and AI Developer Workbench. Click the **FZ** square in the header to open the GitHub repository.

## 1. Main idea

| Source chip | Meaning |
|---|---|
| **LLM** | The selected model answered from prompt/model reasoning. |
| **Docs** | The answer used the local Document Knowledge Library. |
| **App** | The app handled the request directly. |
| **Web** | The answer used internet search or webpage extraction. |
| **News** | The answer came from the Daily News workflow. |
| **Market** | The answer came from a structured market quote. |
| **Memory** | The answer used saved persistent memory. |
| **Files** | The answer used attached files. |
| **Vision** | An image-capable model inspected an image. |
| **Python** | Local Python code executed and returned output. |

Good rule:

```text
Ask normally for model knowledge.
Mention documents / PDF title / page number for local library work.
Mention web / latest / current / URL for internet work.
Mention remember / memory for persistent memory.
Mention run / test / execute for Python.
Use DEV for project scanning, coding context, plans, and checks.
```

## 2. Normal chat

```text
Explain dithering in astrophotography.
Help me debug this Python error.
Compare OSC and mono cameras for deep-sky imaging.
Create a simple imaging checklist for tonight.
```

Expected source chip: `LLM`.

## 3. Models and telemetry

Use the model selector near the chat controls to choose the active local model. Use refresh after adding/removing Ollama models. If Ollama is installed but stopped on the default local endpoint, FZAstro AI can try to start `ollama serve` automatically.

The status line can show model name, response time, output size, context left, and token speed. The lower telemetry row can show GPU/VRAM, CPU, RAM, and best-effort temperatures.

## 4. Web, news, and market

```text
Search the web for latest Artemis news.
Read this page: https://www.nasa.gov/blogs/artemis/
Summarize this article: https://www.nasa.gov/blogs/artemis/
Take screenshot https://www.nasa.gov/blogs/artemis/
Give me the daily news brief.
Get CRM stock price.
Get crude oil price.
Get gold price.
```

Expected source chips: `Web`, `News`, or `Market`.

## 5. Documents and files

Use attachments for small files you want the model to inspect directly. Use the Document Knowledge Library for large PDFs/books or long-term document search.

```text
Analyze this attached Python file.
Import this PDF into the knowledge library.
Search my documents for telescope collimation.
Show page 12 from the PDF.
```

Expected source chips: `Files`, `Docs`, `Vision`, and/or `LLM`.

## 6. Python and Code Lab

Use Code Lab or ask directly:

```text
Run this Python code.
Test this function with three cases.
Explain this traceback.
Create a pytest for this module.
```

Expected source chip: `Python` when code is executed.

## 7. LLM Benchmark Dashboard

Open **Skills → Model Lab → LLM Benchmark**. The legacy `LLM BENCH` wording remains documented for validation continuity.

The dashboard includes telemetry, Dashboard/History/Compare views, persona/calibration controls, Composite scoring, `Run All Presets`, and `Delete Selected`.

## 8. Astro Tools Suite

Use **Skills → Astro** or the Astro toolbar. The production tools are:

`SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP`

- **SITE** — observing location, elevation, timezone, SQM, and Bortle context.
- **IMAGING** — camera preset, focal length, FOV, image size, and rotation.
- **LOOKUP** — object lookup with catalog details, sky preview, and distance-ladder information.
- **SUN NOW** — NASA/SDO solar imagery with metadata and cached fallback.
- **SEEING** — Astro Night Planner with current/tonight context, astronomical-dark priority, Moon periods, cloud-aware scoring, and Bortle tint.
- **TARGETS** — target ranking, filters, CSV export, and optional local OpenNGC import.
- **SOLAR MAP** — native 2D solar-system map with orbit/label/grid controls.

Bortle tint rules: `8–9 white/urban`, `6–7 yellow`, `4–5 green`, `2–3 blue`, and `1 violet`.

Distance ladder calculations can use parallax, Gaia proxy, NED-D, and Hubble-style estimates where available. Optional visibility: `FZASTRO_USE_DISTANCE_LADDER=1`.

## 9. Web Companion

Use the desktop Web Companion controls or run:

```powershell
.\scripts\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
```

Open the LAN URL from an iPad/phone/other device on the same network. LAN mode uses `FZASTRO_WEB_TOKEN`; do not expose it directly to the public internet.

## 10. AI Developer Workbench

Click **DEV** in the quick actions bar.

Use it to:

- Scan the project
- Select relevant files
- Build a context package
- Generate a visible implementation plan
- Run compile checks
- Run pytest checks
- Analyze failures
- Prepare safe patch workflows

Stage 1 is review-first: it helps prepare and validate coding work, not silently rewrite the project.

## 11. Useful commands

```powershell
python -m pytest
python -m compileall -q fzastro_ai tests
powershell -ExecutionPolicy Bypass -File .\scripts\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```
"""

from .window_utils import apply_window_defaults


def open_help_cheat_sheet_dialog(parent):
    """Open the built-in routing and prompt cheat sheet."""
    dialog = QDialog(parent)
    apply_window_defaults(dialog)
    dialog.setObjectName("helpDialog")
    dialog.setWindowTitle("FZAstro AI v2.0.0 Help")
    dialog.resize(900, 760)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("FZAstro AI v2.0.0 Help")
    title.setObjectName("helpDialogTitle")

    subtitle = QLabel(
        "Version 2 guide for chat, models, web, news, market quotes, documents, "
        "PDF page images/text, memory, history, attachments, Python execution, "
        "LLM benchmarking, tests, Web Companion, the Astro Tools Suite, "
        "AI Developer Workbench, and distance-ladder lookup details."
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

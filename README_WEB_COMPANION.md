# FZAstro AI Web Companion Foundation

The Web Companion is a browser interface for the local FZAstro AI engine. It does **not** replace the PySide6 desktop app. It adds a second access path for iPad, Mac, phone, or another browser on the same trusted network.

## Architecture

```text
Browser / iPad / Mac
        ↓
FZAstro AI Web Companion UI
        ↓
FastAPI backend running on the FZAstro AI host PC
        ↓
Existing FZAstro AI runtime helpers
        ↓
Ollama / OpenAI-compatible provider / local tools
```

The LLM runs where the backend runs. In the normal setup, that means the Windows PC running Ollama and FZAstro AI.

## What this first version includes

- FastAPI backend under `fzastro_ai/web_companion/`
- Browser dashboard served from `/`
- Health/status endpoints
- Model list endpoint using the existing runtime helpers
- Streaming chat endpoint using Server-Sent Events
- Optional token protection with `FZASTRO_WEB_TOKEN`
- Initial Astro Tools bridge:
  - LOOKUP
  - SEEING / Astro Night Planner
  - TARGETS

## Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The new dependencies are:

```text
fastapi
uvicorn
```

## Run locally on the host PC

```powershell
.\.venv\Scripts\python.exe -m fzastro_ai.web_companion --port 7860
```

Open:

```text
http://127.0.0.1:7860
```

## Run for iPad/Mac on the same network

Use a token before enabling LAN access:

```powershell
$env:FZASTRO_WEB_TOKEN = "change-this-token"
.\.venv\Scripts\python.exe -m fzastro_ai.web_companion --lan --port 7860
```

Then open this from the iPad/Mac browser:

```text
http://YOUR-PC-IP:7860
```

Enter the same token in the web UI.

## Security notes

- Default bind is `127.0.0.1`, which is host-only.
- `--lan` binds to `0.0.0.0`, which exposes the companion to the local network.
- Use `FZASTRO_WEB_TOKEN` before LAN mode.
- Do not expose this directly to the public internet.
- A future production version should add HTTPS, login/session handling, permission controls, audit logging, and stricter execution isolation.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `FZASTRO_WEB_HOST` | Default bind host | `127.0.0.1` |
| `FZASTRO_WEB_PORT` | Default port | `7860` |
| `FZASTRO_WEB_TOKEN` | Optional shared token | empty |
| `FZASTRO_WEB_ALLOW_LAN` | Metadata flag for LAN mode | `0` |
| `FZASTRO_DEFAULT_MODEL` | Default model | `qwen3:32b` |
| `FZASTRO_APP_DIR` | Data directory override | Windows AppData path |

## Current API endpoints

```text
GET  /api/health
GET  /api/status
GET  /api/models
POST /api/chat
POST /api/chat/stream
GET  /api/astro/tools
GET  /api/news/daily
POST /api/location/resolve
POST /api/astro/lookup
POST /api/astro/seeing
POST /api/astro/targets
```

## Suggested next milestone

For v1.1, expand this into a proper Web Companion mode:

- document library search/upload API
- memory panel API
- benchmark dashboard API
- log tailing via WebSocket
- code workbench API
- file-safe patch generation endpoint
- better mobile/tablet layouts
- desktop configuration-panel controls for local/LAN Web Companion start, open, stop, and auto-start


## Desktop configuration panel plus manual web-only launch

The Web Companion can run in three ways:

1. **Desktop configuration panel** — open the left configuration panel and use the **Web Companion** card to start the local hidden server, open the browser UI, start LAN/iPad mode, copy the URL, or stop a desktop-owned server.
2. **Optional desktop auto-start** — enable **Auto-start local server with desktop** in the same Web Companion card. The setting is saved in the local app data folder and is off by default.
3. **Manual web-only server** — the original manual launch remains supported and does not require the desktop UI:

```powershell
.\run_web_companion.ps1 -Port 7860
```

For iPad/Mac access on the same network:

```powershell
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
```

If the desktop app sees a manually started Web Companion already running on the same port, it reuses it and will not stop it when the desktop app exits.

## Polished Web Companion UI

The Web Companion now uses a workstation-style browser layout:

- The main chat owns most of the screen.
- Model/runtime controls live in a compact right control panel.
- Advanced runtime details are collapsed by default.
- Daily News, LOOKUP, SEEING, TARGETS, and Site Planner are available from the top toolbar above the main chat.
- Astro Tools render inside the main chat instead of a separate output box.
- LOOKUP requests images by default and displays returned local image files through a safe image-asset endpoint.
- Site Planner opens a map picker; latitude/longitude are selected visually and timezone is resolved automatically through the backend.
- Daily News source links render as readable publisher/source chips rather than NEWS_#### identifiers.

## LAN / iPad URL behavior

Local mode serves only the host PC:

```powershell
.\run_web_companion.ps1 -Port 7860
```

Open:

```text
http://127.0.0.1:7860/
```

LAN / iPad mode listens on all local network interfaces and should be opened from other devices through the detected LAN URL, for example:

```powershell
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
```

Open from iPad/Mac/phone on the same Wi-Fi:

```text
http://192.168.x.x:7860/
```

The desktop app's left Configuration panel can start LAN mode, copy the LAN/iPad URL, and display the active URL. Do not expose this directly to the public internet with router port forwarding.

# FZAstro AI Web Companion

The Web Companion is an optional browser interface for FZAstro AI.

It lets the Windows desktop app expose a local web dashboard that can be opened from:

* the same PC
* an iPad
* a Mac
* a phone
* another device on the same LAN

The desktop app and local backend still run on the Windows host. The browser is the remote interface.

## Recommended mode: LAN / iPad mode

Start the server with LAN access and a token:

~~~powershell
cd D:\Dropbox\AI
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
~~~

Open the LAN URL from another device:

~~~text
http://YOUR-PC-LAN-IP:7860/
~~~

Example:

~~~text
http://192.168.178.20:7860/
~~~

Enter the token in the Web Companion UI:

~~~text
fzastro
~~~

## LAN token environment variable

LAN / iPad mode is protected by a web token. The run script sets this automatically when using `-Token`, but it can also be configured manually with the environment variable:

~~~powershell
$env:FZASTRO_WEB_TOKEN = "fzastro"
~~~

Then start the Web Companion in LAN mode:

~~~powershell
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
~~~

Or directly through Python:

~~~powershell
$env:FZASTRO_WEB_TOKEN = "fzastro"
$env:FZASTRO_WEB_ALLOW_LAN = "1"
.\.venv\Scripts\python.exe -m fzastro_ai.web_companion --lan --port 7860
~~~

## Local-only mode

For PC-only testing:

~~~powershell
.\run_web_companion.ps1 -Port 7860
~~~

Open:

~~~text
http://127.0.0.1:7860/
~~~

## Features

* Main chat-first web UI
* Hidden settings drawer opened with the hamburger button
* Local Ollama / OpenAI-compatible model bridge
* Streaming chat
* Daily News Brief
* Astro toolbar:
  * LOOKUP
  * SEEING / Astro Night Planner
  * TARGETS
  * Site Planner
* LOOKUP image display in the main chat
* Site Planner map picker
* Automatic timezone resolution
* Token-protected LAN access
* Manual web-only launch without the desktop app

## Architecture

~~~text
iPad / Mac / phone browser
        ?
FZAstro AI Web Companion
        ?
Windows PC running FZAstro AI backend
        ?
Ollama / OpenAI-compatible local runtime
~~~

The model runs on the Windows host, not on the iPad or phone.

## Test commands

Health check:

~~~powershell
curl.exe http://127.0.0.1:7860/api/health
~~~

LAN status check:

~~~powershell
curl.exe http://YOUR-PC-LAN-IP:7860/api/status -H "X-FZAstro-Token: fzastro"
~~~

Expected LAN mode field:

~~~json
"lan_enabled": true
~~~

## Security note

Do not expose this directly to the public internet. Do not expose port `7860` directly to the public internet. Use LAN, VPN, Tailscale, ZeroTier, or another protected network path for remote access.

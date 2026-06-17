# FZAstro AI Offline Voice Commands

FZAstro AI includes optional offline push-to-talk voice commands using Vosk.
The feature is local-only: audio is recorded from the microphone, transcribed on
this machine, then routed through the same local slash commands, app Skills, and
UI actions the app already uses.

## Setup

Preferred production setup from the project root:

```powershell
. .\scripts\activate_venv.ps1
.\scripts\install_offline_voice.ps1 -PersistEnvironment
```

`install_offline_voice.ps1` downloads/extracts the small English Vosk model to:

```text
%APPDATA%\FZAstroAI\voice_models\vosk-model-small-en-us-0.15
```

The normal release workflow also runs this setup before build unless
`-SkipOfflineVoiceSetup` is passed:

```powershell
.\scripts\deploy.ps1
```

Manual setup remains supported:

```powershell
.\.venv\Scripts\python.exe -m pip install vosk sounddevice
```

Then extract a Vosk model under `%APPDATA%\FZAstroAI\voice_models`, or set
`FZASTRO_VOSK_MODEL` to the extracted model folder. `FZASTRO_VOICE_MODELS_DIR`
can point the setup script and runtime to another model root.

## Use

Click the icon-only microphone button, speak a short command, then pause. The app
auto-processes after roughly one second of silence, so the user does not need to
press Stop after every phrase.

The microphone button still works as a manual override:

```text
click mic -> listen
speak -> pause -> auto process
click mic while listening -> stop/process immediately
```

Say this any time to open the in-app command guide:

```text
what can I say
show voice commands
voice help
```

## Example commands

Astro Tools:

```text
open seeing
open targets
solar map
sun now
site settings
imaging settings
lookup Andromeda
lookup NGC 7000
```

Research and web:

```text
open daily news
refresh daily news
read page
summarize page
screenshot page
```

Knowledge:

```text
open document library
search documents
list documents
open memory
show active context
```

Code Lab:

```text
explain code
debug code
create tests
run python
create commit message
```

Model Lab:

```text
model benchmark
refresh models
model status
show persona
system prompt editor
```

Workspace:

```text
new chat
open history
open diagnostics
open help
clear composer
stop generation
```

## Safety behavior

Safe UI-opening actions execute immediately. Risky actions, including sending the
current message, starting a new chat, or running Python, require confirmation.
Unknown or uncertain speech is inserted into the composer for review instead of
being sent automatically.

## Model notes

The small English Vosk model is recommended for the first release because it is
fast and good enough for fixed commands. Larger models can improve recognition
at the cost of more disk and startup time.

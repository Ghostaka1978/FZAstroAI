from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import (
    API_KEY,
    BASE_URL,
    RUNTIME_CHAT_TIMEOUT_SECONDS,
    RUNTIME_OLLAMA_KEEP_ALIVE_MODE,
)


def normalize_runtime_base_url(base_url):
    clean_url = str(base_url or BASE_URL).strip() or BASE_URL
    return (
        clean_url.rstrip("/") + "/v1"
        if not clean_url.rstrip("/").endswith("/v1")
        else clean_url.rstrip("/")
    )


def normalize_runtime_api_key(api_key):
    return str(api_key or API_KEY or "ollama").strip() or "ollama"


def normalize_runtime_timeout(timeout=None, default=RUNTIME_CHAT_TIMEOUT_SECONDS):
    """Return a positive SDK timeout value in seconds."""

    raw_timeout = default if timeout is None else timeout

    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        timeout_seconds = float(default)

    return max(1.0, timeout_seconds)


OLLAMA_KEEP_ALIVE_MODE_TO_VALUE = {
    "default": None,
    "30m": "30m",
    "60m": "60m",
    "always": "-1",
    "unload": "0",
}

OLLAMA_KEEP_ALIVE_MODE_LABELS = {
    "default": "Ollama default",
    "30m": "Keep warm 30m",
    "60m": "Keep warm 60m",
    "always": "Always warm",
    "unload": "Unload after reply",
}


def normalize_ollama_keep_alive_mode(mode=None, default=None):
    """Return a supported UI/runtime mode for Ollama model residency."""

    fallback = (
        str(default or RUNTIME_OLLAMA_KEEP_ALIVE_MODE or "30m").strip().casefold()
    )
    if fallback not in OLLAMA_KEEP_ALIVE_MODE_TO_VALUE:
        fallback = "30m"

    clean_mode = str(mode or fallback).strip().casefold()
    return clean_mode if clean_mode in OLLAMA_KEEP_ALIVE_MODE_TO_VALUE else fallback


def normalize_ollama_keep_alive_value(value=None):
    """Return an Ollama keep_alive value, or None for provider/default behavior."""

    if value is None:
        return None

    clean_value = str(value).strip()

    if not clean_value:
        return None

    clean_mode = clean_value.casefold()
    if clean_mode in OLLAMA_KEEP_ALIVE_MODE_TO_VALUE:
        return OLLAMA_KEEP_ALIVE_MODE_TO_VALUE[clean_mode]

    # Ollama accepts duration strings such as 30m/1h and sentinel values such as
    # 0 (unload) or -1 (keep indefinitely). Keep validation conservative so an
    # invalid app setting does not poison provider requests.
    if re.match(r"^-?\d+(?:\.\d+)?(?:ms|s|m|h)?$", clean_value, re.IGNORECASE):
        return clean_value

    return None


def ollama_keep_alive_value(mode=None):
    return OLLAMA_KEEP_ALIVE_MODE_TO_VALUE[normalize_ollama_keep_alive_mode(mode)]


def ollama_keep_alive_label(mode=None):
    return OLLAMA_KEEP_ALIVE_MODE_LABELS[normalize_ollama_keep_alive_mode(mode)]


def ollama_keep_alive_preloads_model(mode_or_value=None):
    """Return True when a keep_alive setting should preload a model.

    Provider/default behavior is intentionally skipped because it should not
    create surprise memory residency. ``0``/unload is also skipped because it is
    the explicit cold-mode request. Timed and always-warm modes benefit from a
    deliberate preload so the first real reply does not pay the full model-load
    cost.
    """

    value = normalize_ollama_keep_alive_value(mode_or_value)
    return value not in {None, "0"}


def default_ollama_keep_alive_value():
    explicit_value = os.environ.get("FZASTRO_OLLAMA_KEEP_ALIVE")
    if explicit_value is not None:
        return normalize_ollama_keep_alive_value(explicit_value)
    return ollama_keep_alive_value(os.environ.get("FZASTRO_OLLAMA_KEEP_ALIVE_MODE"))


def is_local_ollama_base_url(base_url):
    """Return True only for local endpoints that the app may auto-start."""

    clean_url = normalize_runtime_base_url(base_url).casefold()
    parsed = urlparse(clean_url)
    host = (parsed.hostname or "").casefold()

    return host in {"localhost", "127.0.0.1", "::1"} and parsed.port == 11434


def is_ollama_base_url(base_url):
    clean_url = normalize_runtime_base_url(base_url).casefold()

    if is_local_ollama_base_url(clean_url):
        return True

    return "ollama" in clean_url


def ollama_root_url(base_url=None):
    """Return the non-OpenAI root URL for an Ollama-compatible endpoint."""

    clean_url = normalize_runtime_base_url(base_url)
    return clean_url.rstrip("/").rsplit("/v1", 1)[0].rstrip("/")


def _parse_listener_output(output, port):
    """Return True when command output shows a listener for ``port``."""

    port_text = str(int(port))

    for raw_line in str(output or "").splitlines():
        line = raw_line.strip().casefold()

        if not line:
            continue

        if port_text not in line:
            continue

        if "listen" in line or "listening" in line:
            return True

    return False


def _linux_proc_net_tcp_has_listener(port):
    """Check Linux /proc TCP tables without opening a socket."""

    port_hex = f"{int(port):04X}"

    for proc_path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = proc_path.read_text(encoding="ascii", errors="ignore").splitlines()[
                1:
            ]
        except OSError:
            continue

        for line in lines:
            parts = line.split()

            if len(parts) < 4:
                continue

            local_address = parts[1].upper()
            state = parts[3].upper()

            if state == "0A" and local_address.endswith(f":{port_hex}"):
                return True

    return False


def _hidden_subprocess_kwargs() -> dict[str, object]:
    """Return subprocess kwargs that suppress console windows on Windows.

    FZAstro is packaged as a windowed desktop app. Startup status probes must
    therefore never flash PowerShell, netstat, git, or optional-tool consoles.
    """

    if not sys.platform.startswith("win"):
        return {}

    kwargs: dict[str, object] = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }

    startupinfo_class = getattr(subprocess, "STARTUPINFO", None)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    if startupinfo_class is not None:
        startupinfo = startupinfo_class()
        startupinfo.dwFlags |= startf_use_show_window
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _run_listener_probe_command(command, timeout=1.0):
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=normalize_runtime_timeout(timeout, default=1.0),
            check=False,
            **_hidden_subprocess_kwargs(),
        )
        return result.stdout or ""
    except Exception:
        return ""


def is_local_tcp_port_listening(port, timeout=1.0):
    """Return whether a local TCP port is listening without connecting to it.

    This deliberately avoids HTTP and socket connect probes. Some local runtime
    managers can wake a background service when clients touch the endpoint, so
    read-only UI status checks and model refresh preflights should inspect the
    OS listener table instead of contacting localhost:11434.
    """

    try:
        clean_port = int(port)
    except (TypeError, ValueError):
        return False

    if clean_port <= 0:
        return False

    command_timeout = normalize_runtime_timeout(timeout, default=1.0)

    if sys.platform.startswith("win"):
        powershell_output = _run_listener_probe_command(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    f"$c = Get-NetTCPConnection -LocalPort {clean_port} "
                    "-State Listen -ErrorAction SilentlyContinue | "
                    "Select-Object -First 1; "
                    "if ($null -ne $c) { 'LISTENING' }"
                ),
            ],
            timeout=command_timeout,
        )

        if _parse_listener_output(powershell_output, clean_port):
            return True

        netstat_output = _run_listener_probe_command(
            ["netstat", "-ano", "-p", "tcp"],
            timeout=command_timeout,
        )
        return _parse_listener_output(netstat_output, clean_port)

    if sys.platform.startswith("linux") and _linux_proc_net_tcp_has_listener(
        clean_port
    ):
        return True

    ss_output = _run_listener_probe_command(
        ["sh", "-c", "command -v ss >/dev/null 2>&1 && ss -ltn || true"],
        timeout=command_timeout,
    )

    if _parse_listener_output(ss_output, clean_port):
        return True

    netstat_output = _run_listener_probe_command(
        ["netstat", "-an"],
        timeout=command_timeout,
    )
    return _parse_listener_output(netstat_output, clean_port)


def is_local_ollama_listener_present(base_url=None, timeout=1.0):
    """Return True when localhost Ollama has a listening port.

    Unlike :func:`is_ollama_server_available`, this does not call /api/tags and
    does not make a TCP connection to the Ollama endpoint. It is safe for model
    refresh/status code paths that must never start or wake Ollama.
    """

    if not is_local_ollama_base_url(base_url):
        return False

    try:
        parsed = urlparse(normalize_runtime_base_url(base_url))
        port = parsed.port or 11434
    except Exception:
        port = 11434

    return is_local_tcp_port_listening(port, timeout=timeout)


def env_flag_enabled(name: str, default: bool = False) -> bool:
    """Return a boolean environment flag using common truthy/falsy values."""

    raw_value = os.environ.get(name)

    if raw_value is None:
        return bool(default)

    return str(raw_value).strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OllamaStartResult:
    """Outcome from a best-effort Ollama launch attempt."""

    available: bool
    attempted_start: bool
    executable: str | None
    status: str
    message: str
    process: subprocess.Popen | None = None


@dataclass(frozen=True)
class OllamaRestartResult:
    """Outcome from a user-requested local Ollama restart."""

    available: bool
    stopped_existing: bool
    attempted_start: bool
    executable: str | None
    status: str
    message: str
    process: subprocess.Popen | None = None


@dataclass(frozen=True)
class OllamaPowerResult:
    """Outcome from a user-requested local Ollama on/off action."""

    running: bool
    action: str
    changed_state: bool
    executable: str | None
    status: str
    message: str
    process: subprocess.Popen | None = None


@dataclass(frozen=True)
class OllamaKeepAliveApplyResult:
    """Outcome from applying model residency through Ollama's native API."""

    applied: bool
    status: str
    message: str


def find_ollama_executable():
    """Return an installed Ollama executable path, if one can be found."""

    configured_path = os.environ.get("FZASTRO_OLLAMA_EXE")
    candidates = []

    if configured_path:
        candidates.append(Path(configured_path).expanduser())

    path_match = shutil.which("ollama")

    if path_match:
        candidates.append(Path(path_match))

    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]

        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            )

        for program_files_dir in program_files:
            if program_files_dir:
                candidates.append(Path(program_files_dir) / "Ollama" / "ollama.exe")

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue

    return None


def is_ollama_server_available(base_url=None, timeout=1.0):
    """Return True when the local Ollama HTTP server responds.

    The function first checks the OS listener table and returns False without
    opening a connection when port 11434 is not listening. That keeps refresh
    and status probes read-only when Ollama is off.
    """

    if not is_local_ollama_base_url(base_url):
        return False

    listener_timeout = min(normalize_runtime_timeout(timeout, default=1.0), 1.0)

    if not is_local_ollama_listener_present(base_url, timeout=listener_timeout):
        return False

    try:
        response = requests.get(
            f"{ollama_root_url(base_url)}/api/tags",
            timeout=normalize_runtime_timeout(timeout, default=1.0),
        )
        return response.status_code < 500
    except Exception:
        return False


def _ollama_native_keep_alive_payload_value(keep_alive):
    """Return a native Ollama keep_alive payload value."""

    keep_alive_value = normalize_ollama_keep_alive_value(keep_alive)

    if keep_alive_value is None:
        return None

    if keep_alive_value in {"0", "-1"}:
        return int(keep_alive_value)

    return keep_alive_value


def apply_ollama_model_keep_alive(
    base_url=None, model=None, keep_alive=None, timeout=4.0
):
    """Apply model residency to a loaded/recently-used Ollama model.

    Ollama's OpenAI-compatible endpoint may not reliably honor ``keep_alive``
    on every server version. After a real chat request, call the native API with
    an empty prompt so a live dropdown change such as Always warm or Unload
    after reply takes effect without requiring an Ollama restart.

    This helper never starts or wakes a stopped local Ollama server: for
    localhost endpoints it first checks the OS listener table and returns before
    opening any HTTP connection when port 11434 is down.
    """

    clean_base_url = normalize_runtime_base_url(base_url)

    if not is_ollama_base_url(clean_base_url):
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="not_ollama",
            message="Keep-alive apply is only available for Ollama endpoints.",
        )

    clean_model = str(model or "").strip()

    if not clean_model:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="missing_model",
            message="No Ollama model name was supplied.",
        )

    payload_keep_alive = _ollama_native_keep_alive_payload_value(keep_alive)

    if payload_keep_alive is None:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="provider_default",
            message="Ollama default residency was requested; no native apply needed.",
        )

    if is_local_ollama_base_url(
        clean_base_url
    ) and not is_local_ollama_listener_present(
        clean_base_url,
        timeout=min(normalize_runtime_timeout(timeout, default=4.0), 1.0),
    ):
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="offline",
            message="Local Ollama is not listening; keep-alive was not applied.",
        )

    payload = {
        "model": clean_model,
        "prompt": "",
        "keep_alive": payload_keep_alive,
        "stream": False,
    }

    try:
        response = requests.post(
            f"{ollama_root_url(clean_base_url)}/api/generate",
            json=payload,
            timeout=normalize_runtime_timeout(timeout, default=4.0),
        )
        response.raise_for_status()
    except Exception as exc:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="apply_failed",
            message=str(exc),
        )

    return OllamaKeepAliveApplyResult(
        applied=True,
        status="applied",
        message=f"Applied Ollama keep_alive={payload_keep_alive!r} for {clean_model}.",
    )


def preload_ollama_model(base_url=None, model=None, keep_alive=None, timeout=90.0):
    """Load the selected Ollama model before the first real chat prompt.

    This uses Ollama's native ``/api/generate`` endpoint with an empty prompt.
    For timed or always-warm modes it asks Ollama to load/keep the model resident
    now, rather than only after the first real reply. For local endpoints the
    function first checks the OS listener table and returns without opening HTTP
    when Ollama is off, so it cannot wake or auto-start the server.
    """

    clean_base_url = normalize_runtime_base_url(base_url)

    if not is_ollama_base_url(clean_base_url):
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="not_ollama",
            message="Model preload is only available for Ollama endpoints.",
        )

    clean_model = str(model or "").strip()

    if not clean_model:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="missing_model",
            message="No Ollama model name was supplied for preload.",
        )

    payload_keep_alive = _ollama_native_keep_alive_payload_value(keep_alive)

    if payload_keep_alive is None:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="provider_default",
            message="Ollama default residency was requested; model preload skipped.",
        )

    if payload_keep_alive == 0:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="unload_mode",
            message="Unload-after-reply mode keeps the model cold; preload skipped.",
        )

    if is_local_ollama_base_url(
        clean_base_url
    ) and not is_local_ollama_listener_present(
        clean_base_url,
        timeout=min(normalize_runtime_timeout(timeout, default=90.0), 1.0),
    ):
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="offline",
            message="Local Ollama is not listening; model preload was not attempted.",
        )

    payload = {
        "model": clean_model,
        "prompt": "",
        "keep_alive": payload_keep_alive,
        "stream": False,
    }

    try:
        response = requests.post(
            f"{ollama_root_url(clean_base_url)}/api/generate",
            json=payload,
            timeout=normalize_runtime_timeout(timeout, default=90.0),
        )
        response.raise_for_status()
    except Exception as exc:
        return OllamaKeepAliveApplyResult(
            applied=False,
            status="preload_failed",
            message=str(exc),
        )

    return OllamaKeepAliveApplyResult(
        applied=True,
        status="preloaded",
        message=f"Preloaded Ollama model {clean_model} with keep_alive={payload_keep_alive!r}.",
    )


def start_ollama_server_if_available(base_url=None, wait_seconds=8.0, keep_alive=None):
    """Best-effort start of an installed Ollama server.

    This is intentionally limited to local Ollama endpoints. It never installs
    Ollama, never downloads models, and never starts arbitrary remote providers.
    """

    if not is_local_ollama_base_url(base_url):
        return OllamaStartResult(
            available=False,
            attempted_start=False,
            executable=None,
            status="not_local_ollama",
            message="The configured provider is not a local Ollama endpoint.",
        )

    if is_ollama_server_available(base_url):
        return OllamaStartResult(
            available=True,
            attempted_start=False,
            executable=None,
            status="already_running",
            message="Ollama is already running.",
        )

    if is_local_ollama_listener_present(base_url):
        return OllamaStartResult(
            available=False,
            attempted_start=False,
            executable=None,
            status="listener_present_not_ready",
            message=(
                "Ollama already owns localhost:11434, but the API is not ready. "
                "Turn it off first, then turn it on again."
            ),
        )

    executable = find_ollama_executable()

    if not executable:
        return OllamaStartResult(
            available=False,
            attempted_start=False,
            executable=None,
            status="not_installed",
            message=(
                "Ollama unavailable — Ollama is not running and ollama.exe was "
                "not found on PATH or in the standard install location."
            ),
        )

    popen_env = os.environ.copy()
    keep_alive_value = normalize_ollama_keep_alive_value(keep_alive)
    if keep_alive_value is not None:
        popen_env["OLLAMA_KEEP_ALIVE"] = keep_alive_value
        popen_env["FZASTRO_OLLAMA_KEEP_ALIVE"] = keep_alive_value

    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": popen_env,
    }

    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen([executable, "serve"], **popen_kwargs)
    except OSError as exc:
        return OllamaStartResult(
            available=False,
            attempted_start=True,
            executable=executable,
            status="start_failed",
            message=f"Ollama unavailable — failed to start Ollama: {exc}",
        )

    deadline = time.monotonic() + normalize_runtime_timeout(wait_seconds, default=8.0)

    while time.monotonic() < deadline:
        if is_ollama_server_available(base_url):
            return OllamaStartResult(
                available=True,
                attempted_start=True,
                executable=executable,
                status="started",
                message="Ollama was started automatically.",
                process=process,
            )

        time.sleep(0.35)

    return OllamaStartResult(
        available=False,
        attempted_start=True,
        executable=executable,
        status="started_not_ready",
        message=(
            "Ollama was started automatically, but the server did not become "
            "ready before the model-list timeout. Refresh models in a few seconds."
        ),
        process=process,
    )


def should_auto_start_ollama():
    """Return whether the app may start an installed local Ollama server."""

    return env_flag_enabled("FZASTRO_AUTO_START_OLLAMA", default=True)


def should_stop_owned_ollama_on_exit():
    """Return whether the app should stop its owned Ollama process on exit.

    FZAstro AI must not leave an Ollama server running after it started one
    automatically or through the local power button. The environment flag is
    retained as an escape hatch for users who intentionally want to keep an
    app-started Ollama process alive after closing the desktop shell.
    """

    return env_flag_enabled("FZASTRO_STOP_OLLAMA_ON_EXIT", default=True)


def stop_owned_ollama_process(process, timeout=3.0):
    """Terminate an Ollama process started by this app.

    The helper intentionally operates only on the stored Popen object returned
    when FZAstro AI launched `ollama serve`. It never scans for or kills other
    Ollama processes that may belong to the user or another application. If the
    graceful termination request times out, it escalates to kill so app-owned
    Ollama processes do not remain stale after desktop exit.
    """

    if process is None:
        return "not_started"

    try:
        if process.poll() is not None:
            return "already_exited"

        wait_timeout = normalize_runtime_timeout(timeout, default=3.0)
        process.terminate()

        try:
            process.wait(timeout=wait_timeout)
            return "stopped"
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=wait_timeout)
            return "killed"
    except subprocess.TimeoutExpired:
        return "still_running"
    except Exception as exc:
        return f"stop_failed: {exc}"


def _run_ollama_stop_commands(commands, timeout):
    """Run one phase of local Ollama stop commands and return the last error."""

    last_error = ""
    command_timeout = normalize_runtime_timeout(timeout, default=5.0)

    for command in commands:
        try:
            subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=command_timeout,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
        except Exception as exc:
            last_error = str(exc)

    return last_error


def _process_name_contains_ollama_runner(name_or_path):
    """Return True for Ollama parent/tray/service and llama runner processes."""

    clean = str(name_or_path or "").strip().casefold()

    if not clean:
        return False

    process_markers = (
        "ollama",
        "llama-server",
        "llama server",
    )
    path_markers = (
        "\\ollama\\",
        "/ollama/",
        "\\lib\\ollama\\",
        "/lib/ollama/",
    )

    return any(marker in clean for marker in process_markers + path_markers)


def is_local_ollama_process_present(timeout=1.0):
    """Return True when a local Ollama process or llama GPU runner remains.

    Port checks alone are insufficient on Windows: the HTTP listener can be gone
    while ``llama-server.exe`` still owns GPU memory for a short period, or a tray
    owner can respawn the listener after FZAstro exits. This helper is used only
    for explicit shutdown verification; normal status refresh still uses the
    listener table to avoid waking Ollama.
    """

    command_timeout = normalize_runtime_timeout(timeout, default=1.0)

    if sys.platform.startswith("win"):
        command = (
            "$items = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { "
            "($_.Name -match '^(ollama|llama-server).*\\.exe$') -or "
            "($_.ExecutablePath -and $_.ExecutablePath -like '*\\Ollama\\*') "
            "}; "
            "foreach ($item in $items) { $item.Name + '|' + $item.ExecutablePath }"
        )
        output = _run_listener_probe_command(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            timeout=command_timeout,
        )
        return any(
            _process_name_contains_ollama_runner(line)
            for line in str(output or "").splitlines()
        )

    if sys.platform == "darwin":
        output = _run_listener_probe_command(
            ["pgrep", "-fl", "ollama|llama-server"],
            timeout=command_timeout,
        )
    else:
        output = _run_listener_probe_command(
            ["pgrep", "-af", "ollama|llama-server"],
            timeout=command_timeout,
        )

    return any(
        _process_name_contains_ollama_runner(line)
        for line in str(output or "").splitlines()
    )


def _wait_for_ollama_shutdown(
    base_url, timeout, stable_seconds=1.5, require_process_stop=False
):
    """Return True only after local Ollama stays down.

    The check deliberately uses the OS listener/process tables instead of
    /api/tags. On some Windows/Ollama installs, HTTP probes can wake a
    background Ollama app or service. Shutdown verification must be read-only,
    catch fast respawns, and optionally ensure the detached ``llama-server.exe``
    GPU runner is gone before the desktop shell exits.
    """

    deadline = time.monotonic() + normalize_runtime_timeout(timeout, default=5.0)
    stable_required = max(0.2, float(stable_seconds or 0.0))
    stable_since = None

    while time.monotonic() < deadline:
        listener_present = is_local_ollama_listener_present(base_url, timeout=0.5)
        process_present = (
            is_local_ollama_process_present(timeout=0.5)
            if require_process_stop
            else False
        )

        if listener_present or process_present:
            stable_since = None
        else:
            now = time.monotonic()

            if stable_since is None:
                stable_since = now

            if now - stable_since >= stable_required:
                return True

        time.sleep(0.25)

    if is_local_ollama_listener_present(base_url, timeout=0.5):
        return False

    if require_process_stop and is_local_ollama_process_present(timeout=0.5):
        return False

    return True


def _windows_ollama_stop_phases(port=11434):
    """Return Windows stop phases for Ollama and possible respawn owners."""

    clean_port = int(port or 11434)
    stop_service_command = (
        "Stop-Service -Name Ollama -ErrorAction SilentlyContinue; "
        "Stop-Service -Name ollama -ErrorAction SilentlyContinue"
    )
    stop_process_command = (
        "$processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "($_.Name -match '^(ollama|llama-server).*\\.exe$') -or "
        "($_.ExecutablePath -and $_.ExecutablePath -like '*\\Ollama\\*') "
        "}; "
        "foreach ($p in $processes) { "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }; "
        f"$pids = Get-NetTCPConnection -LocalPort {clean_port} "
        "-State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess -Unique; "
        "foreach ($processId in $pids) { "
        "Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }"
    )

    return [
        (
            "stopped",
            [
                ["taskkill", "/IM", "ollama.exe", "/T"],
                ["taskkill", "/IM", "llama-server.exe", "/T"],
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    stop_service_command,
                ],
            ],
        ),
        (
            "killed",
            [
                ["taskkill", "/IM", "ollama.exe", "/F", "/T"],
                ["taskkill", "/IM", "llama-server.exe", "/F", "/T"],
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    stop_process_command,
                ],
            ],
        ),
    ]


def _local_ollama_port(base_url=None):
    try:
        parsed = urlparse(normalize_runtime_base_url(base_url))
        return int(parsed.port or 11434)
    except Exception:
        return 11434


def terminate_local_ollama_server(base_url=None, timeout=8.0, force_process_stop=False):
    """Best-effort termination for a local Ollama server process.

    This is used by the explicit local Ollama power control and by app exit
    cleanup when the configured endpoint is localhost:11434. It is intentionally
    restricted to a local Ollama endpoint so remote OpenAI-compatible providers
    can never be affected.

    Windows Ollama can respawn through a tray/background app, service wrapper,
    or detached child listener. The terminator therefore kills the normal
    process tree, kills the owner of port 11434, stops any Ollama service, and
    repeats until the listener has stayed down for a short stable window.
    """

    if not is_local_ollama_base_url(base_url):
        return False, "not_local_ollama"

    listener_present = is_local_ollama_listener_present(base_url, timeout=0.8)

    if not listener_present and not force_process_stop:
        return False, "already_stopped"

    port = _local_ollama_port(base_url)

    if sys.platform.startswith("win"):
        stop_phases = _windows_ollama_stop_phases(port)
    elif sys.platform == "darwin":
        stop_phases = [
            ("stopped", [["pkill", "-TERM", "-f", "ollama|llama-server"]]),
            ("killed", [["pkill", "-KILL", "-f", "ollama|llama-server"]]),
        ]
    else:
        stop_phases = [
            ("stopped", [["pkill", "-TERM", "-f", "ollama|llama-server"]]),
            (
                "killed",
                [
                    ["pkill", "-KILL", "-f", "ollama|llama-server"],
                    [
                        "sh",
                        "-c",
                        f"command -v fuser >/dev/null 2>&1 && fuser -k {port}/tcp || true",
                    ],
                ],
            ),
        ]

    last_error = ""
    total_timeout = normalize_runtime_timeout(timeout, default=8.0)
    max_attempts = 4 if sys.platform.startswith("win") else 2
    phase_timeout = max(1.0, total_timeout / (len(stop_phases) * max_attempts))

    for attempt in range(1, max_attempts + 1):
        for status, commands in stop_phases:
            phase_error = _run_ollama_stop_commands(commands, phase_timeout)

            if phase_error:
                last_error = phase_error

            if _wait_for_ollama_shutdown(
                base_url,
                phase_timeout,
                stable_seconds=1.6 if sys.platform.startswith("win") else 0.8,
                require_process_stop=force_process_stop,
            ):
                status_prefix = (
                    f"{status}_process"
                    if force_process_stop and not listener_present
                    else status
                )

                if attempt == 1:
                    return True, status_prefix

                return True, f"{status_prefix}_after_respawn_{attempt}"

    return False, f"stop_timeout{': ' + last_error if last_error else ''}"


def toggle_local_ollama_server(base_url=None, wait_seconds=12.0, keep_alive=None):
    """Start or stop the local Ollama server depending on its current state.

    Unlike the legacy restart helper, this function never performs a stop-start
    cycle. A running local Ollama endpoint is turned off. A stopped local Ollama
    endpoint is started, then probed until /api/tags responds.
    """

    if not is_local_ollama_base_url(base_url):
        return OllamaPowerResult(
            running=False,
            action="none",
            changed_state=False,
            executable=None,
            status="not_local_ollama",
            message="Power control is available only for local Ollama at localhost:11434.",
        )

    if is_local_ollama_listener_present(base_url, timeout=0.8):
        stopped, stop_status = terminate_local_ollama_server(base_url)

        if stopped or not is_local_ollama_listener_present(base_url, timeout=0.5):
            return OllamaPowerResult(
                running=False,
                action="stop",
                changed_state=True,
                executable=None,
                status=f"stopped:{stop_status}",
                message="Local Ollama was turned off.",
            )

        return OllamaPowerResult(
            running=True,
            action="stop",
            changed_state=False,
            executable=None,
            status=f"stop_failed:{stop_status}",
            message=(
                "FZAstro AI tried to turn off local Ollama, but the listener is "
                "still present. Close Ollama manually, then try again."
            ),
        )

    start_result = start_ollama_server_if_available(
        base_url, wait_seconds=wait_seconds, keep_alive=keep_alive
    )

    if start_result.available:
        return OllamaPowerResult(
            running=True,
            action="start",
            changed_state=bool(start_result.attempted_start),
            executable=start_result.executable,
            status=f"started:{start_result.status}",
            message="Local Ollama is on. " + start_result.message,
            process=start_result.process,
        )

    return OllamaPowerResult(
        running=False,
        action="start",
        changed_state=False,
        executable=start_result.executable,
        status=f"start_failed:{start_result.status}",
        message=start_result.message,
        process=start_result.process,
    )


def restart_local_ollama_server(base_url=None, wait_seconds=12.0):
    """Restart a local Ollama server and wait for it to answer /api/tags."""

    if not is_local_ollama_base_url(base_url):
        return OllamaRestartResult(
            available=False,
            stopped_existing=False,
            attempted_start=False,
            executable=None,
            status="not_local_ollama",
            message="Restart is available only for local Ollama at localhost:11434.",
        )

    stopped_existing, stop_status = terminate_local_ollama_server(base_url)

    start_result = start_ollama_server_if_available(base_url, wait_seconds=wait_seconds)

    if start_result.available:
        stop_fragment = (
            "Existing Ollama process was stopped first. "
            if stopped_existing
            else "No running local Ollama process needed to be stopped. "
        )
        return OllamaRestartResult(
            available=True,
            stopped_existing=stopped_existing,
            attempted_start=start_result.attempted_start,
            executable=start_result.executable,
            status=f"restarted:{stop_status}:{start_result.status}",
            message=stop_fragment + start_result.message,
            process=start_result.process,
        )

    return OllamaRestartResult(
        available=False,
        stopped_existing=stopped_existing,
        attempted_start=start_result.attempted_start,
        executable=start_result.executable,
        status=f"restart_failed:{stop_status}:{start_result.status}",
        message=(
            f"Ollama restart failed after stop status '{stop_status}'. "
            f"{start_result.message}"
        ),
        process=start_result.process,
    )


def iter_exception_chain(error):
    """Yield an exception and its chained causes/contexts once each."""

    seen = set()
    current = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )


def runtime_error_text(error):
    """Return lowercase text from an SDK/runtime exception chain."""

    parts = []

    for current in iter_exception_chain(error):
        parts.append(str(current))

        response = getattr(current, "response", None)

        if response is not None:
            response_text = getattr(response, "text", None)

            if response_text:
                parts.append(str(response_text))

    return " ".join(parts).casefold()


def is_runtime_connection_error(error):
    """Return True for expected provider reachability failures.

    Model discovery is a best-effort convenience path. Local runtimes such as
    Ollama are often stopped while the app is open; that should fall back to the
    configured default model without writing a scary traceback.
    """

    for current in iter_exception_chain(error):
        class_name = current.__class__.__name__

        if class_name in {
            "APIConnectionError",
            "APITimeoutError",
            "ConnectError",
            "ConnectTimeout",
            "ConnectionError",
            "ConnectionRefusedError",
            "ReadTimeout",
            "TimeoutException",
            "TimeoutError",
        }:
            return True

        error_text = str(current).casefold()

        if "request timed out" in error_text or "timed out" in error_text:
            return True

    return False


def is_runtime_model_not_found_error(error):
    """Return True when the selected runtime model is not installed/available."""

    error_text = runtime_error_text(error)

    for current in iter_exception_chain(error):
        class_name = current.__class__.__name__
        status_code = getattr(current, "status_code", None)
        response = getattr(current, "response", None)

        if response is not None:
            status_code = getattr(response, "status_code", status_code)

        not_found_status = status_code == 404 or class_name == "NotFoundError"

        if (
            not_found_status
            and "model" in error_text
            and (
                "not found" in error_text
                or "not_found" in error_text
                or "does not exist" in error_text
                or "unknown model" in error_text
            )
        ):
            return True

    return False


def format_runtime_model_unavailable_message(model, base_url=None):
    """Return a user-facing message for a missing selected model."""

    clean_model = str(model or "").strip() or "the selected model"

    if is_ollama_base_url(base_url):
        return (
            f"Selected model '{clean_model}' is not installed in Ollama. "
            "Refresh models, select an installed model, or pull it with "
            f"ollama pull {clean_model}."
        )

    return (
        f"Selected model '{clean_model}' is not available from the configured "
        "model provider. Refresh models or select an available model."
    )


def make_runtime_client(base_url=None, api_key=None, timeout=None):
    # Import lazily so pure runtime URL/API-key helpers stay testable even when
    # optional GUI/runtime dependencies are not installed in lightweight checks.
    from openai import OpenAI

    return OpenAI(
        base_url=normalize_runtime_base_url(base_url),
        api_key=normalize_runtime_api_key(api_key),
        timeout=normalize_runtime_timeout(timeout),
    )

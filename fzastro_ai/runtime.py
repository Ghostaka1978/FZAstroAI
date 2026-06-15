from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import API_KEY, BASE_URL, RUNTIME_CHAT_TIMEOUT_SECONDS


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
    """Return True when the Ollama HTTP server responds to a local tags probe."""

    if not is_local_ollama_base_url(base_url):
        return False

    try:
        response = requests.get(
            f"{ollama_root_url(base_url)}/api/tags",
            timeout=normalize_runtime_timeout(timeout, default=1.0),
        )
        return response.status_code < 500
    except Exception:
        return False


def start_ollama_server_if_available(base_url=None, wait_seconds=8.0):
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

    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
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
    """Return whether the app should stop only its owned Ollama process on exit."""

    return env_flag_enabled("FZASTRO_STOP_OLLAMA_ON_EXIT", default=False)


def stop_owned_ollama_process(process, timeout=3.0):
    """Best-effort termination for an Ollama process started by this app.

    The helper intentionally operates only on the stored Popen object returned
    when FZAstro AI launched `ollama serve`. It never scans for or kills other
    Ollama processes that may belong to the user or another application.
    """

    if process is None:
        return "not_started"

    try:
        if process.poll() is not None:
            return "already_exited"

        process.terminate()
        process.wait(timeout=normalize_runtime_timeout(timeout, default=3.0))
        return "stopped"
    except subprocess.TimeoutExpired:
        return "still_running"
    except Exception as exc:
        return f"stop_failed: {exc}"


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

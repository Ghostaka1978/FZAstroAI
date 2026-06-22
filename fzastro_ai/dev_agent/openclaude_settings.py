"""Local-only OpenClaude settings.

These settings are deliberately stored under FZAstro's AppData directory, not
inside the selected workspace.  Secrets must never be written to AGENTS.md,
project context files, git status output, launcher scripts, or terminal-visible
diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from ..config import API_KEY, APP_DIR
from ..json_store import atomic_write_json, preserve_corrupt_file

OPENCLAUDE_SETTINGS_SCHEMA_VERSION = 3
OPENCLAUDE_SETTINGS_FILE = APP_DIR / "openclaude" / "openclaude_settings.json"
# Backwards-compatible internal alias. Do not expose this name in UI/env output.
OPENCLAUDE_API_SETTINGS_FILE = OPENCLAUDE_SETTINGS_FILE


@dataclass(frozen=True)
class OpenClaudeApiSettings:
    """Persisted OpenClaude local-secret settings.

    ``api_key`` is retained for the OpenAI-compatible model endpoint.
    ``git_api_token`` is the token used by OpenClaude/GitHub tooling to access
    the selected project repository.  Both values live only under AppData.
    """

    api_key: str = ""
    git_api_token: str = ""
    max_output_tokens: str = ""
    path: str = str(OPENCLAUDE_SETTINGS_FILE)

    @property
    def has_api_key(self) -> bool:
        return bool(str(self.api_key or "").strip())

    @property
    def has_git_api_token(self) -> bool:
        return bool(str(self.git_api_token or "").strip())

    @property
    def has_max_output_tokens(self) -> bool:
        return bool(str(self.max_output_tokens or "").strip())


def _settings_path(settings_file: Path | str | None = None) -> Path:
    return (
        Path(settings_file) if settings_file is not None else OPENCLAUDE_SETTINGS_FILE
    )


def _private_file(path: Path) -> None:
    """Best-effort local secret-file permissions.

    Windows may ignore POSIX mode bits depending on filesystem policy.  The file
    still lives outside the selected Git workspace so normal project scans,
    AGENTS.md generation, and patch exports do not include it.
    """

    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _coerce_secret(value: Any) -> str:
    return str(value or "").strip()


def _coerce_token_budget(value: Any) -> str:
    """Return a safe persisted token budget or an empty string.

    This stores the OpenClaude/Claude Code output-token cap for compatibility
    with existing local settings. The visible UI no longer exposes this as a
    context-set control; OpenClaude context is fixed separately at 128000.
    """

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return ""
    number = max(1024, min(24000, number))
    return str(number)


def _payload_has_persisted_settings(payload: dict[str, Any]) -> bool:
    return any(
        _coerce_secret(payload.get(key))
        for key in ("api_key", "git_api_token", "max_output_tokens")
    )


def _read_settings_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OpenClaude settings file must contain a JSON object")
    return data


def _write_settings_payload(path: Path, payload: dict[str, Any]) -> None:
    clean_payload = {
        key: value
        for key, value in payload.items()
        if key == "schema_version" or _coerce_secret(value)
    }
    clean_payload["schema_version"] = OPENCLAUDE_SETTINGS_SCHEMA_VERSION
    atomic_write_json(path, clean_payload, sort_keys=True)
    _private_file(path)


def load_openclaude_api_settings(
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Load OpenClaude local secrets from the AppData settings file."""

    path = _settings_path(settings_file)
    if not path.exists():
        return OpenClaudeApiSettings(
            api_key="", git_api_token="", max_output_tokens="", path=str(path)
        )
    try:
        data = _read_settings_payload(path)
        return OpenClaudeApiSettings(
            api_key=_coerce_secret(data.get("api_key")),
            git_api_token=_coerce_secret(data.get("git_api_token")),
            max_output_tokens=_coerce_token_budget(data.get("max_output_tokens")),
            path=str(path),
        )
    except Exception:
        preserve_corrupt_file(path, "load_openclaude_api_settings")
        return OpenClaudeApiSettings(
            api_key="", git_api_token="", max_output_tokens="", path=str(path)
        )


def save_openclaude_api_key(
    api_key: str,
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Save or clear the OpenAI-compatible model API key.

    This is intentionally separate from the Git repository token.  Passing an
    empty value clears only the model API key and preserves any saved Git token.
    """

    clean = _coerce_secret(api_key)
    path = _settings_path(settings_file)
    try:
        payload = _read_settings_payload(path)
    except Exception:
        preserve_corrupt_file(path, "save_openclaude_api_key")
        payload = {}
    if clean:
        payload["api_key"] = clean
    else:
        payload.pop("api_key", None)
    if not _payload_has_persisted_settings(payload):
        return clear_openclaude_settings_file(path)
    _write_settings_payload(path, payload)
    return load_openclaude_api_settings(path)


def clear_openclaude_api_key(
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Remove only the model API key, preserving the Git repository token."""

    return save_openclaude_api_key("", settings_file=settings_file)


def save_openclaude_git_api_token(
    git_api_token: str,
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Save or clear the Git repository API token.

    The token is used as ``GITHUB_TOKEN``/``GH_TOKEN`` for OpenClaude's git/GitHub
    operations.  It is stored only under AppData and is never written to the
    selected workspace, AGENTS.md, generated context, launcher script, or git
    diagnostics.
    """

    clean = _coerce_secret(git_api_token)
    path = _settings_path(settings_file)
    try:
        payload = _read_settings_payload(path)
    except Exception:
        preserve_corrupt_file(path, "save_openclaude_git_api_token")
        payload = {}
    if clean:
        payload["git_api_token"] = clean
    else:
        payload.pop("git_api_token", None)
    if not _payload_has_persisted_settings(payload):
        return clear_openclaude_settings_file(path)
    _write_settings_payload(path, payload)
    return load_openclaude_api_settings(path)


def clear_openclaude_git_api_token(
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Remove only the Git repository API token."""

    return save_openclaude_git_api_token("", settings_file=settings_file)


def save_openclaude_max_output_tokens(
    max_output_tokens: str | int,
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Save or clear the OpenClaude output-token budget.

    The value is stored with OpenClaude local settings under AppData and is
    applied to ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` when a new terminal starts.
    """

    clean = _coerce_token_budget(max_output_tokens)
    path = _settings_path(settings_file)
    try:
        payload = _read_settings_payload(path)
    except Exception:
        preserve_corrupt_file(path, "save_openclaude_max_output_tokens")
        payload = {}
    if clean:
        payload["max_output_tokens"] = clean
    else:
        payload.pop("max_output_tokens", None)
    if not _payload_has_persisted_settings(payload):
        return clear_openclaude_settings_file(path)
    _write_settings_payload(path, payload)
    return load_openclaude_api_settings(path)


def openclaude_max_output_tokens_state(
    settings: OpenClaudeApiSettings, *, default: str = "16000"
) -> str:
    """Return a UI-safe status line for the output-token budget."""

    active = _coerce_token_budget(settings.max_output_tokens) or _coerce_token_budget(
        default
    )
    return f"CLAUDE_CODE_MAX_OUTPUT_TOKENS: {active}"


def clear_openclaude_settings_file(
    settings_file: Path | str | None = None,
) -> OpenClaudeApiSettings:
    """Remove the persisted OpenClaude settings file if it is now empty."""

    path = _settings_path(settings_file)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
    return OpenClaudeApiSettings(
        api_key="", git_api_token="", max_output_tokens="", path=str(path)
    )


def openclaude_api_key_state(
    settings: OpenClaudeApiSettings,
    *,
    fallback_api_key: str = API_KEY,
) -> str:
    """Return a UI-safe status string for the active model API key."""

    saved_key = _coerce_secret(settings.api_key)
    fallback_key = _coerce_secret(fallback_api_key)
    if saved_key:
        if saved_key == API_KEY:
            return "OPENAI_API_KEY: stored locally for OpenClaude model endpoint / hidden (default value)"
        return "OPENAI_API_KEY: stored locally for OpenClaude model endpoint / hidden"
    if not fallback_key:
        return "OPENAI_API_KEY: not set"
    if fallback_key == API_KEY:
        return "OPENAI_API_KEY: using configured default / hidden"
    return "OPENAI_API_KEY: using main app runtime / hidden"


def openclaude_git_token_state(settings: OpenClaudeApiSettings) -> str:
    """Return a UI-safe status string for Git repository API access."""

    if _coerce_secret(settings.git_api_token):
        return "Git repository API token: stored locally / hidden"
    return "Git repository API token: not saved"

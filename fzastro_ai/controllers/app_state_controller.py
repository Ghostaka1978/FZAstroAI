from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import APP_DIR, RUNTIME_OLLAMA_KEEP_ALIVE_MODE
from ..history_store import load_chat_history
from ..json_store import atomic_write_json, preserve_corrupt_file
from ..logging_utils import log_exception
from ..memory_store import (
    load_calibration_profile_store,
    load_persistent_memory,
)

WEB_COMPANION_DEFAULT_SETTINGS: dict[str, Any] = {"auto_start_desktop": False}
RUNTIME_DEFAULT_SETTINGS: dict[str, Any] = {
    "ollama_keep_alive_mode": RUNTIME_OLLAMA_KEEP_ALIVE_MODE
}


@dataclass(frozen=True)
class ApplicationState:
    chat_history: list[dict[str, Any]]
    web_companion_settings: dict[str, Any]
    runtime_settings: dict[str, Any]
    calibration_profile_store: dict[str, Any]
    persistent_memory_data: dict[str, Any]


class AppStateController:
    """Loads and saves small app-level state outside the main window class."""

    def __init__(self, app_dir: Path | str = APP_DIR):
        self.app_dir = Path(app_dir)

    @property
    def web_companion_settings_path(self) -> Path:
        return self.app_dir / "web_companion_settings.json"

    def load_web_companion_settings(self) -> dict[str, Any]:
        settings = dict(WEB_COMPANION_DEFAULT_SETTINGS)
        path = self.web_companion_settings_path

        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as exc:
            log_exception("AppStateController.load_web_companion_settings", exc)
            preserve_corrupt_file(
                path,
                "AppStateController.preserve_corrupt_web_companion_settings",
            )

        return settings

    def save_web_companion_settings(self, settings: dict[str, Any]) -> None:
        normalized = dict(WEB_COMPANION_DEFAULT_SETTINGS)
        if isinstance(settings, dict):
            normalized.update(settings)
        atomic_write_json(
            self.web_companion_settings_path,
            normalized,
            indent=2,
            sort_keys=True,
        )

    @property
    def runtime_settings_path(self) -> Path:
        return self.app_dir / "runtime_settings.json"

    def load_runtime_settings(self) -> dict[str, Any]:
        settings = dict(RUNTIME_DEFAULT_SETTINGS)
        path = self.runtime_settings_path

        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as exc:
            log_exception("AppStateController.load_runtime_settings", exc)
            preserve_corrupt_file(
                path,
                "AppStateController.preserve_corrupt_runtime_settings",
            )

        return settings

    def save_runtime_settings(self, settings: dict[str, Any]) -> None:
        normalized = dict(RUNTIME_DEFAULT_SETTINGS)
        if isinstance(settings, dict):
            normalized.update(settings)
        atomic_write_json(
            self.runtime_settings_path,
            normalized,
            indent=2,
            sort_keys=True,
        )

    def load(self) -> ApplicationState:
        return ApplicationState(
            chat_history=load_chat_history(),
            web_companion_settings=self.load_web_companion_settings(),
            runtime_settings=self.load_runtime_settings(),
            calibration_profile_store=load_calibration_profile_store(),
            persistent_memory_data=load_persistent_memory(),
        )

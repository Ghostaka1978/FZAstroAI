from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..config import LOG_DIR
from ..logging_utils import log_exception, log_warning

DEFAULT_WEB_PORT = int(os.environ.get("FZASTRO_WEB_PORT", "7860"))

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_LAN_HOST = "0.0.0.0"
WEB_HEALTH_TIMEOUT_SECONDS = 0.8
WEB_START_WAIT_SECONDS = 4.0


@dataclass
class WebCompanionStatus:
    running: bool
    owned: bool
    url: str
    message: str
    pid: int | None = None
    lan: bool = False


def local_web_url(port: int = DEFAULT_WEB_PORT) -> str:
    return f"http://127.0.0.1:{int(port)}/"


def lan_web_url(port: int = DEFAULT_WEB_PORT) -> str:
    return f"http://{detect_lan_ip()}:{int(port)}/"


def detect_lan_ip() -> str:
    """Return the best same-network IPv4 address for the host PC."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets need to reach this address. connect() only asks the OS
        # which local interface would be used for normal outbound traffic.
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
    except OSError:
        address = "127.0.0.1"
    finally:
        sock.close()

    return address


def is_web_companion_available(port: int = DEFAULT_WEB_PORT) -> bool:
    try:
        response = requests.get(
            f"http://127.0.0.1:{int(port)}/api/health",
            timeout=WEB_HEALTH_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


class WebCompanionProcess:
    """Hidden subprocess manager for the optional FZAstro AI Web Companion.

    The standalone/manual launch path remains available through:
        python -m fzastro_ai.web_companion
        .\run_web_companion.ps1

    This class is only used by the PySide6 desktop app when it wants to start,
    open, or stop a web companion process in the background.
    """

    def __init__(self, port: int = DEFAULT_WEB_PORT) -> None:
        self.port = int(port)
        self.process: subprocess.Popen[str] | None = None
        self.lan = False
        self.log_file = Path(LOG_DIR) / "fzastro_web_companion.log"

    @property
    def local_url(self) -> str:
        return local_web_url(self.port)

    @property
    def lan_url(self) -> str:
        return lan_web_url(self.port)

    def is_owned_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def is_running(self) -> bool:
        return self.is_owned_running() or is_web_companion_available(self.port)

    def status(self) -> WebCompanionStatus:
        if self.is_owned_running():
            return WebCompanionStatus(
                running=True,
                owned=True,
                url=self.lan_url if self.lan else self.local_url,
                message="Web Companion is running from the desktop app.",
                pid=self.process.pid if self.process else None,
                lan=self.lan,
            )

        if is_web_companion_available(self.port):
            return WebCompanionStatus(
                running=True,
                owned=False,
                url=self.lan_url,
                message=(
                    "Web Companion is already running externally/manual. "
                    "Use the LAN/iPad URL if it was started with -Lan."
                ),
                pid=None,
                lan=True,
            )

        return WebCompanionStatus(
            running=False,
            owned=False,
            url=self.local_url,
            message="Web Companion is stopped.",
            pid=None,
            lan=False,
        )

    def start(self, *, lan: bool = False, token: str = "") -> WebCompanionStatus:
        existing = self.status()
        if existing.running:
            return existing

        self.lan = bool(lan)
        env = os.environ.copy()
        env["FZASTRO_WEB_PORT"] = str(self.port)

        args = [
            sys.executable,
            "-m",
            "fzastro_ai.web_companion",
            "--port",
            str(self.port),
        ]

        if self.lan:
            args.append("--lan")
            env["FZASTRO_WEB_ALLOW_LAN"] = "1"

        clean_token = str(token or "").strip()
        if clean_token:
            env["FZASTRO_WEB_TOKEN"] = clean_token
        elif self.lan and not env.get("FZASTRO_WEB_TOKEN"):
            return WebCompanionStatus(
                running=False,
                owned=False,
                url=self.lan_url,
                message="LAN mode requires a web token.",
                pid=None,
                lan=True,
            )

        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self.log_file.open("a", encoding="utf-8")
        log_handle.write("\n--- starting FZAstro Web Companion ---\n")
        log_handle.flush()

        try:
            self.process = subprocess.Popen(
                args,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(Path(__file__).resolve().parents[2]),
                env=env,
                text=True,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            log_handle.close()
        except Exception as exc:
            log_handle.close()
            log_exception("WebCompanionProcess.start", exc)
            return WebCompanionStatus(
                running=False,
                owned=False,
                url=self.lan_url if self.lan else self.local_url,
                message=f"Could not start Web Companion: {exc}",
                pid=None,
                lan=self.lan,
            )

        deadline = time.monotonic() + WEB_START_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if is_web_companion_available(self.port):
                return self.status()
            time.sleep(0.15)

        if self.process.poll() is not None:
            log_warning(
                "Web Companion subprocess exited during startup",
                f"pid={self.process.pid}, code={self.process.returncode}, log={self.log_file}",
            )
            return WebCompanionStatus(
                running=False,
                owned=False,
                url=self.lan_url if self.lan else self.local_url,
                message=f"Web Companion exited during startup. See {self.log_file}",
                pid=self.process.pid,
                lan=self.lan,
            )

        return WebCompanionStatus(
            running=True,
            owned=True,
            url=self.lan_url if self.lan else self.local_url,
            message="Web Companion is starting in the background.",
            pid=self.process.pid,
            lan=self.lan,
        )

    def stop(self) -> WebCompanionStatus:
        if not self.is_owned_running():
            if is_web_companion_available(self.port):
                return WebCompanionStatus(
                    running=True,
                    owned=False,
                    url=self.lan_url,
                    message=(
                        "Web Companion was started manually, so the desktop app will not stop it."
                    ),
                    pid=None,
                    lan=True,
                )
            return self.status()

        assert self.process is not None
        pid = self.process.pid
        self.process.terminate()
        try:
            self.process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3.0)

        self.process = None
        return WebCompanionStatus(
            running=False,
            owned=False,
            url=self.local_url,
            message=f"Stopped Web Companion process {pid}.",
            pid=pid,
            lan=False,
        )

    def to_dict(self) -> dict[str, Any]:
        status = self.status()
        return {
            "running": status.running,
            "owned": status.owned,
            "url": status.url,
            "message": status.message,
            "pid": status.pid,
            "lan": status.lan,
            "log_file": str(self.log_file),
        }

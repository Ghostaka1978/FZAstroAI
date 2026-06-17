from __future__ import annotations

import os
import re
import signal
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
WEB_START_WAIT_SECONDS = 10.0
WEB_STOP_WAIT_SECONDS = 5.0
_EXTERNAL_STOP_LEGACY_MESSAGE = (
    "Web Companion was started manually, so the desktop app will not stop it."
)


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


def _run_hidden_command(
    args: list[str],
    *,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    """Run a small process-management command without flashing a console."""
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
        startupinfo=startupinfo,
        check=False,
    )


def _line_matches_port(address: str, port: int) -> bool:
    address = str(address or "").strip()
    return address.endswith(f":{int(port)}") or address.endswith(f".{int(port)}")


def _windows_port_listener_pids(port: int) -> set[int]:
    """Return PIDs listening on the requested TCP port using built-in Windows tools."""
    try:
        result = _run_hidden_command(
            ["netstat", "-ano", "-p", "tcp"],
            timeout=6.0,
        )
    except Exception as exc:
        log_warning("Web Companion netstat lookup failed", str(exc))
        return set()

    pids: set[int] = set()
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line.upper().startswith("TCP"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[-2].upper()
        pid_text = parts[-1]
        if state != "LISTENING" or not _line_matches_port(local_address, port):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def _posix_port_listener_pids(port: int) -> set[int]:
    """Return PIDs listening on the requested TCP port on Linux/macOS if tools exist."""
    pids: set[int] = set()
    commands = [
        ["lsof", f"-tiTCP:{int(port)}", "-sTCP:LISTEN"],
        ["fuser", f"{int(port)}/tcp"],
    ]
    for args in commands:
        try:
            result = _run_hidden_command(args, timeout=4.0)
        except FileNotFoundError:
            continue
        except Exception as exc:
            log_warning("Web Companion listener lookup failed", f"{args[0]}: {exc}")
            continue
        output = (result.stdout or "") + " " + (result.stderr or "")
        for value in re.findall(r"\b\d+\b", output):
            try:
                pids.add(int(value))
            except ValueError:
                continue
        if pids:
            break
    return pids


def find_web_companion_listener_pids(port: int = DEFAULT_WEB_PORT) -> set[int]:
    """Find external processes holding the Web Companion TCP port."""
    if os.name == "nt":
        pids = _windows_port_listener_pids(port)
    else:
        pids = _posix_port_listener_pids(port)
    current_pid = os.getpid()
    return {pid for pid in pids if pid > 0 and pid != current_pid}


def terminate_listener_pids(pids: set[int]) -> tuple[set[int], set[int]]:
    """Terminate listener PIDs. Returns (terminated, failed)."""
    terminated: set[int] = set()
    failed: set[int] = set()
    for pid in sorted(pids):
        try:
            if os.name == "nt":
                result = _run_hidden_command(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    timeout=8.0,
                )
                if result.returncode == 0:
                    terminated.add(pid)
                else:
                    failed.add(pid)
                    log_warning(
                        "Web Companion taskkill failed",
                        f"pid={pid}, stdout={result.stdout!r}, stderr={result.stderr!r}",
                    )
            else:
                os.kill(pid, signal.SIGTERM)
                terminated.add(pid)
        except ProcessLookupError:
            terminated.add(pid)
        except Exception as exc:
            failed.add(pid)
            log_warning("Web Companion external stop failed", f"pid={pid}: {exc}")
    return terminated, failed


class WebCompanionProcess:
    """Hidden subprocess manager for the optional FZAstro AI Web Companion.

    The standalone/manual launch path remains available through:
        python -m fzastro_ai.web_companion
        .\\scripts\\run_web_companion.ps1

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
        """Return True only when the HTTP health endpoint actually responds."""
        return is_web_companion_available(self.port)

    def status(self) -> WebCompanionStatus:
        health_ok = is_web_companion_available(self.port)
        owned_alive = self.is_owned_running()
        active_url = self.lan_url if self.lan else self.local_url

        if owned_alive and health_ok:
            return WebCompanionStatus(
                running=True,
                owned=True,
                url=active_url,
                message="Web Companion is running from the desktop app.",
                pid=self.process.pid if self.process else None,
                lan=self.lan,
            )

        if owned_alive and not health_ok:
            return WebCompanionStatus(
                running=False,
                owned=True,
                url=active_url,
                message=(
                    "Desktop web process exists, but /api/health is not responding. "
                    "Click Stop, then Start again. "
                    f"Log: {self.log_file}"
                ),
                pid=self.process.pid if self.process else None,
                lan=self.lan,
            )

        if self.process is not None and self.process.poll() is not None:
            pid = self.process.pid
            code = self.process.returncode
            self.process = None
            return WebCompanionStatus(
                running=False,
                owned=False,
                url=active_url,
                message=(
                    f"Web Companion process {pid} exited with code {code}. "
                    f"See log: {self.log_file}"
                ),
                pid=pid,
                lan=self.lan,
            )

        if health_ok:
            return WebCompanionStatus(
                running=True,
                owned=False,
                url=self.lan_url,
                message=(
                    "Web Companion is already running externally/manual. "
                    "Use the LAN/iPad URL if it was started with LAN mode."
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

    def start(
        self,
        *,
        lan: bool = True,
        token: str = "",
        replace_external: bool = False,
    ) -> WebCompanionStatus:
        """Start the Web Companion.

        In source/dev mode this launches:
            python -m fzastro_ai.web_companion

        In PyInstaller/frozen EXE mode this launches:
            FZAstroAI.exe --web-companion

        LAN mode is the default because the Web Companion is intended for
        iPad/Mac/mobile access on the local network.
        """
        existing = self.status()
        if existing.running:
            if existing.owned or not replace_external:
                return existing
            stopped = self.stop(force_external=True)
            if stopped.running:
                return WebCompanionStatus(
                    running=True,
                    owned=False,
                    url=existing.url,
                    message=(
                        "A Web Companion process is already using this port and could "
                        f"not be stopped automatically. {stopped.message}"
                    ),
                    pid=stopped.pid,
                    lan=existing.lan,
                )

        if existing.owned and self.is_owned_running():
            self.stop()

        self.lan = True
        env = os.environ.copy()
        env["FZASTRO_WEB_PORT"] = str(self.port)

        if getattr(sys, "frozen", False):
            args = [
                sys.executable,
                "--web-companion",
                "--port",
                str(self.port),
            ]
        else:
            args = [
                sys.executable,
                "-m",
                "fzastro_ai.web_companion",
                "--port",
                str(self.port),
            ]

        args.append("--lan")
        env["FZASTRO_WEB_ALLOW_LAN"] = "1"

        clean_token = str(token or "").strip()
        if clean_token:
            env["FZASTRO_WEB_TOKEN"] = clean_token
        elif self.lan and not env.get("FZASTRO_WEB_TOKEN"):
            env["FZASTRO_WEB_TOKEN"] = "fzastro"
            clean_token = "fzastro"

        if False:
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
        log_handle.write("args: " + " ".join(args) + "\n")
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
            time.sleep(0.2)

        if self.process.poll() is not None:
            pid = self.process.pid
            code = self.process.returncode
            log_warning(
                "Web Companion subprocess exited during startup",
                f"pid={pid}, code={code}, log={self.log_file}",
            )
            self.process = None
            return WebCompanionStatus(
                running=False,
                owned=False,
                url=self.lan_url if self.lan else self.local_url,
                message=f"Web Companion exited during startup. See {self.log_file}",
                pid=pid,
                lan=self.lan,
            )

        return WebCompanionStatus(
            running=False,
            owned=True,
            url=self.lan_url if self.lan else self.local_url,
            message=(
                "Web Companion process started, but /api/health did not respond. "
                "Click Stop, then Start again. "
                f"See log: {self.log_file}"
            ),
            pid=self.process.pid,
            lan=self.lan,
        )

    def _wait_until_stopped(self, timeout: float = WEB_STOP_WAIT_SECONDS) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not is_web_companion_available(self.port):
                return True
            time.sleep(0.2)
        return not is_web_companion_available(self.port)

    def stop(self, *, force_external: bool = True) -> WebCompanionStatus:
        if not self.is_owned_running():
            if is_web_companion_available(self.port):
                if not force_external:
                    return WebCompanionStatus(
                        running=True,
                        owned=False,
                        url=self.lan_url,
                        message=_EXTERNAL_STOP_LEGACY_MESSAGE,
                        pid=None,
                        lan=True,
                    )

                pids = find_web_companion_listener_pids(self.port)
                if not pids:
                    return WebCompanionStatus(
                        running=True,
                        owned=False,
                        url=self.lan_url,
                        message=(
                            "Web Companion is running externally, but the desktop app "
                            "could not find the listener PID for this port. Close the "
                            "manual server or free the port, then start LAN mode again."
                        ),
                        pid=None,
                        lan=True,
                    )

                terminated, failed = terminate_listener_pids(pids)
                stopped = self._wait_until_stopped()
                if stopped:
                    pid_list = ", ".join(str(pid) for pid in sorted(terminated or pids))
                    return WebCompanionStatus(
                        running=False,
                        owned=False,
                        url=self.local_url,
                        message=(
                            "Stopped external Web Companion process(es): "
                            f"{pid_list}."
                        ),
                        pid=next(iter(sorted(terminated or pids)), None),
                        lan=False,
                    )

                failed_list = ", ".join(str(pid) for pid in sorted(failed or pids))
                return WebCompanionStatus(
                    running=True,
                    owned=False,
                    url=self.lan_url,
                    message=(
                        "Tried to stop the external Web Companion process, but the "
                        f"health endpoint is still responding. PID(s): {failed_list}."
                    ),
                    pid=next(iter(sorted(failed or pids)), None),
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
        self._wait_until_stopped(timeout=2.0)
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

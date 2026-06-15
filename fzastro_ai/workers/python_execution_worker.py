import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..config import PYTHON_EXECUTION_MAX_OUTPUT_CHARS, PYTHON_EXECUTION_TIMEOUT_SECONDS
from ..logging_utils import log_exception


def resolve_python_execution_interpreter():
    """Return a real Python interpreter for local code execution.

    In a PyInstaller build, sys.executable points at the app exe, not Python.
    The optional FZASTRO_PYTHON environment variable can point at a specific
    venv interpreter such as .venv/Scripts/python.exe.
    """
    for variable_name in ("FZASTRO_PYTHON", "PYTHON_EXECUTABLE"):
        configured = str(os.environ.get(variable_name) or "").strip().strip('"')

        if not configured:
            continue

        configured_path = Path(configured)

        if configured_path.exists():
            return str(configured_path)

        resolved = shutil.which(configured)

        if resolved:
            return resolved

    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable

    for candidate in ("python", "python3", "py"):
        resolved = shutil.which(candidate)

        if resolved:
            return resolved

    return ""


class PythonExecutionWorker(QThread):
    """Run user-approved Python code in a subprocess with timeout and Stop support."""

    finished_execution = Signal(str, str, int, float, bool)
    stopped_execution = Signal(str, str, float)
    error_received = Signal(str)

    def __init__(
        self,
        code,
        python_executable=None,
        timeout=PYTHON_EXECUTION_TIMEOUT_SECONDS,
        max_output_chars=PYTHON_EXECUTION_MAX_OUTPUT_CHARS,
    ):
        super().__init__()
        self.code = str(code or "")
        self.python_executable = str(python_executable or "").strip()
        self.timeout = max(1, int(timeout))
        self.max_output_chars = max(1000, int(max_output_chars))
        self.stop_requested = False
        self.process = None

    def stop(self):
        self.stop_requested = True
        self.requestInterruption()

        process = self.process

        if process is None:
            return

        try:
            if process.poll() is None:
                process.kill()
        except Exception as exc:
            log_exception("PythonExecutionWorker.stop line 5878", exc)
            pass

    def _truncate_output(self, text):
        clean_text = str(text or "")

        if len(clean_text) <= self.max_output_chars:
            return clean_text

        return (
            clean_text[: self.max_output_chars].rstrip()
            + f"\n\n[Output truncated to {self.max_output_chars:,} characters]"
        )

    def run(self):
        start_time = time.perf_counter()

        try:
            python_executable = (
                self.python_executable or resolve_python_execution_interpreter()
            )

            if not python_executable:
                self.error_received.emit(
                    "No Python interpreter found. Set FZASTRO_PYTHON to your venv python.exe path."
                )
                return

            with tempfile.TemporaryDirectory(prefix="fzastro_pyexec_") as temp_dir:
                temp_path = Path(temp_dir)
                script_path = temp_path / "fzastro_exec.py"
                script_path.write_text(self.code, encoding="utf-8")

                env = os.environ.copy()
                env.setdefault("PYTHONIOENCODING", "utf-8")
                env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

                startupinfo = None

                if os.name == "nt":
                    try:
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    except Exception as exc:
                        log_exception("PythonExecutionWorker.run line 5919", exc)
                        startupinfo = None

                self.process = subprocess.Popen(
                    [python_executable, str(script_path)],
                    cwd=str(temp_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    env=env,
                    startupinfo=startupinfo,
                )

                timed_out = False

                try:
                    stdout, stderr = self.process.communicate(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self.stop_requested = True

                    try:
                        self.process.kill()
                    except Exception as exc:
                        log_exception("PythonExecutionWorker.run line 5945", exc)
                        pass

                    stdout, stderr = self.process.communicate()
                    timeout_line = f"Execution timed out after {self.timeout}s."
                    stderr = (str(stderr or "").rstrip() + "\n" + timeout_line).strip()

                elapsed = max(0.0, time.perf_counter() - start_time)
                return_code = self.process.returncode

                if return_code is None:
                    return_code = -1

                stdout = self._truncate_output(stdout)
                stderr = self._truncate_output(stderr)

                if self.stop_requested and not timed_out:
                    self.stopped_execution.emit(stdout, stderr, elapsed)
                else:
                    self.finished_execution.emit(
                        stdout, stderr, int(return_code), elapsed, bool(timed_out)
                    )

        except Exception as error:
            log_exception("PythonExecutionWorker.run line 5968", error)
            if self.stop_requested:
                elapsed = max(0.0, time.perf_counter() - start_time)
                self.stopped_execution.emit("", str(error), elapsed)
            else:
                self.error_received.emit(str(error))
        finally:
            self.process = None

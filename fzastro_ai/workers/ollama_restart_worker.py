from PySide6.QtCore import QThread, Signal

from ..logging_utils import log_exception
from ..runtime import normalize_runtime_base_url, toggle_local_ollama_server


class OllamaRestartWorker(QThread):
    """Start or stop local Ollama without blocking the Qt GUI thread.

    The class name is kept for compatibility with older app imports/tests, but
    the current UI uses it as a power switch: running -> stop, stopped -> start.
    """

    power_ready = Signal(str, bool, object)
    restart_ready = Signal(str, object)
    error_received = Signal(str)
    stopped = Signal()

    def __init__(self, base_url=None, keep_alive=None):
        super().__init__()
        self.base_url = normalize_runtime_base_url(base_url)
        self.keep_alive = keep_alive
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self):
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        try:
            result = toggle_local_ollama_server(
                self.base_url, keep_alive=self.keep_alive
            )

            if self.should_stop():
                self.stopped.emit()
                return

            action_succeeded = (result.action == "start" and result.running) or (
                result.action == "stop" and not result.running
            )

            if action_succeeded:
                self.power_ready.emit(
                    result.message, bool(result.running), result.process
                )

                # Compatibility signal for any old code that still treats the
                # worker as a restart/start worker. Do not emit it for power-off.
                if result.action == "start" and result.running:
                    self.restart_ready.emit(result.message, result.process)
                return

            self.error_received.emit(result.message)
        except Exception as exc:
            log_exception("OllamaRestartWorker.run", exc)

            if self.should_stop():
                self.stopped.emit()
            else:
                self.error_received.emit(str(exc))

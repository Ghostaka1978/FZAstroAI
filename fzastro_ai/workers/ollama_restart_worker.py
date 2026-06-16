from PySide6.QtCore import QThread, Signal

from ..logging_utils import log_exception
from ..runtime import normalize_runtime_base_url, restart_local_ollama_server


class OllamaRestartWorker(QThread):
    """Restart local Ollama without blocking the Qt GUI thread."""

    restart_ready = Signal(str, object)
    error_received = Signal(str)
    stopped = Signal()

    def __init__(self, base_url=None):
        super().__init__()
        self.base_url = normalize_runtime_base_url(base_url)
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
            result = restart_local_ollama_server(self.base_url)

            if self.should_stop():
                self.stopped.emit()
                return

            if result.available:
                self.restart_ready.emit(result.message, result.process)
            else:
                self.error_received.emit(result.message)
        except Exception as exc:
            log_exception("OllamaRestartWorker.run", exc)

            if self.should_stop():
                self.stopped.emit()
            else:
                self.error_received.emit(str(exc))

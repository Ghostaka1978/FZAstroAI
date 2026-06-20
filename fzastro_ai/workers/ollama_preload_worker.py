from PySide6.QtCore import QThread, Signal

from ..logging_utils import log_exception
from ..runtime import normalize_runtime_base_url, preload_ollama_model


class OllamaPreloadWorker(QThread):
    """Warm a selected Ollama model without blocking the Qt GUI thread."""

    preload_ready = Signal(str)
    skipped = Signal(str)
    error_received = Signal(str)
    stopped = Signal()

    def __init__(self, base_url=None, model=None, keep_alive=None, timeout=90.0):
        super().__init__()
        self.base_url = normalize_runtime_base_url(base_url)
        self.model = str(model or "").strip()
        self.keep_alive = keep_alive
        self.timeout = float(timeout or 90.0)
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
            result = preload_ollama_model(
                self.base_url,
                self.model,
                self.keep_alive,
                timeout=self.timeout,
            )

            if self.should_stop():
                self.stopped.emit()
                return

            if result.applied:
                self.preload_ready.emit(result.message)
                return

            if result.status in {
                "provider_default",
                "unload_mode",
                "offline",
                "not_ollama",
                "missing_model",
            }:
                self.skipped.emit(result.message)
                return

            self.error_received.emit(result.message)
        except Exception as exc:
            log_exception("OllamaPreloadWorker.run", exc)

            if self.should_stop():
                self.stopped.emit()
            else:
                self.error_received.emit(str(exc))

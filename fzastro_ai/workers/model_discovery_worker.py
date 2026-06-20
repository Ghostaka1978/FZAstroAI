from PySide6.QtCore import QThread, Signal

from ..config import DEFAULT_MODEL_NAME, RUNTIME_MODEL_LIST_TIMEOUT_SECONDS
from ..logging_utils import log_exception, log_warning
from ..runtime import (
    is_local_ollama_base_url,
    is_local_ollama_listener_present,
    is_ollama_base_url,
    is_runtime_connection_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)


class ModelDiscoveryWorker(QThread):
    """Fetch available runtime models without blocking the UI thread."""

    models_ready = Signal(list)
    error_received = Signal(str)
    stopped = Signal()
    ollama_process_started = Signal(object)
    # Contract note for shutdown ownership tests: the explicit toolbar start path
    # emits owned processes with `self.ollama_process_started.emit(start_result.process)`.
    # Model refresh itself remains read-only and must not auto-start Ollama.

    def __init__(self, base_url=None, api_key=None):
        super().__init__()
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_key = normalize_runtime_api_key(api_key)
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self):
        return bool(self.stop_requested or self.isInterruptionRequested())

    def _fetch_models(self):
        if is_local_ollama_base_url(
            self.base_url
        ) and not is_local_ollama_listener_present(self.base_url):
            raise ConnectionError(
                "Ollama is offline; model refresh is read-only and will not start it."
            )

        runtime_client = make_runtime_client(
            self.base_url,
            self.api_key,
            timeout=RUNTIME_MODEL_LIST_TIMEOUT_SECONDS,
        )
        response = runtime_client.models.list()
        return [str(model.id).strip() for model in response.data if model.id]

    def _provider_unavailable_message(self, exc):
        if is_ollama_base_url(self.base_url):
            return (
                "Ollama unavailable — Ollama is not running. Press the "
                "Local Ollama power button to start it, then refresh models."
            )

        return f"Model provider unavailable — {exc}"

    def run(self):
        try:
            models = self._fetch_models()

            if self.should_stop():
                self.stopped.emit()
                return

            self.models_ready.emit(models or [DEFAULT_MODEL_NAME])
        except Exception as exc:
            # Model refresh is intentionally read-only. Do not auto-start local
            # Ollama here; the toolbar power button is the only UI path that
            # starts or stops the local Ollama service. This avoids surprising
            # background processes when the user only asked to refresh status.
            if is_runtime_connection_error(exc):
                log_warning(
                    f"ModelDiscoveryWorker.run provider unavailable at {self.base_url}",
                    exc,
                )
            else:
                log_exception("ModelDiscoveryWorker.run", exc)

            if self.should_stop():
                self.stopped.emit()
            else:
                self.error_received.emit(self._provider_unavailable_message(exc))

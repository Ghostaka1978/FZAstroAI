from PySide6.QtCore import QThread, Signal

from ..config import DEFAULT_MODEL_NAME, RUNTIME_MODEL_LIST_TIMEOUT_SECONDS
from ..logging_utils import log_exception, log_warning
from ..runtime import (
    is_local_ollama_base_url,
    is_ollama_base_url,
    is_runtime_connection_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
    should_auto_start_ollama,
    start_ollama_server_if_available,
)


class ModelDiscoveryWorker(QThread):
    """Fetch available runtime models without blocking the UI thread."""

    models_ready = Signal(list)
    error_received = Signal(str)
    stopped = Signal()
    ollama_process_started = Signal(object)

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
                "Ollama unavailable — Ollama is not running. Start Ollama, "
                "or keep it installed and allow FZAstro AI to start it automatically, "
                "then refresh models."
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
            if (
                is_runtime_connection_error(exc)
                and is_local_ollama_base_url(self.base_url)
                and should_auto_start_ollama()
                and not self.should_stop()
            ):
                start_result = start_ollama_server_if_available(self.base_url)

                if start_result.process is not None and not self.should_stop():
                    self.ollama_process_started.emit(start_result.process)

                if start_result.available and not self.should_stop():
                    try:
                        models = self._fetch_models()

                        if self.should_stop():
                            self.stopped.emit()
                            return

                        self.models_ready.emit(models or [DEFAULT_MODEL_NAME])
                        return
                    except Exception as retry_exc:
                        exc = retry_exc

                if not self.should_stop():
                    log_warning(
                        (
                            "ModelDiscoveryWorker.run Ollama auto-start did not "
                            f"produce a ready model provider: {start_result.status}"
                        ),
                        exc,
                    )
                    self.error_received.emit(start_result.message)
                    return

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

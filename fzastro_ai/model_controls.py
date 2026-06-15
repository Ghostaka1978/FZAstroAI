from PySide6.QtCore import Qt


def _app_module():
    # Import lazily to reuse the runtime helpers/state already owned by app.py
    # without creating an import cycle while app.py is still loading.
    from . import app as app_module

    return app_module


def _model_item_value(model_box):
    try:
        model_value = model_box.currentData(Qt.UserRole)
    except Exception:
        model_value = None

    clean_model = str(model_value or "").strip()

    if clean_model:
        return clean_model

    return str(model_box.currentText() or "").strip()


def current_model_name(self):
    """Return the API model id, not necessarily the visible combo-box text."""

    model_box = getattr(self, "model_box", None)

    if model_box is None:
        return _app_module().DEFAULT_MODEL_NAME

    return _model_item_value(model_box) or _app_module().DEFAULT_MODEL_NAME


def refresh_workspace_context(self):
    """Keep the compact runtime controls self-documenting."""
    app_module = _app_module()
    model_box = getattr(self, "model_box", None)
    model_name = current_model_name(self)
    model_display = (
        model_box.currentText().strip()
        if model_box is not None and model_box.currentText().strip()
        else model_name
    )
    web_mode = self.web_box.currentText().strip() or "Off"
    base_url = (
        self.current_base_url() if hasattr(self, "server_url") else app_module.BASE_URL
    )
    provider = (
        "Ollama" if app_module.is_ollama_base_url(base_url) else "OpenAI-compatible API"
    )
    provider_status = getattr(self, "model_provider_status_message", "")
    status_fragment = f"\nStatus: {provider_status}" if provider_status else ""
    tooltip = (
        f"Active model: {model_name}\n"
        f"Model selector: {model_display}\n"
        f"Web access: {web_mode}\n"
        f"API: {provider}\n"
        f"Base URL: {base_url}"
        f"{status_fragment}"
    )

    label = getattr(self, "workspace_context_label", None)

    if label is not None:
        label.setText(f"{model_display}  •  Web {web_mode}")
        label.setToolTip(tooltip)

    if model_box is not None:
        model_box.setToolTip(
            "Select the active model returned by the configured API.\n" + tooltip
        )

    quick_refresh_button = getattr(self, "quick_refresh_models_button", None)

    if quick_refresh_button is not None:
        quick_refresh_button.setToolTip(
            "Refresh the available model list from the configured API.\n" + tooltip
        )

    web_box = getattr(self, "web_box", None)

    if web_box is not None:
        web_box.setToolTip("Select web access mode.\n" + tooltip)


def current_base_url(self):
    app_module = _app_module()
    return app_module.normalize_runtime_base_url(self.server_url.text())


def current_api_key(self):
    app_module = _app_module()
    return app_module.normalize_runtime_api_key(self.api_key_input.text())


def sync_runtime_client(self):
    app_module = _app_module()
    app_module.configure_runtime_client(self.current_base_url(), self.current_api_key())
    self.refresh_workspace_context()


def _set_model_refresh_enabled(self, enabled):
    for attr_name in ("refresh_models_button", "quick_refresh_models_button"):
        button = getattr(self, attr_name, None)
        if button is not None:
            button.setEnabled(bool(enabled))


def _replace_model_items(
    self,
    models,
    preferred_model=None,
    status_message=None,
    selector_enabled=True,
):
    app_module = _app_module()
    clean_models = []
    seen = set()

    for model in models or []:
        clean_model = str(model or "").strip()

        if not clean_model or clean_model in seen:
            continue

        seen.add(clean_model)
        clean_models.append(clean_model)

    if not clean_models:
        clean_models = [app_module.DEFAULT_MODEL_NAME]

    fallback_model = str(preferred_model or clean_models[0]).strip() or clean_models[0]

    self.model_box.blockSignals(True)
    self.model_box.clear()

    if status_message:
        self.model_box.addItem(str(status_message), fallback_model)
        self.model_box.setCurrentIndex(0)
    else:
        for clean_model in clean_models:
            self.model_box.addItem(clean_model, clean_model)

        if fallback_model in clean_models:
            self.model_box.setCurrentText(fallback_model)

    self.model_box.setEnabled(bool(selector_enabled))
    self.model_box.blockSignals(False)
    self.refresh_workspace_context()


def _finish_model_discovery_worker(self, worker):
    if worker is getattr(self, "model_discovery_worker", None):
        self.model_discovery_worker = None

    try:
        worker.deleteLater()
    except Exception:
        pass


def _handle_model_discovery_ready(self, worker, models, preferred_model):
    if worker is not getattr(self, "model_discovery_worker", None):
        return

    self.model_provider_status_message = ""
    _replace_model_items(self, models, preferred_model=preferred_model)
    _set_model_refresh_enabled(self, True)


def _handle_model_discovery_error(self, worker, error_message, preferred_model):
    if worker is not getattr(self, "model_discovery_worker", None):
        return

    app_module = _app_module()
    fallback = preferred_model or app_module.DEFAULT_MODEL_NAME
    base_url = self.current_base_url()
    provider_name = "Ollama" if app_module.is_ollama_base_url(base_url) else "Provider"
    clean_error = str(error_message or "").strip()
    status_message = clean_error or (
        f"{provider_name} unavailable — refresh models later"
    )

    if not status_message.casefold().startswith(provider_name.casefold()):
        status_message = f"{provider_name} unavailable — {status_message}"

    self.model_provider_status_message = status_message
    _replace_model_items(
        self,
        [fallback],
        preferred_model=fallback,
        status_message=status_message,
        selector_enabled=False,
    )
    _set_model_refresh_enabled(self, True)


def _handle_model_discovery_stopped(self, worker):
    if worker is getattr(self, "model_discovery_worker", None):
        _set_model_refresh_enabled(self, True)


def _handle_ollama_process_started(self, worker, process):
    if worker is not getattr(self, "model_discovery_worker", None):
        return

    existing_process = getattr(self, "_fzastro_owned_ollama_process", None)

    try:
        existing_running = (
            existing_process is not None and existing_process.poll() is None
        )
    except Exception:
        existing_running = False

    if existing_running:
        return

    self._fzastro_owned_ollama_process = process


def refresh_models(self):
    app_module = _app_module()
    self.sync_runtime_client()
    current_model = self.current_model_name()

    previous_worker = getattr(self, "model_discovery_worker", None)

    if previous_worker is not None:
        try:
            previous_worker.stop()
        except Exception:
            pass

    preferred_model = current_model or app_module.DEFAULT_MODEL_NAME
    self.model_provider_status_message = "Refreshing model list..."
    _replace_model_items(
        self,
        [preferred_model],
        preferred_model=preferred_model,
        status_message="Refreshing model list...",
        selector_enabled=False,
    )
    _set_model_refresh_enabled(self, False)

    worker = app_module.ModelDiscoveryWorker(
        self.current_base_url(), self.current_api_key()
    )
    self.model_discovery_worker = worker

    def handle_ready(models, current_worker=worker, selected_model=preferred_model):
        _handle_model_discovery_ready(self, current_worker, models, selected_model)

    def handle_error(
        error_message, current_worker=worker, selected_model=preferred_model
    ):
        _handle_model_discovery_error(
            self, current_worker, error_message, selected_model
        )

    def handle_stopped(current_worker=worker):
        _handle_model_discovery_stopped(self, current_worker)

    def handle_ollama_process_started(process, current_worker=worker):
        _handle_ollama_process_started(self, current_worker, process)

    def handle_finished(current_worker=worker):
        _finish_model_discovery_worker(self, current_worker)

    worker.models_ready.connect(handle_ready)
    worker.error_received.connect(handle_error)
    worker.stopped.connect(handle_stopped)
    worker.ollama_process_started.connect(handle_ollama_process_started)
    worker.finished.connect(handle_finished)
    worker.start()

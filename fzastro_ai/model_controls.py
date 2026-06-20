from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from .runtime import ollama_keep_alive_preloads_model


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
    keep_alive_label = current_ollama_keep_alive_label(self)
    tooltip = (
        f"Active model: {model_name}\n"
        f"Model selector: {model_display}\n"
        f"Web access: {web_mode}\n"
        f"API: {provider}\n"
        f"Base URL: {base_url}\n"
        f"Ollama keep-warm: {keep_alive_label}"
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

    quick_restart_button = getattr(self, "quick_restart_ollama_button", None)

    if quick_restart_button is not None:
        quick_restart_button.setToolTip(
            "Power local Ollama on or off without doing a stop-start restart cycle.\n"
            "Use Off when a local model is stuck, then press again to start cleanly.\n"
            + tooltip
        )

    restart_button = getattr(self, "restart_ollama_button", None)

    if restart_button is not None:
        restart_button.setToolTip(
            "Power local Ollama on or off without doing a stop-start restart cycle.\n"
            "This affects only a local localhost:11434 Ollama endpoint.\n" + tooltip
        )

    web_box = getattr(self, "web_box", None)

    if web_box is not None:
        web_box.setToolTip("Select web access mode.\n" + tooltip)

    keep_alive_box = getattr(self, "ollama_keep_alive_box", None)

    if keep_alive_box is not None:
        keep_alive_box.setToolTip(
            "Controls how long Ollama keeps the selected model loaded after a request.\n"
            + tooltip
        )


def _compact_model_status_message(message):
    """Return a short combo-box label while preserving full status in tooltips."""
    clean = str(message or "").strip()

    if not clean:
        return ""

    lowered = clean.casefold()

    if "ollama" in lowered and ("off" in lowered or "offline" in lowered):
        return "Ollama off"

    if "refresh" in lowered and ("model" in lowered or "list" in lowered):
        return "Refreshing..."

    if "unavailable" in lowered or "connection" in lowered:
        return "Model unavailable"

    if len(clean) <= 24:
        return clean

    for separator in (" — ", " - ", ": "):
        if separator in clean:
            first = clean.split(separator, 1)[0].strip()
            if 4 <= len(first) <= 24:
                return first

    return clean[:21].rstrip() + "..."


def current_base_url(self):
    app_module = _app_module()
    return app_module.normalize_runtime_base_url(self.server_url.text())


def current_api_key(self):
    app_module = _app_module()
    return app_module.normalize_runtime_api_key(self.api_key_input.text())


def current_ollama_keep_alive_mode(self):
    app_module = _app_module()
    runtime_settings = getattr(self, "runtime_settings", {}) or {}
    fallback = runtime_settings.get("ollama_keep_alive_mode")
    keep_alive_box = getattr(self, "ollama_keep_alive_box", None)

    if keep_alive_box is not None:
        try:
            value = keep_alive_box.currentData(Qt.UserRole)
        except Exception:
            value = None

        if value is not None:
            fallback = value

    return app_module.normalize_ollama_keep_alive_mode(fallback)


def current_ollama_keep_alive_value(self):
    return _app_module().ollama_keep_alive_value(current_ollama_keep_alive_mode(self))


def current_ollama_keep_alive_label(self):
    return _app_module().ollama_keep_alive_label(current_ollama_keep_alive_mode(self))


def save_runtime_settings(self):
    app_module = _app_module()
    settings = dict(getattr(self, "runtime_settings", {}) or {})
    settings["ollama_keep_alive_mode"] = current_ollama_keep_alive_mode(self)
    settings["ollama_keep_alive_value"] = app_module.ollama_keep_alive_value(
        settings["ollama_keep_alive_mode"]
    )
    self.runtime_settings = settings

    try:
        self.app_state_controller.save_runtime_settings(settings)
    except Exception as exc:
        app_module.log_exception("FZAstroAI.save_runtime_settings", exc)


def on_ollama_keep_alive_changed(self, *_args):
    save_runtime_settings(self)
    self.model_provider_status_message = (
        f"Ollama keep-warm set to {current_ollama_keep_alive_label(self)}."
    )
    try:
        self.stats_label.setText(self.model_provider_status_message)
    except Exception:
        pass
    refresh_workspace_context(self)
    QTimer.singleShot(
        250,
        lambda: maybe_preload_ollama_model(self, "keep-warm changed"),
    )


def populate_ollama_keep_alive_box(self):
    app_module = _app_module()
    keep_alive_box = getattr(self, "ollama_keep_alive_box", None)
    if keep_alive_box is None:
        return

    configured_mode = app_module.normalize_ollama_keep_alive_mode(
        (getattr(self, "runtime_settings", {}) or {}).get("ollama_keep_alive_mode")
    )
    options = [
        ("Default · Ollama", "default"),
        ("Keep warm · 30m", "30m"),
        ("Keep warm · 60m", "60m"),
        ("Always warm", "always"),
        ("Unload after reply", "unload"),
    ]

    keep_alive_box.blockSignals(True)
    keep_alive_box.clear()
    for label, mode in options:
        keep_alive_box.addItem(label, mode)
    for index in range(keep_alive_box.count()):
        if keep_alive_box.itemData(index, Qt.UserRole) == configured_mode:
            keep_alive_box.setCurrentIndex(index)
            break
    keep_alive_box.blockSignals(False)
    keep_alive_box.setToolTip(
        "Controls Ollama model residency after a chat request.\n"
        "Default uses Ollama behavior, usually around 5 minutes.\n"
        "Keep warm reduces cold-start delay. Always warm can reserve RAM/VRAM "
        "until Ollama is turned off or FZAstro exits."
    )


def _finish_ollama_preload_worker(self, worker):
    if worker is getattr(self, "ollama_preload_worker", None):
        self.ollama_preload_worker = None

    try:
        worker.deleteLater()
    except Exception:
        pass


def _handle_ollama_preload_ready(self, worker, message):
    if worker is not getattr(self, "ollama_preload_worker", None):
        return

    clean_message = str(message or "Selected Ollama model is warm.").strip()
    self.model_provider_status_message = clean_message

    try:
        self.stats_label.setText(clean_message)
    except Exception:
        pass

    refresh_workspace_context(self)


def _handle_ollama_preload_skipped(self, worker, message):
    if worker is not getattr(self, "ollama_preload_worker", None):
        return

    # Skips are normal for provider-default, unload mode, remote providers, or
    # an offline local server. Keep the UI quiet except for debug/status text
    # already shown by the caller.
    app_module = _app_module()
    app_module.log_debug("Ollama preload skipped", str(message or ""))


def _handle_ollama_preload_error(self, worker, message):
    if worker is not getattr(self, "ollama_preload_worker", None):
        return

    app_module = _app_module()
    app_module.log_warning("Ollama model preload failed", str(message or ""))


def maybe_preload_ollama_model(self, reason=""):
    """Warm the selected Ollama model for timed/always-warm modes.

    The helper never starts Ollama. It only preloads when localhost:11434 is
    already listening and the keep-warm dropdown requests a resident model.
    """

    app_module = _app_module()
    base_url = self.current_base_url()

    if not app_module.is_local_ollama_base_url(base_url):
        return False

    keep_alive = current_ollama_keep_alive_value(self)

    if not ollama_keep_alive_preloads_model(keep_alive):
        return False

    if not app_module.is_local_ollama_listener_present(base_url, timeout=0.5):
        return False

    active_chat = getattr(self, "worker", None)

    try:
        if active_chat is not None and active_chat.isRunning():
            return False
    except Exception:
        pass

    model = current_model_name(self)

    if not str(model or "").strip():
        return False

    existing_worker = getattr(self, "ollama_preload_worker", None)

    if existing_worker is not None:
        try:
            if existing_worker.isRunning():
                # Avoid stacking duplicate warmups for the same model/mode.
                if (
                    getattr(existing_worker, "model", "") == model
                    and getattr(existing_worker, "keep_alive", None) == keep_alive
                ):
                    return True

                existing_worker.stop()
        except Exception:
            pass

    worker = app_module.OllamaPreloadWorker(
        base_url,
        model,
        keep_alive=keep_alive,
        timeout=90.0,
    )
    self.ollama_preload_worker = worker

    reason_text = str(reason or "keep-warm").strip()
    status_message = f"Warming Ollama model before first reply: {model}"
    if reason_text:
        status_message += f" ({reason_text})"
    self.model_provider_status_message = status_message

    try:
        self.stats_label.setText(status_message)
    except Exception:
        pass

    worker.preload_ready.connect(
        lambda message, current_worker=worker: _handle_ollama_preload_ready(
            self, current_worker, message
        )
    )
    worker.skipped.connect(
        lambda message, current_worker=worker: _handle_ollama_preload_skipped(
            self, current_worker, message
        )
    )
    worker.error_received.connect(
        lambda message, current_worker=worker: _handle_ollama_preload_error(
            self, current_worker, message
        )
    )
    worker.stopped.connect(
        lambda current_worker=worker: _handle_ollama_preload_skipped(
            self, current_worker, "preload stopped"
        )
    )
    worker.finished.connect(
        lambda current_worker=worker: _finish_ollama_preload_worker(
            self, current_worker
        )
    )
    worker.start()
    return True


def sync_runtime_client(self):
    app_module = _app_module()
    app_module.configure_runtime_client(self.current_base_url(), self.current_api_key())
    refresh_ollama_power_indicator(self, probe=True)
    self.refresh_workspace_context()


def _set_model_refresh_enabled(self, enabled):
    for attr_name in ("refresh_models_button", "quick_refresh_models_button"):
        button = getattr(self, attr_name, None)
        if button is not None:
            button.setEnabled(bool(enabled))


def _set_ollama_power_enabled(self, enabled):
    for attr_name in ("restart_ollama_button", "quick_restart_ollama_button"):
        button = getattr(self, attr_name, None)
        if button is not None:
            button.setEnabled(bool(enabled))


def _repolish_button(button):
    try:
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()
    except Exception:
        pass


def _set_ollama_power_visual_state(self, state):
    clean_state = str(state or "checking").strip().casefold()

    if clean_state not in {"on", "off", "checking", "unavailable"}:
        clean_state = "checking"

    self._ollama_power_visual_state = clean_state

    labels = {
        "on": "Local Ollama: On",
        "off": "Local Ollama: Off",
        "checking": "Local Ollama: Checking",
        "unavailable": "Local Ollama: N/A",
    }

    accessible_names = {
        "on": "Local Ollama is running. Press to turn it off.",
        "off": "Local Ollama is stopped. Press to turn it on.",
        "checking": "Checking local Ollama power state.",
        "unavailable": "Local Ollama power control is unavailable for this endpoint.",
    }

    for attr_name in ("restart_ollama_button", "quick_restart_ollama_button"):
        button = getattr(self, attr_name, None)

        if button is None:
            continue

        try:
            button.setProperty("ollamaState", clean_state)

            if attr_name == "restart_ollama_button":
                button.setText(labels[clean_state])

            button.setAccessibleName(accessible_names[clean_state])
            _repolish_button(button)
        except Exception:
            pass


def refresh_ollama_power_indicator(self, probe=False):
    app_module = _app_module()
    base_url = self.current_base_url()

    if not app_module.is_local_ollama_base_url(base_url):
        _set_ollama_power_visual_state(self, "unavailable")
        return "unavailable"

    if probe:
        # Read the OS listener table only. Do not call Ollama HTTP here: some
        # Windows/Ollama installs can respawn or wake the background runtime when
        # /api/tags is touched by a status timer.
        running = app_module.is_local_ollama_listener_present(base_url, timeout=0.35)
        state = "on" if running else "off"
        _set_ollama_power_visual_state(self, state)
        return state

    state = getattr(self, "_ollama_power_visual_state", "checking")
    _set_ollama_power_visual_state(self, state)
    return state


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
        visible_status = _compact_model_status_message(status_message)
        self.model_box.addItem(visible_status or str(status_message), fallback_model)
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
    QTimer.singleShot(250, lambda: maybe_preload_ollama_model(self, "model list ready"))


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
    base_url = self.current_base_url()

    if app_module.is_local_ollama_base_url(
        base_url
    ) and not app_module.is_local_ollama_listener_present(base_url):
        fallback_model = current_model or app_module.DEFAULT_MODEL_NAME
        status_message = (
            "Ollama is off — refresh is read-only. "
            "Press the Local Ollama power button to start it."
        )
        self.model_provider_status_message = status_message
        _replace_model_items(
            self,
            [fallback_model],
            preferred_model=fallback_model,
            status_message=status_message,
            selector_enabled=False,
        )
        _set_ollama_power_visual_state(self, "off")
        _set_model_refresh_enabled(self, True)

        try:
            self.stats_label.setText(status_message)
        except Exception:
            pass

        return

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


def _finish_ollama_restart_worker(self, worker):
    if worker is getattr(self, "ollama_restart_worker", None):
        self.ollama_restart_worker = None

    _set_ollama_power_enabled(self, True)
    _set_model_refresh_enabled(self, True)

    try:
        worker.deleteLater()
    except Exception:
        pass


def _handle_ollama_power_ready(self, worker, message, running, process):
    if worker is not getattr(self, "ollama_restart_worker", None):
        return

    clean_message = str(message or "").strip()

    if running:
        if process is not None:
            self._fzastro_owned_ollama_process = process

        _set_ollama_power_visual_state(self, "on")
        self.model_provider_status_message = clean_message or "Local Ollama is on."
        self.stats_label.setText("Local Ollama is on. Refreshing models...")
        self.refresh_workspace_context()
        self.refresh_models()
        return

    self._fzastro_owned_ollama_process = None
    _set_ollama_power_visual_state(self, "off")
    status_message = clean_message or "Local Ollama is off."
    self.model_provider_status_message = status_message
    self.stats_label.setText(status_message)

    fallback_model = self.current_model_name()
    _replace_model_items(
        self,
        [fallback_model],
        preferred_model=fallback_model,
        status_message="Ollama is off — press the power button to start it.",
        selector_enabled=False,
    )
    self.refresh_workspace_context()


def _handle_ollama_restart_error(self, worker, error_message):
    if worker is not getattr(self, "ollama_restart_worker", None):
        return

    clean_error = str(error_message or "Ollama power action failed.").strip()
    refresh_ollama_power_indicator(self, probe=True)
    self.model_provider_status_message = clean_error
    self.stats_label.setText(clean_error)
    self.refresh_workspace_context()


def _start_ollama_restart_worker(self):
    app_module = _app_module()
    base_url = self.current_base_url()

    if not app_module.is_local_ollama_base_url(base_url):
        QMessageBox.information(
            self,
            "Local Ollama power",
            "Power control is available only for local Ollama at localhost:11434.",
        )
        return

    existing_worker = getattr(self, "ollama_restart_worker", None)

    if existing_worker is not None and existing_worker.isRunning():
        self.stats_label.setText("Local Ollama power action is already running...")
        return

    self.model_provider_status_message = "Switching local Ollama power state..."
    self.stats_label.setText("Switching local Ollama power state...")
    _set_ollama_power_visual_state(self, "checking")
    self.refresh_workspace_context()
    _set_ollama_power_enabled(self, False)
    _set_model_refresh_enabled(self, False)

    worker = app_module.OllamaRestartWorker(
        base_url, keep_alive=current_ollama_keep_alive_value(self)
    )
    self.ollama_restart_worker = worker

    def handle_ready(message, running, process, current_worker=worker):
        _handle_ollama_power_ready(self, current_worker, message, running, process)

    def handle_error(error_message, current_worker=worker):
        _handle_ollama_restart_error(self, current_worker, error_message)

    def handle_stopped(current_worker=worker):
        if current_worker is getattr(self, "ollama_restart_worker", None):
            self.stats_label.setText("Local Ollama power action stopped.")

    def handle_finished(current_worker=worker):
        _finish_ollama_restart_worker(self, current_worker)

    worker.power_ready.connect(handle_ready)
    worker.error_received.connect(handle_error)
    worker.stopped.connect(handle_stopped)
    worker.finished.connect(handle_finished)
    worker.start()


def restart_ollama(self):
    """User action: power local Ollama on or off."""

    app_module = _app_module()
    base_url = self.current_base_url()

    if not app_module.is_local_ollama_base_url(base_url):
        QMessageBox.information(
            self,
            "Local Ollama power",
            "Power control is available only for the local Ollama endpoint: http://localhost:11434/v1.",
        )
        return

    active_worker = getattr(self, "worker", None)
    ollama_running = app_module.is_local_ollama_listener_present(base_url, timeout=0.8)

    if active_worker is not None and active_worker.isRunning():
        action_text = "turn off" if ollama_running else "turn on"
        reply = QMessageBox.question(
            self,
            "Stop reply and switch Ollama power?",
            (
                "A model reply is still running. Stop that reply first, then "
                f"{action_text} the local Ollama server?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        try:
            self.stop_generation()
        except Exception:
            pass

        QTimer.singleShot(700, lambda: _start_ollama_restart_worker(self))
        return

    if ollama_running:
        reply = QMessageBox.question(
            self,
            "Turn off local Ollama?",
            (
                "This will stop the local Ollama server at localhost:11434. "
                "Press the power button again later to start it cleanly."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

    _start_ollama_restart_worker(self)

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKERS = PROJECT_ROOT / "fzastro_ai" / "workers"


def read_worker(name):
    return (WORKERS / name).read_text(encoding="utf-8-sig")


def test_streaming_workers_request_qthread_interruption_on_stop():
    for worker_file in [
        "chat_worker.py",
        "memory_extraction_worker.py",
        "web_decision_worker.py",
        "web_search_worker.py",
        "document_import_worker.py",
        "astro_worker.py",
    ]:
        text = read_worker(worker_file)
        stop_body = text.split("def stop", 1)[1].split("def ", 1)[0]
        assert "requestInterruption" in stop_body, worker_file


def test_model_stream_workers_close_active_streams_on_stop():
    for worker_file in ["chat_worker.py", "memory_extraction_worker.py"]:
        text = read_worker(worker_file)
        stop_body = text.split("def stop", 1)[1].split("def ", 1)[0]
        assert ".stream.close()" in stop_body, worker_file


def test_gpu_monitor_logs_expected_unavailable_state_without_traceback_spam():
    text = read_worker("gpu_monitor_worker.py")
    assert "log_warning" in text
    assert "log_exception" not in text
    assert "unavailable_reported" in text


def test_chat_worker_handles_closed_stream_without_traceback_spam():
    text = read_worker("chat_worker.py")
    assert "_is_expected_stream_close_error" in text
    assert "winerror 10038" in text
    assert "not a socket" in text
    assert 'log_debug("ChatWorker.run stream closed after stop request"' in text
    assert 'log_warning("ChatWorker.run model stream disconnected"' in text
    assert 'log_exception("ChatWorker.run stream failure"' in text
    assert 'log_exception("ChatWorker.run line 6398"' not in text


def test_chat_worker_stream_close_cleanup_is_debug_level():
    text = read_worker("chat_worker.py")
    assert 'log_debug("ChatWorker.stop stream close"' in text
    assert 'log_debug("ChatWorker.run final stream close"' in text
    assert 'log_exception("ChatWorker.stop line' not in text
    assert 'log_exception("ChatWorker.run line 6408"' not in text


def test_model_discovery_logs_provider_unavailable_without_traceback_spam():
    text = read_worker("model_discovery_worker.py")

    assert "is_runtime_connection_error" in text
    assert "log_warning" in text
    assert "provider unavailable" in text


def test_optional_web_progress_signal_disconnect_is_guarded():
    shutdown_text = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "shutdown_controller.py"
    ).read_text(encoding="utf-8-sig")
    web_actions_text = (
        PROJECT_ROOT / "fzastro_ai" / "actions" / "web_news_actions.py"
    ).read_text(encoding="utf-8-sig")

    assert "_fzastro_progress_connected = False" in web_actions_text
    assert "_fzastro_progress_connected = True" in web_actions_text
    assert 'getattr(web_worker, "_fzastro_progress_connected", False)' in shutdown_text
    assert "progress_search.disconnect(" in shutdown_text
    assert "self.handle_daily_news_progress" in shutdown_text


def test_model_discovery_reports_owned_ollama_process_to_app():
    text = read_worker("model_discovery_worker.py")

    assert "ollama_process_started = Signal(object)" in text
    assert "self.ollama_process_started.emit(start_result.process)" in text


def test_hardware_telemetry_reports_cpu_ram_and_temperatures():
    worker_text = read_worker("gpu_monitor_worker.py")
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    layout_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "main_layout.py").read_text(
        encoding="utf-8-sig"
    )

    assert "system_metrics_ready = Signal" in worker_text
    assert "temperature.gpu" in worker_text
    assert "GlobalMemoryStatusEx" in worker_text
    assert "GetSystemTimes" in worker_text
    assert "psutil.sensors_temperatures" in worker_text
    assert "self.system_label = QLabel" in app_text
    assert "system_metrics_ready.connect(self.update_system_metrics)" in app_text
    assert "def update_system_metrics" in layout_text
    assert "CPU temperature" in layout_text
    assert "GPU temperature" in layout_text


def test_system_telemetry_worker_signal_is_disconnected_on_shutdown():
    shutdown_text = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "shutdown_controller.py"
    ).read_text(encoding="utf-8-sig")

    assert "system_metrics_ready.disconnect()" in shutdown_text


def test_document_knowledge_import_status_is_mirrored_in_dialog():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    styles_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "styles.py").read_text(
        encoding="utf-8-sig"
    )

    assert "knowledge_current_status_text" in app_text
    assert "def set_document_knowledge_status" in app_text
    assert "self.knowledge_status_label.setToolTip(status_text)" in app_text
    assert "self.set_document_knowledge_status(text)" in app_text
    assert "self.set_document_knowledge_status(final_status)" in app_text
    assert (
        "visible_status = self.knowledge_current_status_text or summary_text"
        in app_text
    )
    assert "documentKnowledgeStatusLabel" in styles_text


def test_web_decision_timeout_uses_deterministic_fallback_without_traceback_spam():
    worker_text = read_worker("web_decision_worker.py")
    actions_text = (
        PROJECT_ROOT / "fzastro_ai" / "actions" / "web_news_actions.py"
    ).read_text(encoding="utf-8-sig")

    assert "is_runtime_connection_error" in worker_text
    assert "is_runtime_model_not_found_error" in worker_text
    assert "WebDecisionWorker.run provider unavailable or timed out" in worker_text
    assert "WebDecisionWorker.run selected model unavailable" in worker_text
    assert "WebDecisionWorker.run response_format retry" in worker_text
    assert 'log_exception("WebDecisionWorker.run line' not in worker_text
    assert "Preparing web search without model routing" in actions_text
    assert "self.build_web_query(text)" in actions_text


def test_chat_worker_handles_missing_selected_model_without_traceback_spam():
    worker_text = read_worker("chat_worker.py")

    assert "is_runtime_model_not_found_error" in worker_text
    assert "ChatWorker.run selected model unavailable" in worker_text
    assert "format_runtime_model_unavailable_message" in worker_text
    assert 'log_exception("ChatWorker.run line' not in worker_text


def test_document_maintenance_worker_and_shutdown_are_wired():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    worker_text = read_worker("document_maintenance_worker.py")
    shutdown_text = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "shutdown_controller.py"
    ).read_text(encoding="utf-8-sig")

    assert "DocumentKnowledgeMaintenanceWorker" in app_text
    assert "maintenance_finished.connect" in app_text
    assert "compact_storage" in worker_text
    assert "maintenance_finished = Signal" in worker_text
    assert "knowledge_worker.maintenance_finished.disconnect" in shutdown_text

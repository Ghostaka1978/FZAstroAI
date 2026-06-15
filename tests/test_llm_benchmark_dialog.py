import os

import pytest


class _FakeAppWindowMixin:
    def current_model_name(self):
        value = self.model_box.currentData()
        return str(value or self.model_box.currentText()).strip()

    def current_base_url(self):
        return "http://localhost:11434/v1"

    def current_api_key(self):
        return "ollama"

    def sync_runtime_client(self):
        self.synced_runtime = True


def _make_qt_app(monkeypatch):
    monkeypatch.setenv(
        "QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen")
    )
    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    return qt_widgets, qt_widgets.QApplication.instance() or qt_widgets.QApplication([])


def _make_fake_window(qt_widgets, models, current_index=0):
    class FakeAppWindow(qt_widgets.QWidget, _FakeAppWindowMixin):
        pass

    window = FakeAppWindow()
    window.synced_runtime = False
    window.model_box = qt_widgets.QComboBox()
    window.gpu_label = qt_widgets.QLabel("GPU 46% • 48°C • VRAM 23.4/24.0 GB")
    window.gpu_label.setToolTip("GPU telemetry tooltip")
    window.system_label = qt_widgets.QLabel("CPU 54% • RAM 26.1/63.8 GB")
    window.system_label.setToolTip("System telemetry tooltip")
    for model in models:
        window.model_box.addItem(model, model)
    window.model_box.setCurrentIndex(current_index)
    return window


def test_llm_benchmark_model_selector_keeps_full_app_model_list(monkeypatch):
    qt_widgets, app = _make_qt_app(monkeypatch)

    import fzastro_ai.ui.llm_benchmark_dialog as dialog_module

    monkeypatch.setattr(
        dialog_module.QTimer, "singleShot", lambda *_args, **_kwargs: None
    )

    fake_window = _make_fake_window(
        qt_widgets,
        ["qwen3.6:35b", "gemma4-12b-q8xl-ud-3090ti-150k", "llama3.1:8b"],
        current_index=0,
    )
    dialog = dialog_module.LlmBenchmarkDialog(fake_window)

    try:
        assert [
            dialog.model_box.itemText(i) for i in range(dialog.model_box.count())
        ] == [
            "qwen3.6:35b",
            "gemma4-12b-q8xl-ud-3090ti-150k",
            "llama3.1:8b",
        ]

        assert dialog.select_model("gemma4-12b-q8xl-ud-3090ti-150k")
        assert dialog.selected_model_name() == "gemma4-12b-q8xl-ud-3090ti-150k"
        assert fake_window.current_model_name() == "qwen3.6:35b"

        dummy_worker = object()
        dialog.model_discovery_worker = dummy_worker
        dialog.handle_model_discovery_error(
            dummy_worker,
            "simulated provider refresh failure",
            "gemma4-12b-q8xl-ud-3090ti-150k",
            show_error_dialog=False,
        )

        available = [
            dialog.model_box.itemText(i) for i in range(dialog.model_box.count())
        ]
        assert "qwen3.6:35b" in available
        assert "gemma4-12b-q8xl-ud-3090ti-150k" in available
        assert "llama3.1:8b" in available
        assert dialog.selected_model_name() == "gemma4-12b-q8xl-ud-3090ti-150k"
    finally:
        dialog.close()
        fake_window.close()
        dialog.deleteLater()
        fake_window.deleteLater()
        app.processEvents()


def test_llm_benchmark_tabs_and_telemetry(monkeypatch):
    qt_widgets, app = _make_qt_app(monkeypatch)

    import fzastro_ai.ui.llm_benchmark_dialog as dialog_module

    monkeypatch.setattr(
        dialog_module.QTimer, "singleShot", lambda *_args, **_kwargs: None
    )

    fake_window = _make_fake_window(qt_widgets, ["qwen3.6:35b"], current_index=0)
    dialog = dialog_module.LlmBenchmarkDialog(fake_window)

    try:
        assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
            "Dashboard",
            "History",
            "Compare",
        ]
        assert dialog.gpu_telemetry_label.text() == "GPU 46% • 48°C • VRAM 23.4/24.0 GB"
        assert dialog.system_telemetry_label.text() == "CPU 54% • RAM 26.1/63.8 GB"
        assert dialog.gpu_telemetry_label.toolTip() == "GPU telemetry tooltip"
    finally:
        dialog.close()
        fake_window.close()
        dialog.deleteLater()
        fake_window.deleteLater()
        app.processEvents()


def test_llm_benchmark_delete_selected_history_record(monkeypatch):
    qt_widgets, app = _make_qt_app(monkeypatch)

    import fzastro_ai.ui.llm_benchmark_dialog as dialog_module

    monkeypatch.setattr(
        dialog_module.QTimer, "singleShot", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(dialog_module, "save_benchmark_history", lambda history: None)
    monkeypatch.setattr(
        dialog_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: dialog_module.QMessageBox.Yes,
    )

    fake_window = _make_fake_window(qt_widgets, ["qwen3.6:35b"], current_index=0)
    dialog = dialog_module.LlmBenchmarkDialog(fake_window)

    try:
        dialog.history = [
            {
                "id": "record-1",
                "started_at": "2026-06-15T16:00:00+00:00",
                "model": "qwen3.6:35b",
                "preset": "Quick Q&A (short)",
                "tokens_per_second": 30.0,
                "time_to_first_token_s": 1.0,
                "total_time_s": 3.0,
                "generation_time_s": 2.0,
                "prompt_tokens": 10,
                "completion_tokens": 60,
            },
            {
                "id": "record-2",
                "started_at": "2026-06-15T16:05:00+00:00",
                "model": "qwen3.6:35b",
                "preset": "Math Reasoning",
                "tokens_per_second": 20.0,
                "time_to_first_token_s": 2.0,
                "total_time_s": 5.0,
                "generation_time_s": 3.0,
                "prompt_tokens": 40,
                "completion_tokens": 80,
            },
        ]
        dialog.refresh_history_tables()
        dialog.history_table.selectRow(0)

        dialog.delete_selected_history_records()

        assert [entry["id"] for entry in dialog.history] == ["record-2"]
        assert dialog.history_table.rowCount() == 1
        assert (
            dialog.history_table.item(0, 0).data(dialog_module.Qt.UserRole)
            == "record-2"
        )
    finally:
        dialog.close()
        fake_window.close()
        dialog.deleteLater()
        fake_window.deleteLater()
        app.processEvents()

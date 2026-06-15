import os

import pytest


def test_gui_main_window_constructs_and_closes(monkeypatch, tmp_path):
    """Smoke-test main-window construction when PySide6 is available.

    The CI/container used for pure unit tests may not install PySide6, so this
    test is intentionally skipped there. On the Windows release environment it
    verifies that the app can build the main window and close it without starting
    background GPU polling.
    """

    monkeypatch.setenv(
        "QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen")
    )
    monkeypatch.setenv("FZASTRO_APP_DIR", str(tmp_path / "appdata"))
    monkeypatch.setenv("FZASTRO_DISABLE_STARTUP_GPU_MONITOR", "1")
    monkeypatch.setenv("FZASTRO_DISABLE_STARTUP_MODEL_REFRESH", "1")

    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtCore")

    from fzastro_ai.app import FZAstroAI

    application = qt_widgets.QApplication.instance() or qt_widgets.QApplication([])
    window = FZAstroAI()

    try:
        assert window.windowTitle()
        assert window.system_prompt.toPlainText().strip()
        assert window.gpu_monitor is None
        assert window.model_discovery_worker is None
        window.close()
        application.processEvents()
    finally:
        window.deleteLater()
        application.processEvents()

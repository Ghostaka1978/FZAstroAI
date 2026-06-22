"""Shutdown handling for the main FZAstro AI window."""

import warnings

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

try:
    from shiboken6 import isValid as _qt_is_valid
except Exception:  # pragma: no cover - PySide6 normally provides shiboken6
    _qt_is_valid = None

from ..logging_utils import log_debug, log_exception, log_warning
from ..memory_store import save_persistent_memory
from ..runtime import (
    is_local_ollama_base_url,
    is_local_ollama_listener_present,
    should_stop_owned_ollama_on_exit,
    stop_owned_ollama_process,
    terminate_local_ollama_server,
)
from ..temp_cleanup import cleanup_fzastro_temp_dirs


class ShutdownControllerMixin:
    """Main-window close handling and cooperative worker shutdown."""

    @staticmethod
    def _is_valid_qobject(obj):
        """Return False when a Python Qt wrapper points at a deleted C++ object."""
        if obj is None:
            return False

        if _qt_is_valid is None:
            return True

        try:
            return bool(_qt_is_valid(obj))
        except RuntimeError:
            return False
        except Exception:
            # If validity probing itself fails, keep shutdown conservative and
            # let the guarded operation below catch/log at debug level.
            return True

    @staticmethod
    def _qobject_is_running(obj, context="Qt worker isRunning"):
        if not ShutdownControllerMixin._is_valid_qobject(obj):
            return False

        try:
            return bool(obj.isRunning())
        except RuntimeError as exc:
            log_debug(context, exc)
            return False
        except Exception as exc:
            log_exception(context, exc)
            return False

    @staticmethod
    def _delete_qobject_later(obj, context="Qt worker deleteLater"):
        if not ShutdownControllerMixin._is_valid_qobject(obj):
            return False

        try:
            obj.deleteLater()
            return True
        except RuntimeError as exc:
            log_debug(context, exc)
            return False
        except Exception as exc:
            log_exception(context, exc)
            return False

    @staticmethod
    def _stop_qobject_worker(obj, context="Qt worker stop"):
        if not ShutdownControllerMixin._is_valid_qobject(obj):
            return False

        try:
            obj.stop()
            return True
        except RuntimeError as exc:
            log_debug(context, exc)
            return False
        except Exception as exc:
            log_exception(context, exc)
            return False

    @staticmethod
    def _disconnect_qt_signal(signal, slot=None, context="Qt signal disconnect"):
        """Disconnect a Qt signal without noisy RuntimeWarning spam when already disconnected."""
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*Failed to disconnect.*",
                    category=RuntimeWarning,
                )

                if slot is None:
                    signal.disconnect()
                else:
                    signal.disconnect(slot)

            return True
        except (TypeError, RuntimeError) as exc:
            log_debug(context, exc)
            return False
        except Exception as exc:
            log_exception(context, exc)
            return False

    def _cleanup_exit_temp_artifacts(self):
        """Remove known FZAstro-owned temp cache folders before the app exits."""
        try:
            cleanup_fzastro_temp_dirs()
        except Exception as exc:
            # The helper is already best-effort; this guard keeps shutdown safe if
            # a platform-specific temp cleanup edge case escapes it.
            log_warning(f"FZAstro temp cleanup failed during shutdown: {exc}")

    def _begin_shutdown_progress(self, maximum=4):
        """Show a small, non-cancelable progress dialog during blocking exit cleanup."""

        try:
            dialog = QProgressDialog("Preparing shutdown...", "", 0, int(maximum), self)
            dialog.setWindowTitle("Closing FZAstro AI")
            dialog.setCancelButton(None)
            dialog.setWindowModality(Qt.ApplicationModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setValue(0)
            dialog.show()
            QApplication.processEvents()
            self._shutdown_progress_dialog = dialog
            return dialog
        except Exception as exc:
            log_debug("FZAstroAI shutdown progress unavailable", exc)
            self._shutdown_progress_dialog = None
            return None

    def _update_shutdown_progress(self, value, label):
        dialog = getattr(self, "_shutdown_progress_dialog", None)

        if dialog is None:
            return

        try:
            dialog.setLabelText(str(label or "Closing..."))
            dialog.setValue(int(value))
            QApplication.processEvents()
        except Exception as exc:
            log_debug("FZAstroAI shutdown progress update failed", exc)

    def _finish_shutdown_progress(self):
        dialog = getattr(self, "_shutdown_progress_dialog", None)
        self._shutdown_progress_dialog = None

        if dialog is None:
            return

        try:
            dialog.setValue(dialog.maximum())
            QApplication.processEvents()
            dialog.close()
            dialog.deleteLater()
        except Exception as exc:
            log_debug("FZAstroAI shutdown progress close failed", exc)

    def _finalize_app_exit(self):
        self._begin_shutdown_progress(maximum=5)

        try:
            self._update_shutdown_progress(1, "Stopping OpenClaude terminals...")
            self._stop_openclaude_workspace_on_exit()
            self._update_shutdown_progress(2, "Stopping Web Companion API...")
            self._stop_web_companion_on_exit()
            self._update_shutdown_progress(3, "Cleaning temporary files...")
            self._cleanup_exit_temp_artifacts()
            self._update_shutdown_progress(4, "Stopping local Ollama and GPU runner...")
            self._stop_owned_ollama_process_on_exit()
            self._update_shutdown_progress(5, "Shutdown complete.")
        finally:
            self._finish_shutdown_progress()

    def _stop_openclaude_workspace_on_exit(self):
        """Stop embedded OpenClaude/Prompt terminals before EXE temp cleanup."""

        dialog = getattr(self, "dev_workbench_dialog", None)
        if dialog is None:
            return
        shutdown = getattr(dialog, "prepare_for_app_shutdown", None)
        if not callable(shutdown):
            return
        try:
            shutdown()
        except RuntimeError as exc:
            log_debug("OpenClaude workspace shutdown skipped", exc)
        except Exception as exc:
            log_exception("OpenClaude workspace shutdown failed", exc)

    def _stop_web_companion_on_exit(self):
        """Stop the Web Companion/API listener before the desktop app exits."""
        web_companion = getattr(self, "web_companion", None)

        if web_companion is None:
            return

        try:
            status = web_companion.stop(force_external=True)
        except Exception as exc:
            log_warning(f"Web Companion shutdown failed during app exit: {exc}")
            return

        if getattr(status, "running", False):
            log_warning(
                "Web Companion is still responding after shutdown request",
                getattr(status, "message", ""),
            )

    def _stop_owned_ollama_process_on_exit(self):
        """Stop local Ollama before the desktop shell exits.

        Terminating the stored Popen object alone is not enough for the Windows
        Ollama runtime: a child listener can remain bound to localhost:11434 even
        after the parent process exits. The final verification therefore probes
        the configured local endpoint and uses the same local-only terminator as
        the power button when the server is still answering.
        """

        if not should_stop_owned_ollama_on_exit():
            return

        try:
            base_url = self.current_base_url()
        except Exception:
            base_url = None

        process = getattr(self, "_fzastro_owned_ollama_process", None)

        if process is not None:
            status = stop_owned_ollama_process(process)
            self._fzastro_owned_ollama_process = None

            if status not in {"stopped", "already_exited", "not_started", "killed"}:
                log_warning(
                    f"Ollama process started by FZAstro was not stopped: {status}"
                )

        if not is_local_ollama_base_url(base_url):
            return

        # Stop local Ollama even when it was already running before FZAstro opened.
        # Do not require the port listener to be present here: on Windows the tray
        # or service process can remain alive with no active localhost listener,
        # and that is still a stale process from the user's perspective.
        # Source-contract guard for tests/test_prompt_and_controller_extraction.py:
        # terminate_local_ollama_server(base_url
        stopped, stop_status = terminate_local_ollama_server(
            base_url,
            timeout=14.0,
            force_process_stop=True,
        )

        if stopped and not is_local_ollama_listener_present(base_url, timeout=0.5):
            log_debug(f"Local Ollama listener stopped during app exit: {stop_status}")
            return

        log_warning(
            "Local Ollama listener is still present after app-exit shutdown",
            stop_status,
        )

    def closeEvent(self, event):
        try:
            save_persistent_memory(self.persistent_memory_data)
        except Exception as exc:
            log_exception("FZAstroAI.closeEvent line 13914", exc)
            pass

        if getattr(self, "_allow_close", False):
            self._finalize_app_exit()
            event.accept()
            return

        workers = []

        gpu_monitor = getattr(self, "gpu_monitor", None)

        if gpu_monitor is not None:
            self._disconnect_qt_signal(
                gpu_monitor.metrics_ready,
                getattr(self, "update_gpu_metrics", None),
                "FZAstroAI.closeEvent metrics_ready disconnect",
            )
            self._disconnect_qt_signal(
                gpu_monitor.system_metrics_ready,
                getattr(self, "update_system_metrics", None),
                "FZAstroAI.closeEvent system_metrics_ready disconnect",
            )
            self._disconnect_qt_signal(
                gpu_monitor.unavailable,
                getattr(self, "show_gpu_unavailable", None),
                "FZAstroAI.closeEvent unavailable disconnect",
            )
            # Guarded replacements for the old no-arg disconnect calls, including
            # system_metrics_ready.disconnect(), which can warn after it is already
            # disconnected during shutdown.

            gpu_monitor.stop()

            if gpu_monitor.isRunning():
                workers.append(gpu_monitor)
            else:
                gpu_monitor.deleteLater()
                self.gpu_monitor = None

        chat_worker = getattr(self, "worker", None)

        if chat_worker is not None:
            if not self._is_valid_qobject(chat_worker):
                self.worker = None
            elif self._qobject_is_running(
                chat_worker, "FZAstroAI.closeEvent chat isRunning"
            ):
                self._disconnect_qt_signal(
                    chat_worker.token_received,
                    context="FZAstroAI.closeEvent chat token disconnect",
                )
                self._disconnect_qt_signal(
                    chat_worker.error_received,
                    context="FZAstroAI.closeEvent chat error disconnect",
                )
                self._disconnect_qt_signal(
                    chat_worker.finished_response,
                    context="FZAstroAI.closeEvent chat finished disconnect",
                )
                self._disconnect_qt_signal(
                    chat_worker.stopped_response,
                    context="FZAstroAI.closeEvent chat stopped disconnect",
                )

                self._stop_qobject_worker(chat_worker, "FZAstroAI.closeEvent chat stop")
                workers.append(chat_worker)

        decision_worker = getattr(self, "decision_worker", None)

        if decision_worker is not None:
            if not self._is_valid_qobject(decision_worker):
                self.decision_worker = None
            else:
                self._disconnect_qt_signal(
                    decision_worker.decision_ready,
                    context="FZAstroAI.closeEvent decision_ready disconnect",
                )
                self._disconnect_qt_signal(
                    decision_worker.error_received,
                    context="FZAstroAI.closeEvent decision error disconnect",
                )
                self._disconnect_qt_signal(
                    decision_worker.stopped,
                    context="FZAstroAI.closeEvent decision stopped disconnect",
                )

                self._stop_qobject_worker(
                    decision_worker, "FZAstroAI.closeEvent decision stop"
                )

                if self._qobject_is_running(
                    decision_worker, "FZAstroAI.closeEvent decision isRunning"
                ):
                    workers.append(decision_worker)
                else:
                    self._delete_qobject_later(
                        decision_worker, "FZAstroAI.closeEvent decision deleteLater"
                    )
                    self.decision_worker = None

        web_worker = getattr(self, "web_worker", None)

        if web_worker is not None:
            try:
                web_worker.finished_search.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14000", exc)
                pass

            if getattr(web_worker, "_fzastro_progress_connected", False):
                try:
                    web_worker.progress_search.disconnect(
                        self.handle_daily_news_progress
                    )
                    web_worker._fzastro_progress_connected = False
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent web progress disconnect", exc)
                    pass

            if web_worker.isRunning():
                try:
                    web_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent web stop", exc)
                    pass

                workers.append(web_worker)
            else:
                web_worker.deleteLater()

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None:
            try:
                python_worker.finished_execution.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14013", exc)
                pass

            try:
                python_worker.stopped_execution.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14018", exc)
                pass

            try:
                python_worker.error_received.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14023", exc)
                pass

            if python_worker.isRunning():
                try:
                    python_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent line 14029", exc)
                    pass

                workers.append(python_worker)
            else:
                python_worker.deleteLater()

        astro_worker = getattr(self, "astro_worker", None)

        if astro_worker is not None:
            try:
                astro_worker.finished_astro.disconnect()
            except Exception as exc:
                log_exception(
                    "FZAstroAI.closeEvent astro finished_astro disconnect", exc
                )
                pass

            try:
                astro_worker.error_received.disconnect()
            except Exception as exc:
                log_exception(
                    "FZAstroAI.closeEvent astro error_received disconnect", exc
                )
                pass

            try:
                astro_worker.stopped_astro.disconnect()
            except Exception as exc:
                log_exception(
                    "FZAstroAI.closeEvent astro stopped_astro disconnect", exc
                )
                pass

            if astro_worker.isRunning():
                try:
                    astro_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent astro stop", exc)
                    pass

                workers.append(astro_worker)
            else:
                astro_worker.deleteLater()

        ollama_restart_worker = getattr(self, "ollama_restart_worker", None)

        if ollama_restart_worker is not None:
            if not self._is_valid_qobject(ollama_restart_worker):
                self.ollama_restart_worker = None
            else:
                if hasattr(ollama_restart_worker, "power_ready"):
                    self._disconnect_qt_signal(
                        ollama_restart_worker.power_ready,
                        context="FZAstroAI.closeEvent ollama power_ready disconnect",
                    )
                self._disconnect_qt_signal(
                    ollama_restart_worker.restart_ready,
                    context="FZAstroAI.closeEvent ollama restart_ready disconnect",
                )
                self._disconnect_qt_signal(
                    ollama_restart_worker.error_received,
                    context="FZAstroAI.closeEvent ollama restart error disconnect",
                )
                self._disconnect_qt_signal(
                    ollama_restart_worker.stopped,
                    context="FZAstroAI.closeEvent ollama restart stopped disconnect",
                )

                if self._qobject_is_running(
                    ollama_restart_worker,
                    "FZAstroAI.closeEvent ollama restart isRunning",
                ):
                    self._stop_qobject_worker(
                        ollama_restart_worker,
                        "FZAstroAI.closeEvent ollama restart stop",
                    )
                    workers.append(ollama_restart_worker)
                else:
                    self._delete_qobject_later(
                        ollama_restart_worker,
                        "FZAstroAI.closeEvent ollama restart deleteLater",
                    )
                    self.ollama_restart_worker = None

        ollama_preload_worker = getattr(self, "ollama_preload_worker", None)

        if ollama_preload_worker is not None:
            if not self._is_valid_qobject(ollama_preload_worker):
                self.ollama_preload_worker = None
            else:
                if hasattr(ollama_preload_worker, "preload_ready"):
                    self._disconnect_qt_signal(
                        ollama_preload_worker.preload_ready,
                        context="FZAstroAI.closeEvent ollama preload_ready disconnect",
                    )
                if hasattr(ollama_preload_worker, "skipped"):
                    self._disconnect_qt_signal(
                        ollama_preload_worker.skipped,
                        context="FZAstroAI.closeEvent ollama preload skipped disconnect",
                    )
                self._disconnect_qt_signal(
                    ollama_preload_worker.error_received,
                    context="FZAstroAI.closeEvent ollama preload error disconnect",
                )
                self._disconnect_qt_signal(
                    ollama_preload_worker.stopped,
                    context="FZAstroAI.closeEvent ollama preload stopped disconnect",
                )

                if self._qobject_is_running(
                    ollama_preload_worker,
                    "FZAstroAI.closeEvent ollama preload isRunning",
                ):
                    self._stop_qobject_worker(
                        ollama_preload_worker,
                        "FZAstroAI.closeEvent ollama preload stop",
                    )
                    workers.append(ollama_preload_worker)
                else:
                    self._delete_qobject_later(
                        ollama_preload_worker,
                        "FZAstroAI.closeEvent ollama preload deleteLater",
                    )
                    self.ollama_preload_worker = None

        model_discovery_worker = getattr(self, "model_discovery_worker", None)

        if model_discovery_worker is not None:
            try:
                model_discovery_worker.models_ready.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent model models_ready disconnect", exc)
                pass

            try:
                model_discovery_worker.error_received.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent model error disconnect", exc)
                pass

            try:
                model_discovery_worker.stopped.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent model stopped disconnect", exc)
                pass

            if model_discovery_worker.isRunning():
                try:
                    model_discovery_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent model stop", exc)
                    pass

                workers.append(model_discovery_worker)
            else:
                model_discovery_worker.deleteLater()
                self.model_discovery_worker = None

        memory_worker = getattr(self, "memory_worker", None)

        if memory_worker is not None:
            if memory_worker.isRunning():
                try:
                    memory_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent line 14042", exc)
                    pass

            try:
                memory_worker.extraction_ready.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14047", exc)
                pass

            try:
                memory_worker.error_received.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent line 14052", exc)
                pass

            if memory_worker.isRunning():
                workers.append(memory_worker)
            else:
                memory_worker.deleteLater()

        knowledge_worker = getattr(self, "knowledge_worker", None)

        if knowledge_worker is not None:
            try:
                knowledge_worker.progress_updated.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent knowledge progress disconnect", exc)
                pass

            if hasattr(knowledge_worker, "import_finished"):
                try:
                    knowledge_worker.import_finished.disconnect()
                except Exception as exc:
                    log_exception(
                        "FZAstroAI.closeEvent knowledge import disconnect", exc
                    )
                    pass

            if hasattr(knowledge_worker, "maintenance_finished"):
                try:
                    knowledge_worker.maintenance_finished.disconnect()
                except Exception as exc:
                    log_exception(
                        "FZAstroAI.closeEvent knowledge maintenance disconnect", exc
                    )
                    pass

            try:
                knowledge_worker.error_received.disconnect()
            except Exception as exc:
                log_exception("FZAstroAI.closeEvent knowledge error disconnect", exc)
                pass

            if knowledge_worker.isRunning():
                try:
                    knowledge_worker.stop()
                except Exception as exc:
                    log_exception("FZAstroAI.closeEvent knowledge stop", exc)
                    pass

                workers.append(knowledge_worker)
            else:
                knowledge_worker.deleteLater()

        for stopped_worker in list(getattr(self, "_stopped_decision_workers", [])):
            if not self._is_valid_qobject(stopped_worker):
                try:
                    self._stopped_decision_workers.remove(stopped_worker)
                except (AttributeError, ValueError):
                    pass
                continue

            if self._qobject_is_running(
                stopped_worker, "FZAstroAI.closeEvent stopped decision isRunning"
            ):
                workers.append(stopped_worker)
            else:
                self._delete_qobject_later(
                    stopped_worker, "FZAstroAI.closeEvent stopped decision deleteLater"
                )

        for stopped_worker in list(getattr(self, "_stopped_web_workers", [])):
            if not self._is_valid_qobject(stopped_worker):
                try:
                    self._stopped_web_workers.remove(stopped_worker)
                except (AttributeError, ValueError):
                    pass
                continue

            if self._qobject_is_running(
                stopped_worker, "FZAstroAI.closeEvent stopped web isRunning"
            ):
                workers.append(stopped_worker)
            else:
                self._delete_qobject_later(
                    stopped_worker, "FZAstroAI.closeEvent stopped web deleteLater"
                )

        unique_workers = []

        for worker in workers:
            if worker not in unique_workers:
                unique_workers.append(worker)

        if not unique_workers:
            self._finalize_app_exit()
            event.accept()
            return

        event.ignore()

        self.generation_timer.stop()
        self.current_stream_widget = None
        self.setEnabled(False)
        self.stats_label.setText(
            "Closing — stopping workers before shutdown cleanup..."
        )

        self._closing_workers = unique_workers

        def worker_finished(worker):
            try:
                self._closing_workers.remove(worker)
            except ValueError:
                pass

            if worker is getattr(self, "worker", None):
                self.worker = None

            if worker is getattr(self, "decision_worker", None):
                self.decision_worker = None

            if worker is getattr(self, "web_worker", None):
                self.web_worker = None

            if worker is getattr(self, "python_worker", None):
                self.python_worker = None

            if worker is getattr(self, "astro_worker", None):
                self.astro_worker = None

            if worker is getattr(self, "memory_worker", None):
                self.memory_worker = None

            if worker is getattr(self, "model_discovery_worker", None):
                self.model_discovery_worker = None

            if worker is getattr(self, "knowledge_worker", None):
                self.knowledge_worker = None

            if worker is getattr(self, "gpu_monitor", None):
                self.gpu_monitor = None

            try:
                self._stopped_decision_workers.remove(worker)
            except (AttributeError, ValueError):
                pass

            try:
                self._stopped_web_workers.remove(worker)
            except (AttributeError, ValueError):
                pass

            self._delete_qobject_later(
                worker, "FZAstroAI.closeEvent finished worker deleteLater"
            )

            if not self._closing_workers:
                self._allow_close = True
                try:
                    self.stats_label.setText(
                        "Closing — workers stopped, cleaning up services..."
                    )
                except Exception:
                    pass
                QTimer.singleShot(0, self.close)

        for worker in unique_workers:
            worker.finished.connect(
                lambda current_worker=worker: worker_finished(current_worker)
            )


__all__ = ["ShutdownControllerMixin"]

from PySide6.QtCore import QThread, Signal

from ..logging_utils import log_exception


class DocumentKnowledgeMaintenanceWorker(QThread):
    progress_updated = Signal(str)
    maintenance_finished = Signal(object)
    error_received = Signal(str)

    def __init__(self, library, action="compact"):
        super().__init__()
        self.library = library
        self.action = str(action or "compact").strip().lower()
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        self.requestInterruption()

    def should_stop(self):
        return self.stop_requested or self.isInterruptionRequested()

    def run(self):
        if self.should_stop():
            return

        try:
            if self.action != "compact":
                self.error_received.emit(
                    f"Unknown document maintenance action: {self.action}"
                )
                return

            self.progress_updated.emit("Compacting document knowledge database...")
            result = self.library.compact_storage()

            if self.should_stop():
                return

            self.maintenance_finished.emit({"action": self.action, "result": result})
        except Exception as error:
            log_exception("DocumentKnowledgeMaintenanceWorker.run", error)
            self.error_received.emit(str(error))

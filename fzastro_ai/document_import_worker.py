from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .logging_utils import log_exception


class DocumentKnowledgeImportWorker(QThread):
    progress_updated = Signal(str)
    import_finished = Signal(object)
    error_received = Signal(str)

    def __init__(self, library, file_paths):
        super().__init__()
        self.library = library
        self.file_paths = list(file_paths)
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        self.requestInterruption()

    def should_stop(self):
        return self.stop_requested or self.isInterruptionRequested()

    def run(self):
        results = []
        errors = []

        for index, file_path in enumerate(self.file_paths, start=1):
            if self.should_stop():
                return

            file_name = Path(file_path).name
            self.progress_updated.emit(
                f"Indexing document {index}/{len(self.file_paths)}: {file_name}"
            )

            if self.should_stop():
                return

            try:
                result = self.library.import_document(file_path)
                results.append(result)
            except Exception as error:
                log_exception("DocumentKnowledgeImportWorker.run", error)
                errors.append(f"{file_name}: {error}")

            if self.should_stop():
                return

        if self.should_stop():
            return

        if not results:
            self.error_received.emit(
                "No selected document could be indexed.\n\n"
                + "\n".join(f"- {item}" for item in errors)
            )
            return

        self.import_finished.emit({"results": results, "errors": errors})

from PySide6.QtCore import QThread, Signal

from ..logging_utils import log_exception
from ..market_sources import perform_stock_quote
from ..web_tools import (
    perform_rendered_page_extraction,
    perform_web_image_search,
    perform_web_search,
    perform_website_screenshot,
)


class WebSearchWorker(QThread):
    finished_search = Signal(str)
    progress_search = Signal(str)

    def __init__(self, query, image_search=False, mode=None):
        super().__init__()

        self.query = query
        self.stop_requested = False

        if mode is not None:
            self.mode = mode
        elif image_search:
            self.mode = "image"
        else:
            self.mode = "web"

    def stop(self):
        self.stop_requested = True
        self.requestInterruption()

    def should_stop(self):
        return self.stop_requested or self.isInterruptionRequested()

    def emit_progress(self, text):
        if not self.should_stop():
            self.progress_search.emit(str(text))

    def run(self):
        if self.should_stop():
            return

        try:
            if self.mode == "image":
                result = perform_web_image_search(self.query)

            elif self.mode == "stock_quote":
                result = perform_stock_quote(self.query)

            elif self.mode == "rendered_page":
                result = perform_rendered_page_extraction(self.query)

            elif self.mode == "website_screenshot":
                result = perform_website_screenshot(self.query)

            else:
                result = perform_web_search(
                    self.query, progress_callback=self.emit_progress
                )

        except Exception as e:
            log_exception("WebSearchWorker.run", e)
            result = f"Browser operation failed: {str(e)}"

        if not self.should_stop():
            self.finished_search.emit(result)

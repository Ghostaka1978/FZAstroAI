"""Market quote actions for the main FZAstro AI window.

Extracted from app.py during Phase 2G without behavior changes.
"""

import time
import uuid

from PySide6.QtCore import QTimer

from ..workers import WebSearchWorker


def prepare_content(text, files):
    # Imported lazily to avoid an app -> actions -> app import cycle at startup.
    from ..app import prepare_content as _prepare_content

    return _prepare_content(text, files)


class MarketActionsMixin:
    def retrieve_stock_price(self, ticker):
        ticker = str(ticker or "").strip().upper()

        asset_labels = {
            "CRM": "CRM stock",
            "DBX": "DBX stock",
            "CL=F": "Crude oil",
            "GC=F": "Gold",
        }

        if ticker not in asset_labels:
            return

        if self.worker and self.worker.isRunning():
            return

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            return

        decision_worker = getattr(self, "decision_worker", None)

        if decision_worker is not None and decision_worker.isRunning():
            return

        web_worker = getattr(self, "web_worker", None)

        if web_worker is not None and web_worker.isRunning():
            return

        asset_label = asset_labels[ticker]
        display_text = f"{asset_label} price"
        user_message_id = uuid.uuid4().hex

        self.messages.append(
            {
                "id": user_message_id,
                "role": "user",
                "content": prepare_content(display_text, []),
                "files": [],
            }
        )

        self.add_message_widget(":ME:", display_text, [], message_id=user_message_id)

        self.request_start_time = time.perf_counter()
        self.generation_timer.start(100)
        self.set_busy_ui_state()
        self.stats_label.setText(f"Retrieving {asset_label} quote... • 0.00s")

        worker = WebSearchWorker(ticker, mode="stock_quote")
        self.web_worker = worker

        worker.finished_search.connect(
            lambda result, current_ticker=ticker: self.finish_stock_quote(
                current_ticker, result
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def finish_stock_quote(self, ticker, quote_text):
        self.generation_timer.stop()
        self.web_worker = None
        self.global_thought_box.setMarkdown("")
        self._last_thoughts_text = ""

        elapsed = max(0.0, time.perf_counter() - self.request_start_time)
        assistant_message_id = uuid.uuid4().hex

        self.messages.append(
            {
                "id": assistant_message_id,
                "role": "assistant",
                "content": quote_text,
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": ["app", "market_data"],
            }
        )

        self.add_message_widget(
            ":AI: ",
            quote_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=["app", "market_data"],
        )

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.force_scroll_to_bottom()
        QTimer.singleShot(0, self.force_scroll_to_bottom)

        asset_labels = {"CRM": "CRM", "DBX": "DBX", "CL=F": "Crude oil", "GC=F": "Gold"}
        asset_label = asset_labels.get(ticker, ticker)

        self.set_idle_ui_state(f"{asset_label} quote retrieved • {elapsed:.2f}s")

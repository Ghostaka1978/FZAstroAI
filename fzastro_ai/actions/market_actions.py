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
    def _market_request_is_busy(self):
        if self.worker and self.worker.isRunning():
            return True

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            return True

        decision_worker = getattr(self, "decision_worker", None)

        if decision_worker is not None and decision_worker.isRunning():
            return True

        web_worker = getattr(self, "web_worker", None)

        return web_worker is not None and web_worker.isRunning()

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

        if self._market_request_is_busy():
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

    def retrieve_global_market_pulse(self):
        if self._market_request_is_busy():
            return

        display_text = "Global market pulse"
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
        self.stats_label.setText("Retrieving global market pulse... - 0.00s")

        worker = WebSearchWorker("global_market_pulse", mode="market_pulse")
        self.web_worker = worker

        worker.finished_search.connect(self.finish_global_market_pulse)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def finish_global_market_pulse(self, pulse_text):
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
                "content": pulse_text,
                "news_sources": {},
                "response_time": elapsed,
                "source_tags": ["app", "market_data"],
            }
        )

        self.add_message_widget(
            ":AI: ",
            pulse_text,
            message_id=assistant_message_id,
            response_time=elapsed,
            source_tags=["app", "market_data"],
        )

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.force_scroll_to_bottom()
        QTimer.singleShot(0, self.force_scroll_to_bottom)

        self.set_idle_ui_state(f"Global market pulse retrieved - {elapsed:.2f}s")

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

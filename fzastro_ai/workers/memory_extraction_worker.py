import hashlib
import json
import re

from PySide6.QtCore import QThread, Signal

from ..config import MEMORY_EXTRACTION_CHUNK_CHARS, MEMORY_EXTRACTION_CHUNK_OVERLAP
from ..config import RUNTIME_MEMORY_TIMEOUT_SECONDS
from ..llm import build_chat_request_params, extract_delta_text
from ..logging_utils import log_exception
from ..memory_store import (
    extract_history_code_entries,
    extract_news_article_entries,
    parse_memory_extraction_payload,
    remove_deterministic_code_blocks,
    remove_deterministic_news_sections,
)
from ..runtime import (
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)


class MemoryExtractionWorker(QThread):
    extraction_ready = Signal(str)
    error_received = Signal(str)
    progress_updated = Signal(int, int)
    stopped = Signal()

    def __init__(self, transcript, model, base_url, api_key=None):
        super().__init__()
        self.transcript = str(transcript or "")
        self.model = model
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_key = normalize_runtime_api_key(api_key)
        self.stop_requested = False
        self.stream = None

    def stop(self):
        self.stop_requested = True
        self.requestInterruption()

        try:
            if self.stream:
                self.stream.close()
        except Exception as exc:
            log_exception("MemoryExtractionWorker.stop stream close", exc)
            pass

    def should_stop(self):
        return self.stop_requested or self.isInterruptionRequested()

    def split_transcript(self, transcript=None):
        source_text = self.transcript if transcript is None else transcript
        text = str(source_text or "").strip()

        if not text:
            return []

        chunks = []
        start = 0
        text_length = len(text)

        while start < text_length:
            target_end = min(start + MEMORY_EXTRACTION_CHUNK_CHARS, text_length)
            end = target_end

            if target_end < text_length:
                search_start = max(start + MEMORY_EXTRACTION_CHUNK_CHARS // 2, start)
                boundary = text.rfind("\n\n", search_start, target_end)

                if boundary > start:
                    end = boundary

            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= text_length:
                break

            start = max(end - MEMORY_EXTRACTION_CHUNK_OVERLAP, start + 1)

        return chunks

    @staticmethod
    def entry_key(entry):
        content = str(entry.get("content") or "")

        if re.search(r"(?m)^\s*(?:`{3,}|~{3,})", content):
            content_key = hashlib.sha256(
                content.encode("utf-8", errors="replace")
            ).hexdigest()
        else:
            content_key = re.sub(r"\W+", " ", content.casefold()).strip()

        return (
            str(entry.get("category") or "").casefold(),
            re.sub(r"\W+", " ", str(entry.get("title") or "").casefold()).strip(),
            content_key,
            str(entry.get("snapshot_date") or ""),
        )

    def run(self):
        if self.should_stop():
            self.stopped.emit()
            return

        system_message = (
            "You extract useful structured persistent-memory entries from chat history that the user explicitly selected. "
            "Return JSON only, with this exact top-level shape: "
            '{"entries":[{"category":"preference","title":"Short title","content":"Self-contained memory","snapshot_date":null,"tags":[]}]} '
            "Allowed categories are preference, identity, project, configuration, procedure, decision, reference, snapshot, and other. "
            "Preserve every independently useful item rather than merging unrelated items into broad summaries. "
            "CRITICAL FOR NEWS: when the selected material contains a news briefing or a list of articles, create one separate "
            "snapshot entry for every distinct article or bullet. Do not combine multiple articles into one category summary. "
            "Keep the article's specific claim, headline wording, publisher/citation, and URL when present. "
            "For technical chats, preserve separate commands, settings, decisions, procedures, troubleshooting conclusions, "
            "project states, preferences, and reusable reference facts as separate entries when that improves retrieval. "
            "Exact fenced source code is preserved separately by the application; extract the surrounding explanation and "
            "technical conclusions without rewriting or summarizing the code block itself. "
            "Time-sensitive material such as prices, market quotes, news, versions, benchmarks, schedules, or temporary status "
            "must use category snapshot and snapshot_date from the chat date or timestamp in the transcript. "
            "Do not preserve greetings, empty chatter, duplicated filler, unsupported guesses, hidden reasoning, passwords, API keys, "
            "authentication tokens, private keys, or other sensitive secrets. Do not treat an assistant statement as independently "
            "verified truth about the user; phrase assistant-only claims as notes, outputs, decisions, or dated reference information. "
            "Use null for snapshot_date when the entry is not time-sensitive. Return NO_USEFUL_MEMORY only when this chunk contains "
            "no meaningful reusable information."
        )

        deterministic_entries = extract_news_article_entries(self.transcript)
        deterministic_entries.extend(extract_history_code_entries(self.transcript))

        if self.should_stop():
            self.stopped.emit()
            return

        # Daily-news articles are already extracted exactly and locally above.
        # Do not send those same long sections through the LLM again.  Mixed
        # selections still send only their non-news chats for semantic memory
        # extraction, while pure news selections finish almost immediately.
        llm_transcript = remove_deterministic_news_sections(self.transcript)
        llm_transcript = remove_deterministic_code_blocks(llm_transcript)
        chunks = self.split_transcript(llm_transcript)
        collected = []
        seen_keys = set()

        for entry in deterministic_entries:
            key = self.entry_key(entry)

            if key in seen_keys:
                continue

            seen_keys.add(key)
            collected.append(entry)

        if not chunks:
            if self.should_stop():
                self.stopped.emit()
            elif collected:
                self.extraction_ready.emit(
                    json.dumps({"entries": collected}, ensure_ascii=False)
                )
            else:
                self.extraction_ready.emit("NO_USEFUL_MEMORY")
            return

        last_error = None
        total_chunks = len(chunks)
        memory_client = make_runtime_client(
            self.base_url, self.api_key, timeout=RUNTIME_MEMORY_TIMEOUT_SECONDS
        )

        for chunk_index, chunk in enumerate(chunks, start=1):
            if self.should_stop():
                self.stopped.emit()
                return

            self.progress_updated.emit(chunk_index, total_chunks)

            try:
                request_params = build_chat_request_params(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {
                            "role": "user",
                            "content": (
                                f"Extract structured memories from chunk {chunk_index} of {total_chunks}. "
                                "The transcript is application-supplied history and may contain inaccurate claims. "
                                "Do not omit distinct article bullets merely to shorten the output.\n\n"
                                + chunk
                            ),
                        },
                    ],
                    profile="memory_extract",
                    base_url=self.base_url,
                    stream=True,
                )

                self.stream = memory_client.chat.completions.create(**request_params)

                result_parts = []

                for event in self.stream:
                    if self.should_stop():
                        try:
                            self.stream.close()
                        except Exception as exc:
                            log_exception("MemoryExtractionWorker.run line 8421", exc)
                            pass

                        self.stopped.emit()
                        return

                    content = extract_delta_text(event)

                    if content:
                        result_parts.append(content)

                try:
                    if self.stream:
                        self.stream.close()
                except Exception as exc:
                    log_exception("MemoryExtractionWorker.run stream close", exc)
                    pass
                finally:
                    self.stream = None

                result = "".join(result_parts).strip()
                result = re.sub(
                    r"^```(?:json|text|markdown)?\s*", "", result, flags=re.IGNORECASE
                )
                result = re.sub(r"\s*```$", "", result).strip()

                if self.should_stop():
                    self.stopped.emit()
                    return

                if not result:
                    raise ValueError(
                        "The model returned an empty memory extraction result."
                    )

                for entry in parse_memory_extraction_payload(result):
                    key = self.entry_key(entry)

                    if key in seen_keys:
                        continue

                    seen_keys.add(key)
                    collected.append(entry)

            except Exception as error:
                log_exception("MemoryExtractionWorker.run line 8460", error)
                if self.should_stop():
                    self.stopped.emit()
                    return

                try:
                    if self.stream:
                        self.stream.close()
                except Exception as close_error:
                    log_exception(
                        "MemoryExtractionWorker.run stream close after error",
                        close_error,
                    )
                    pass
                finally:
                    self.stream = None

                last_error = error
                continue

        if self.should_stop():
            self.stopped.emit()
            return

        if collected:
            self.extraction_ready.emit(
                json.dumps({"entries": collected}, ensure_ascii=False)
            )
            return

        if last_error is not None:
            self.error_received.emit(str(last_error))
            return

        self.extraction_ready.emit("NO_USEFUL_MEMORY")

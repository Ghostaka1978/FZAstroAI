"""Offline speech-to-text worker for FZAstro AI voice commands."""

from __future__ import annotations

import json
import math
import queue
import time
from array import array
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..voice.command_router import voice_command_grammar


class VoiceCommandWorker(QThread):
    """Record a microphone utterance and transcribe it with local Vosk.

    Optional dependencies are imported inside ``run()`` so the rest of the app
    still starts normally when offline voice support has not been installed yet.

    The worker supports production-friendly endpointing: after speech has been
    detected, a short pause automatically finalizes the transcript. Users can
    still click the mic button again to stop immediately.
    """

    status = Signal(str)
    transcribed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        model_path: str | Path,
        sample_rate: int = 16000,
        max_seconds: float = 10.0,
        silence_seconds: float = 0.9,
        min_speech_seconds: float = 0.25,
        silence_rms_threshold: int = 450,
        parent=None,
    ):
        super().__init__(parent)
        self.model_path = Path(model_path).expanduser()
        self.sample_rate = int(sample_rate or 16000)
        self.max_seconds = max(1.5, float(max_seconds or 10.0))
        self.silence_seconds = max(0.35, float(silence_seconds or 0.9))
        self.min_speech_seconds = max(0.05, float(min_speech_seconds or 0.25))
        self.silence_rms_threshold = max(40, int(silence_rms_threshold or 450))
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):  # pragma: no cover - requires live microphone hardware
        try:
            self._run_vosk_transcription()
        except Exception as exc:
            self.failed.emit(f"Offline voice failed: {exc}")

    def _run_vosk_transcription(
        self,
    ):  # pragma: no cover - requires live microphone hardware
        try:
            import sounddevice as sd
            import vosk
        except Exception as exc:
            raise RuntimeError(
                "missing optional packages. Install them with: "
                "pip install vosk sounddevice"
            ) from exc

        if not self.model_path.exists():
            raise RuntimeError(
                "Vosk model not found. Put an extracted Vosk model folder under "
                f"{self.model_path.parent} or set FZASTRO_VOSK_MODEL."
            )

        audio_queue: queue.Queue[bytes] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                self.status.emit(f"Voice input warning: {status}")
            audio_queue.put(bytes(indata))

        self.status.emit("Loading offline voice model…")
        model = vosk.Model(str(self.model_path))
        grammar_json = json.dumps(voice_command_grammar())
        recognizer = vosk.KaldiRecognizer(model, float(self.sample_rate), grammar_json)
        recognizer.SetWords(False)

        heard_text = ""
        partial_text = ""
        speech_started = False
        first_voice_time: float | None = None
        last_voice_time: float | None = None
        start_time = time.monotonic()
        deadline = start_time + self.max_seconds
        blocksize = max(800, int(self.sample_rate * 0.1))
        self.status.emit("Listening… speak, then pause to process")

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=blocksize,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            while not self._stop_requested and time.monotonic() < deadline:
                try:
                    data = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                now = time.monotonic()
                if self._audio_rms(data) >= self.silence_rms_threshold:
                    if not speech_started:
                        first_voice_time = now
                        self.status.emit("Listening… pause when done")
                    speech_started = True
                    last_voice_time = now

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result() or "{}")
                    text = str(result.get("text") or "").strip()
                    if text:
                        heard_text = text
                        break
                else:
                    partial = json.loads(recognizer.PartialResult() or "{}")
                    text = str(partial.get("partial") or "").strip()
                    if text:
                        partial_text = text

                if (
                    speech_started
                    and first_voice_time is not None
                    and last_voice_time is not None
                    and now - first_voice_time >= self.min_speech_seconds
                    and now - last_voice_time >= self.silence_seconds
                ):
                    self.status.emit("Processing voice command…")
                    final = json.loads(recognizer.FinalResult() or "{}")
                    heard_text = str(final.get("text") or partial_text or "").strip()
                    break

        if not heard_text:
            final = json.loads(recognizer.FinalResult() or "{}")
            heard_text = str(final.get("text") or partial_text or "").strip()

        if self._stop_requested and not heard_text:
            self.status.emit("Voice command cancelled.")
            return

        self.transcribed.emit(heard_text)

    @staticmethod
    def _audio_rms(data: bytes) -> float:
        """Return a simple RMS level for signed 16-bit mono PCM audio."""

        if not data:
            return 0.0

        samples = array("h")
        samples.frombytes(data)
        if not samples:
            return 0.0

        # RawInputStream uses native endian int16. For command endpointing we only
        # need a stable relative energy level, not calibrated dB.
        return math.sqrt(
            sum(int(sample) * int(sample) for sample in samples) / len(samples)
        )

"""LLM benchmark dashboard for the FZAstro AI desktop app.

This dialog benchmarks any model returned by the configured OpenAI-compatible
runtime, records accuracy, speed, trust, and throughput metrics, and keeps a lightweight
local JSON history for later comparison.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..benchmarks import (
    BENCHMARK_ENGINE_VERSION,
    build_result_evidence,
    composite_score,
    grade_benchmark_response,
    run_statistics,
)
from ..config import APP_DIR, DEFAULT_MODEL_NAME, RUNTIME_CHAT_TIMEOUT_SECONDS
from ..logging_utils import log_exception, log_warning
from ..runtime import is_ollama_base_url, make_runtime_client
from ..workers.model_discovery_worker import ModelDiscoveryWorker
from .window_utils import apply_window_defaults

BENCHMARK_HISTORY_FILE = Path(APP_DIR) / "llm_benchmark_history.json"


@dataclass(frozen=True)
class BenchmarkPreset:
    name: str
    subtitle: str
    max_tokens: int
    prompts: tuple[str, ...]


BENCHMARK_PRESETS = (
    BenchmarkPreset(
        name="Quick Q&A (short)",
        subtitle="Short factual answers — measures latency on compact outputs.",
        max_tokens=256,
        prompts=(
            "Answer in one short paragraph: why does the Moon show phases?",
            "Answer in one short paragraph: why do stars twinkle more near the horizon?",
            "Answer in one short paragraph: why is the sky darker at a high-altitude observatory?",
        ),
    ),
    BenchmarkPreset(
        name="Math Reasoning",
        subtitle="Multi-step arithmetic, units, and concise explanation.",
        max_tokens=768,
        prompts=(
            "A train leaves station A at 60 mph. Another train leaves station B, "
            "180 miles away, at 75 mph toward station A. If they start at the same "
            "time, when do they meet? Show the reasoning briefly.",
            "An imaging rig captures 240 light frames of 180 seconds each, 60 darks, "
            "and 80 flats. How many total exposure hours are in the light frames, and "
            "how many calibration frames are there? Show the calculation.",
            "A telescope has 800 mm focal length and a camera with 3.76 micron pixels. "
            "Estimate the image scale in arcseconds per pixel using 206.265 * pixel_size / focal_length. "
            "Show the formula and result.",
        ),
    ),
    BenchmarkPreset(
        name="Code Generation",
        subtitle="Python implementation tasks with edge cases and tests.",
        max_tokens=1024,
        prompts=(
            "Write a Python function that implements binary search on a sorted list. "
            "Include type hints, handle missing values, and add three simple tests.",
            "Write a Python function that parses a CSV string of timestamp,temperature rows "
            "and returns min, max, and average temperature. Include error handling and two tests.",
            "Write a small Python dataclass for an astrophotography exposure plan. Include "
            "fields for target, exposure seconds, frame count, filter name, and a method that returns total minutes.",
        ),
    ),
    BenchmarkPreset(
        name="Creative Writing",
        subtitle="Longer coherent prose with continuity and style control.",
        max_tokens=1400,
        prompts=(
            "Write a short story of at least 300 words about a programmer who teaches "
            "an observatory telescope to dream. Keep the tone cinematic but clear.",
            "Write a 350-word scene about a rover hearing a human voice for the first time "
            "during a dust storm on Mars. Keep it grounded and emotionally restrained.",
            "Write a 300-word reflective monologue from an old satellite watching city lights "
            "from orbit. Avoid clichés and keep the language precise.",
        ),
    ),
    BenchmarkPreset(
        name="Logical Reasoning",
        subtitle="Syllogisms, constraints, and contradiction checks.",
        max_tokens=640,
        prompts=(
            "All roses are flowers. Some flowers fade quickly. Can we conclude that "
            "some roses fade quickly? Explain the answer carefully in 5 sentences or fewer.",
            "Three filters are used on Monday, Tuesday, and Wednesday: Luminance, H-alpha, and OIII. "
            "H-alpha is not used on Monday. OIII is used after Luminance. Which filter is used Tuesday? Explain.",
            "A statement says: every calibrated frame is saved, and no saved frame is corrupted. "
            "A new frame is corrupted. Can it be calibrated? Explain the valid conclusion.",
        ),
    ),
    BenchmarkPreset(
        name="Data Analysis",
        subtitle="Small table analysis, arithmetic consistency, and recommendation.",
        max_tokens=900,
        prompts=(
            "Given this coffee shop revenue for one week: Mon $120, Tue $135, Wed $128, "
            "Thu $180, Fri $250, Sat $310, Sun $290. Compute total, average, best day, "
            "and give one operational recommendation.",
            "Given nightly seeing values in arcseconds: 2.4, 1.9, 1.6, 2.1, 1.4, 1.8, 2.7. "
            "Compute the average, best night, worst night, and advise whether to schedule high-resolution imaging.",
            "A local model benchmark produced TPS values 24, 28, 31, 27, and 30. Compute mean, median, "
            "range, and identify whether the run looks stable enough for comparison.",
        ),
    ),
    BenchmarkPreset(
        name="Translation & Multilingual",
        subtitle="Translation plus meaning preservation across scripts.",
        max_tokens=800,
        prompts=(
            "Translate this paragraph into Japanese, then Greek, then summarize the meaning "
            "in English: The night sky rewards patient observers because faint details emerge "
            "only after careful attention and good conditions.",
            "Translate into Greek and Spanish, then list two terms that are hard to translate precisely: "
            "Good calibration frames make faint nebula structure easier to recover during processing.",
            "Translate into Japanese and French, then give a one-sentence English summary: "
            "A careful benchmark should measure both speed and whether the answer actually follows instructions.",
        ),
    ),
    BenchmarkPreset(
        name="Summarization",
        subtitle="Dense technical compression with coverage requirements.",
        max_tokens=900,
        prompts=(
            "Summarize the key concepts of transformer architecture in deep learning. "
            "Cover attention, positional information, feed-forward layers, and why scaling helps.",
            "Summarize the purpose of dark frames, flats, bias frames, dithering, and stacking in astrophotography. "
            "Use concise bullets and mention what each step fixes.",
            "Summarize how an OpenAI-compatible local runtime, streaming responses, model discovery, "
            "and token throughput metrics fit together in a desktop AI app.",
        ),
    ),
    BenchmarkPreset(
        name="Instruction Following",
        subtitle="Exact constraints, formatting, and refusal/verbosity control.",
        max_tokens=512,
        prompts=(
            "List exactly 5 fruits that start with the letter M. For each fruit provide "
            "one color and one short culinary use. Return only a markdown table.",
            "Return exactly 7 bullet points. Each bullet must contain one astronomy term and exactly one number. "
            "Do not include an introduction or conclusion.",
            "Create a JSON object with keys model, benchmark, metrics, and verdict. metrics must contain "
            "tokens_per_second and quality_score as numbers. Return only JSON.",
        ),
    ),
)


SUITE_DEPTHS = (
    ("standard", "Standard — first prompt per preset"),
    ("deep", "Deep — all prompts per preset"),
)


class LlmBenchmarkWorker(QThread):
    progress = Signal(str)
    sample_finished = Signal(object)
    benchmark_finished = Signal(object)
    benchmark_stopped = Signal(object)
    error_received = Signal(str)

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        jobs: list[dict[str, Any]],
        temperature: float,
        system_prompt: str = "",
        persona_key: str = "baseline",
        persona_name: str = "Raw model",
        parent=None,
    ):
        super().__init__(parent)
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.jobs = self._normalize_jobs(jobs)
        self.temperature = float(temperature)
        self.system_prompt = str(system_prompt or "").strip()
        self.persona_key = str(persona_key or "baseline").strip() or "baseline"
        self.persona_name = str(persona_name or "Raw model").strip() or "Raw model"
        self.stop_requested = False
        self.active_stream = None

    @staticmethod
    def _normalize_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clean_jobs = []

        for job in jobs or []:
            prompt = str(job.get("prompt") or "").strip()
            if not prompt:
                continue

            preset_name = str(job.get("preset") or "Custom Prompt").strip()
            prompt_name = str(job.get("prompt_name") or "").strip()
            suite_depth = str(job.get("suite_depth") or "standard").strip()
            try:
                repeat_index = max(1, int(job.get("repeat_index") or 1))
            except (TypeError, ValueError):
                repeat_index = 1
            try:
                repeat_total = max(1, int(job.get("repeat_total") or 1))
            except (TypeError, ValueError):
                repeat_total = 1
            max_tokens = max(16, int(job.get("max_tokens") or 512))
            clean_jobs.append(
                {
                    "preset": preset_name or "Custom Prompt",
                    "prompt_name": prompt_name,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "suite_depth": suite_depth or "standard",
                    "repeat_index": repeat_index,
                    "repeat_total": repeat_total,
                }
            )

        return clean_jobs

    def stop(self):
        self.stop_requested = True

        try:
            self.requestInterruption()
        except Exception:
            pass

        try:
            if self.active_stream is not None:
                self.active_stream.close()
        except Exception as exc:
            log_warning("LlmBenchmarkWorker.stop stream close", exc)

    def should_stop(self):
        return bool(self.stop_requested or self.isInterruptionRequested())

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        clean_text = str(text or "")
        if not clean_text:
            return 0
        return max(1, len(clean_text) // 4)

    @staticmethod
    def _chunk_content(chunk) -> str:
        if not getattr(chunk, "choices", None):
            return ""

        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        content = getattr(delta, "content", None)

        if content is not None:
            return str(content)

        try:
            delta_data = delta.model_dump() if delta is not None else {}
        except Exception:
            delta_data = {}

        if isinstance(delta_data, dict):
            content = delta_data.get("content")
            if content is not None:
                return str(content)

        return ""

    def _request_params(self, prompt: str, max_tokens: int):
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
        }

        if is_ollama_base_url(self.base_url):
            params["extra_body"] = {
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": self.temperature,
                    "repeat_penalty": 1.05,
                },
            }
        else:
            # OpenAI-compatible cloud providers usually accept max_tokens here.
            # Local Ollama is handled through extra_body/options above.
            params["max_tokens"] = max_tokens

        return params

    def run(self):
        if not self.model:
            self.error_received.emit("Select a benchmark model first.")
            return

        if not self.jobs:
            self.error_received.emit("Add at least one benchmark prompt.")
            return

        started_at = datetime.now(timezone.utc).isoformat()
        results = []

        try:
            client = make_runtime_client(
                self.base_url,
                self.api_key,
                timeout=max(float(RUNTIME_CHAT_TIMEOUT_SECONDS), 600.0),
            )

            total_jobs = len(self.jobs)
            for index, job in enumerate(self.jobs, start=1):
                if self.should_stop():
                    self.benchmark_stopped.emit({"results": results})
                    return

                prompt = job["prompt"]
                preset_name = job["preset"]
                prompt_name = job.get("prompt_name") or ""
                max_tokens = job["max_tokens"]
                repeat_index = int(job.get("repeat_index") or 1)
                repeat_total = int(job.get("repeat_total") or 1)
                repeat_suffix = (
                    f", repeat {repeat_index}/{repeat_total}"
                    if repeat_total > 1
                    else ""
                )
                prompt_suffix = f" — {prompt_name}" if prompt_name else ""
                self.progress.emit(
                    f"Running {preset_name}{prompt_suffix} ({index}/{total_jobs}{repeat_suffix})…"
                )

                response_parts = []
                request_started = time.perf_counter()
                first_token_elapsed = None

                try:
                    self.active_stream = client.chat.completions.create(
                        **self._request_params(prompt, max_tokens)
                    )

                    for chunk in self.active_stream:
                        if self.should_stop():
                            try:
                                self.active_stream.close()
                            except Exception:
                                pass
                            self.benchmark_stopped.emit({"results": results})
                            return

                        content = self._chunk_content(chunk)
                        if not content:
                            continue

                        if first_token_elapsed is None:
                            first_token_elapsed = time.perf_counter() - request_started

                        response_parts.append(content)

                finally:
                    try:
                        if self.active_stream is not None:
                            self.active_stream.close()
                    except Exception as exc:
                        log_warning("LlmBenchmarkWorker.run stream close", exc)
                    self.active_stream = None

                total_elapsed = time.perf_counter() - request_started
                response_text = "".join(response_parts).strip()
                prompt_tokens = self._estimate_tokens(prompt)
                system_prompt_tokens = self._estimate_tokens(self.system_prompt)
                input_tokens = prompt_tokens + system_prompt_tokens
                completion_tokens = self._estimate_tokens(response_text)
                time_to_first_token = (
                    first_token_elapsed
                    if first_token_elapsed is not None
                    else total_elapsed
                )
                generation_elapsed = max(0.001, total_elapsed - time_to_first_token)
                tokens_per_second = completion_tokens / generation_elapsed

                heuristic_quality = evaluate_response_quality(
                    preset_name=preset_name,
                    prompt=prompt,
                    response=response_text,
                    max_tokens=max_tokens,
                )
                benchmark_scores = grade_benchmark_response(
                    preset_name=preset_name,
                    prompt=prompt,
                    response=response_text,
                    max_tokens=max_tokens,
                    model=self.model,
                    base_url=self.base_url,
                    repeat_total=repeat_total,
                    heuristic_score=heuristic_quality.get("score"),
                    heuristic_notes=heuristic_quality.get("notes") or [],
                    token_estimation_method="estimated char/4",
                )
                result = {
                    "id": f"{int(time.time() * 1000)}-{index}",
                    "started_at": started_at,
                    "model": self.model,
                    "persona_key": self.persona_key,
                    "persona_name": self.persona_name,
                    "system_prompt_tokens": system_prompt_tokens,
                    "system_prompt_hash": _prompt_hash(self.system_prompt),
                    "preset": preset_name,
                    "prompt_name": prompt_name,
                    "prompt_index": index,
                    "prompt": prompt,
                    "response": response_text,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                    "suite_depth": job.get("suite_depth") or "standard",
                    "repeat_index": repeat_index,
                    "repeat_total": repeat_total,
                    "prompt_tokens": prompt_tokens,
                    "input_tokens": input_tokens,
                    "completion_tokens": completion_tokens,
                    "total_time_s": total_elapsed,
                    "time_to_first_token_s": time_to_first_token,
                    "generation_time_s": generation_elapsed,
                    "tokens_per_second": tokens_per_second,
                    "benchmark_engine_version": BENCHMARK_ENGINE_VERSION,
                    "case_id": benchmark_scores["case_id"],
                    "prompt_hash": benchmark_scores["prompt_hash"],
                    "response_hash": benchmark_scores["response_hash"],
                    "accuracy_score": benchmark_scores["accuracy_score"],
                    "instruction_score": benchmark_scores["instruction_score"],
                    "trust_score": benchmark_scores["trust_score"],
                    "deterministic_score": benchmark_scores["deterministic_score"],
                    "heuristic_quality_score": benchmark_scores[
                        "heuristic_quality_score"
                    ],
                    "quality_score": benchmark_scores["quality_score"],
                    "quality_label": benchmark_scores["quality_label"],
                    "quality_notes": benchmark_scores["quality_notes"],
                    "quality_method": benchmark_scores["quality_method"],
                    "grader_results": benchmark_scores["grader_results"],
                    "trust_notes": benchmark_scores["trust_notes"],
                    "token_estimation_method": benchmark_scores[
                        "token_estimation_method"
                    ],
                }
                results.append(result)
                self.sample_finished.emit(result)

            self.benchmark_finished.emit({"results": results})

        except Exception as exc:
            if self.should_stop():
                self.benchmark_stopped.emit({"results": results})
                return

            log_exception("LlmBenchmarkWorker.run", exc)
            self.error_received.emit(str(exc))


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        title_label = QLabel(title.upper())
        title_label.setObjectName("fieldCaption")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("header")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("settingsCardSubtitle")
        self.subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)

    def set_metric(self, value: str, subtitle: str = ""):
        self.value_label.setText(str(value))
        self.subtitle_label.setText(str(subtitle or ""))


class LlmBenchmarkDialog(QDialog):
    def __init__(self, app_window, parent=None):
        super().__init__(parent or app_window)
        apply_window_defaults(self)
        self.app_window = app_window
        self.worker: LlmBenchmarkWorker | None = None
        self.model_discovery_worker: ModelDiscoveryWorker | None = None
        self.history: list[dict] = load_benchmark_history()
        self.current_response_result_id: str | None = None

        self.setWindowTitle("LLM Benchmark Dashboard")
        self.resize(1160, 820)
        self.setMinimumSize(900, 640)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._build_ui()
        self.refresh_models_from_app(set_status=False)
        self.refresh_personas_from_app()
        QTimer.singleShot(
            150, lambda: self.refresh_models_from_runtime(show_errors=False)
        )
        self._load_selected_preset()
        self.refresh_history_tables()
        self.refresh_dashboard()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(1)
        title = QLabel("LLM Benchmark")
        title.setObjectName("header")
        subtitle = QLabel("Accuracy, speed, trust, history, and model comparison")
        subtitle.setObjectName("subtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("selectionPill")
        self.status_label.setAlignment(Qt.AlignCenter)

        header_row.addWidget(title_box, 1)
        header_row.addWidget(self.status_label, 0, Qt.AlignRight)
        root_layout.addLayout(header_row)

        telemetry_card = QFrame()
        telemetry_card.setObjectName("benchmarkTelemetryCard")
        telemetry_layout = QHBoxLayout(telemetry_card)
        telemetry_layout.setContentsMargins(12, 6, 12, 6)
        telemetry_layout.setSpacing(10)

        telemetry_caption = QLabel("TELEMETRY")
        telemetry_caption.setObjectName("fieldCaption")
        self.gpu_telemetry_label = QLabel("GPU --% • VRAM --/-- GB")
        self.gpu_telemetry_label.setObjectName("gpuLabel")
        self.gpu_telemetry_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.system_telemetry_label = QLabel("CPU --% • RAM --/-- GB")
        self.system_telemetry_label.setObjectName("systemLabel")
        self.system_telemetry_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        telemetry_layout.addWidget(telemetry_caption, 0, Qt.AlignLeft)
        telemetry_layout.addSpacing(6)
        telemetry_layout.addWidget(self.gpu_telemetry_label, 1)
        telemetry_layout.addStretch(1)
        telemetry_layout.addWidget(self.system_telemetry_label, 1)
        root_layout.addWidget(telemetry_card)

        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self.refresh_telemetry_from_app)
        self.telemetry_timer.start(1000)
        self.refresh_telemetry_from_app()

        controls_card = QFrame()
        controls_card.setObjectName("benchmarkControlsCard")
        controls_layout = QGridLayout(controls_card)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.setVerticalSpacing(8)

        model_caption = QLabel("MODEL")
        model_caption.setObjectName("fieldCaption")
        self.model_box = QComboBox()
        self.model_box.setEditable(False)
        # Keep the benchmark selector visually and behaviorally aligned with the
        # compact model selector in the main quick bar, while allowing a wider
        # popup for long local model names.
        self.model_box.setObjectName("quickModelBox")
        self.model_box.setFixedHeight(36)
        self.model_box.setMinimumWidth(320)
        self.model_box.setMinimumContentsLength(28)
        self.model_box.setMaxVisibleItems(24)
        self.model_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_box.view().setMinimumWidth(560)
        self.model_box.setToolTip(
            "Choose the model to benchmark from the same model list used by the main app."
        )
        self.model_box.currentTextChanged.connect(self._benchmark_model_changed)

        self.refresh_button = QPushButton("Refresh Models")
        self.refresh_button.setObjectName("secondaryActionButton")
        self.refresh_button.setToolTip(
            "Fetch model names from the configured endpoint, using the same runtime settings as the main app."
        )
        self.refresh_button.clicked.connect(self.refresh_models_from_runtime)

        self.use_active_model_button = QPushButton("Use Active Model")
        self.use_active_model_button.setObjectName("secondaryActionButton")
        self.use_active_model_button.setToolTip(
            "Select the model currently active in the main FZAstro AI window."
        )
        self.use_active_model_button.clicked.connect(self.select_active_app_model)

        persona_caption = QLabel("PERSONA / CALIBRATION")
        persona_caption.setObjectName("fieldCaption")
        self.persona_box = QComboBox()
        self.persona_box.setObjectName("benchmarkComboBox")
        self.persona_box.setMinimumWidth(230)
        self.persona_box.setMinimumContentsLength(20)
        self.persona_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.persona_box.setToolTip(
            "Choose whether the benchmark runs as a raw model or with one of the app calibration/persona system prompts."
        )
        self.persona_box.currentIndexChanged.connect(self._benchmark_persona_changed)

        preset_caption = QLabel("BENCHMARK PRESET")
        preset_caption.setObjectName("fieldCaption")
        self.preset_box = QComboBox()
        self.preset_box.setObjectName("benchmarkComboBox")
        self.preset_box.setMinimumWidth(260)
        self.preset_box.setMinimumContentsLength(22)
        self.preset_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preset_box.addItems(
            [preset.name for preset in BENCHMARK_PRESETS] + ["Custom Prompt"]
        )
        self.preset_box.currentTextChanged.connect(self._load_selected_preset)

        suite_caption = QLabel("SUITE DEPTH")
        suite_caption.setObjectName("fieldCaption")
        self.suite_depth_box = QComboBox()
        self.suite_depth_box.setObjectName("benchmarkComboBox")
        self.suite_depth_box.setMinimumWidth(230)
        self.suite_depth_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for depth_value, depth_label in SUITE_DEPTHS:
            self.suite_depth_box.addItem(depth_label, depth_value)
        self.suite_depth_box.setCurrentIndex(1)
        self.suite_depth_box.setToolTip(
            "Standard runs the first prompt from each preset. Deep runs every prompt for stronger comparisons."
        )
        self.suite_depth_box.currentIndexChanged.connect(self._load_selected_preset)

        repeat_caption = QLabel("REPEAT / PROMPT")
        repeat_caption.setObjectName("fieldCaption")
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setObjectName("benchmarkSpinBox")
        self.repeat_spin.setRange(1, 10)
        self.repeat_spin.setSingleStep(1)
        self.repeat_spin.setValue(1)
        self.repeat_spin.setMinimumWidth(112)
        self.repeat_spin.setToolTip(
            "Repeat each benchmark prompt for more stable averages. Use 2-3 for serious model comparisons."
        )

        temperature_caption = QLabel("TEMPERATURE")
        temperature_caption.setObjectName("fieldCaption")
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setObjectName("benchmarkSpinBox")
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setValue(0.30)
        self.temperature_spin.setMinimumWidth(112)

        max_tokens_caption = QLabel("MAX TOKENS")
        max_tokens_caption.setObjectName("fieldCaption")
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setObjectName("benchmarkSpinBox")
        self.max_tokens_spin.setRange(16, 32768)
        self.max_tokens_spin.setSingleStep(128)
        self.max_tokens_spin.setValue(512)
        self.max_tokens_spin.setMinimumWidth(112)

        self.run_button = QPushButton("Run Selected")
        self.run_button.setObjectName("primaryActionButton")
        self.run_button.setToolTip("Run the selected preset or custom prompt.")
        self.run_button.clicked.connect(self.run_benchmark)

        self.run_all_button = QPushButton("Run All Presets")
        self.run_all_button.setObjectName("secondaryActionButton")
        self.run_all_button.setToolTip(
            "Run every built-in benchmark preset using the selected suite depth and repeat count."
        )
        self.run_all_button.clicked.connect(self.run_all_presets)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerActionButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_benchmark)

        self.clear_history_button = QPushButton("Clear History")
        self.clear_history_button.setObjectName("secondaryActionButton")
        self.clear_history_button.clicked.connect(self.clear_history)

        self.export_button = QPushButton("Export JSON")
        self.export_button.setObjectName("secondaryActionButton")
        self.export_button.clicked.connect(self.export_history)

        controls_layout.addWidget(model_caption, 0, 0, 1, 3)
        controls_layout.addWidget(persona_caption, 0, 3, 1, 3)
        controls_layout.addWidget(self.model_box, 1, 0, 1, 3)
        controls_layout.addWidget(self.refresh_button, 1, 3, 1, 1)
        controls_layout.addWidget(self.use_active_model_button, 1, 4, 1, 1)
        controls_layout.addWidget(self.persona_box, 1, 5, 1, 1)
        controls_layout.addWidget(preset_caption, 2, 0, 1, 2)
        controls_layout.addWidget(suite_caption, 2, 2)
        controls_layout.addWidget(repeat_caption, 2, 3)
        controls_layout.addWidget(temperature_caption, 2, 4)
        controls_layout.addWidget(max_tokens_caption, 2, 5)
        controls_layout.addWidget(self.preset_box, 3, 0, 1, 2)
        controls_layout.addWidget(self.suite_depth_box, 3, 2)
        controls_layout.addWidget(self.repeat_spin, 3, 3)
        controls_layout.addWidget(self.temperature_spin, 3, 4)
        controls_layout.addWidget(self.max_tokens_spin, 3, 5)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(8)
        actions_row.addStretch(1)
        actions_row.addWidget(self.export_button)
        actions_row.addWidget(self.clear_history_button)
        actions_row.addWidget(self.stop_button)
        actions_row.addWidget(self.run_all_button)
        actions_row.addWidget(self.run_button)
        controls_layout.addLayout(actions_row, 4, 0, 1, 6)

        self.prompt_summary_label = QLabel("")
        self.prompt_summary_label.setObjectName("settingsCardSubtitle")
        self.prompt_summary_label.setWordWrap(True)
        controls_layout.addWidget(self.prompt_summary_label, 5, 0, 1, 6)

        self.custom_prompt_caption = QLabel("CUSTOM PROMPT")
        self.custom_prompt_caption.setObjectName("fieldCaption")
        self.custom_prompt_edit = QTextEdit()
        self.custom_prompt_edit.setObjectName("systemPromptBox")
        self.custom_prompt_edit.setPlaceholderText(
            "Type a custom benchmark prompt here…"
        )
        self.custom_prompt_edit.setMinimumHeight(72)
        self.custom_prompt_edit.setMaximumHeight(96)
        self.custom_prompt_edit.textChanged.connect(self._custom_prompt_changed)
        controls_layout.addWidget(self.custom_prompt_caption, 6, 0, 1, 6)
        controls_layout.addWidget(self.custom_prompt_edit, 7, 0, 1, 6)

        self.prompt_list = QListWidget(self)
        self.prompt_list.hide()

        controls_layout.setColumnStretch(0, 2)
        controls_layout.setColumnStretch(1, 2)
        controls_layout.setColumnStretch(2, 1)
        controls_layout.setColumnStretch(3, 0)
        controls_layout.setColumnStretch(4, 0)
        controls_layout.setColumnStretch(5, 2)
        root_layout.addWidget(controls_card)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("benchmarkTabs")
        root_layout.addWidget(self.tabs, 1)

        self.dashboard_tab = QWidget()
        self.history_tab = QWidget()
        self.compare_tab = QWidget()
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.compare_tab, "Compare")

        self._build_dashboard_tab()
        self._build_history_tab()
        self._build_compare_tab()

    def refresh_telemetry_from_app(self):
        """Mirror the main window hardware telemetry inside the benchmark dialog."""

        def _copy_label(source_name: str, target: QLabel, fallback: str):
            source = getattr(self.app_window, source_name, None)
            text = ""
            tooltip = ""
            try:
                text = source.text() if source is not None else ""
                tooltip = source.toolTip() if source is not None else ""
            except RuntimeError:
                text = ""
                tooltip = ""

            target.setText(text.strip() or fallback)
            target.setToolTip(tooltip.strip() or fallback)

        _copy_label("gpu_label", self.gpu_telemetry_label, "GPU telemetry unavailable")
        _copy_label(
            "system_label", self.system_telemetry_label, "CPU/RAM telemetry unavailable"
        )

    def _build_dashboard_tab(self):
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        metric_grid = QGridLayout()
        metric_grid.setContentsMargins(0, 0, 0, 0)
        metric_grid.setHorizontalSpacing(10)
        metric_grid.setVerticalSpacing(10)

        self.metric_total_runs = MetricCard("Total runs", "0", "0 completed, 0 errors")
        self.metric_models_tested = MetricCard("Models tested", "0", "0 servers")
        self.metric_avg_latency = MetricCard("Avg latency", "—", "time to first token")
        self.metric_avg_throughput = MetricCard(
            "Avg speed", "—", "tokens/sec generation"
        )
        self.metric_avg_accuracy = MetricCard("Avg accuracy", "—", "graded checks")
        self.metric_avg_trust = MetricCard("Avg trust", "—", "evidence score")
        self.metric_avg_stability = MetricCard("Stability", "—", "throughput variance")
        self.metric_avg_gen = MetricCard("Avg gen time", "—", "token generation time")

        cards = [
            self.metric_total_runs,
            self.metric_models_tested,
            self.metric_avg_accuracy,
            self.metric_avg_trust,
            self.metric_avg_throughput,
            self.metric_avg_latency,
            self.metric_avg_stability,
            self.metric_avg_gen,
        ]
        for index, card in enumerate(cards):
            metric_grid.addWidget(card, index // 4, index % 4)

        layout.addLayout(metric_grid)

        result_label = QLabel("LATEST BENCHMARK RESULTS")
        result_label.setObjectName("fieldCaption")
        layout.addWidget(result_label)

        self.latest_table = self._create_results_table()
        layout.addWidget(self.latest_table, 1)

        response_label = QLabel("MODEL RESPONSE")
        response_label.setObjectName("fieldCaption")
        layout.addWidget(response_label)

        self.response_browser = QTextBrowser()
        self.response_browser.setObjectName("helpCheatSheetBrowser")
        self.response_browser.setMinimumHeight(150)
        self.response_browser.setMarkdown(
            "Run a benchmark to see the model output here."
        )
        layout.addWidget(self.response_browser, 1)

    def _build_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        history_actions = QHBoxLayout()
        history_actions.setContentsMargins(0, 0, 0, 0)
        history_actions.setSpacing(8)
        history_label = QLabel("BENCHMARK HISTORY")
        history_label.setObjectName("fieldCaption")
        self.delete_history_button = QPushButton("Delete Selected")
        self.delete_history_button.setObjectName("dangerActionButton")
        self.delete_history_button.setToolTip(
            "Delete the selected benchmark history record(s)."
        )
        self.delete_history_button.setEnabled(False)
        self.delete_history_button.clicked.connect(self.delete_selected_history_records)
        history_actions.addWidget(history_label)
        history_actions.addStretch(1)
        history_actions.addWidget(self.delete_history_button)
        layout.addLayout(history_actions)

        self.history_table = self._create_results_table()
        self.history_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(
            self.open_history_context_menu
        )
        self.history_table.itemSelectionChanged.connect(
            self.update_history_action_state
        )
        self.delete_history_shortcut = QShortcut(
            QKeySequence.Delete, self.history_table
        )
        self.delete_history_shortcut.activated.connect(
            self.delete_selected_history_records
        )
        layout.addWidget(self.history_table)

        hint = QLabel(
            "Select a history row and press Delete, right-click it, or use Delete Selected to remove individual records."
        )
        hint.setObjectName("settingsCardSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _build_compare_tab(self):
        layout = QVBoxLayout(self.compare_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        label = QLabel("MODEL COMPARISON")
        label.setObjectName("fieldCaption")
        layout.addWidget(label)

        self.compare_table = QTableWidget()
        self.compare_table.setObjectName("benchmarkTable")
        self.compare_table.setColumnCount(12)
        self.compare_table.setHorizontalHeaderLabels(
            [
                "Model",
                "Persona",
                "Runs",
                "Coverage",
                "Accuracy",
                "Speed",
                "Trust",
                "Instruction",
                "Stability",
                "Composite",
                "Avg TPS",
                "Avg TTFT",
            ]
        )
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.compare_table.verticalHeader().setVisible(False)
        self.compare_table.setAlternatingRowColors(True)
        self.compare_table.setShowGrid(False)
        self.compare_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.compare_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.compare_table)

    @staticmethod
    def _create_results_table():
        table = QTableWidget()
        table.setObjectName("benchmarkTable")
        table.setColumnCount(12)
        table.setHorizontalHeaderLabels(
            [
                "Started",
                "Model",
                "Persona",
                "Preset",
                "Accuracy",
                "Trust",
                "Quality",
                "TPS",
                "TTFT",
                "Total",
                "Input tok",
                "Output tok",
            ]
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        return table

    @staticmethod
    def _combo_model_names(model_box: QComboBox | None) -> list[str]:
        if model_box is None:
            return []

        models = []
        seen = set()
        for index in range(model_box.count()):
            model_value = model_box.itemData(index, Qt.UserRole)
            model_name = str(model_value or model_box.itemText(index) or "").strip()
            if not model_name or model_name in seen:
                continue
            models.append(model_name)
            seen.add(model_name)
        return models

    def active_app_model_name(self) -> str:
        if hasattr(self.app_window, "current_model_name"):
            try:
                model = str(self.app_window.current_model_name() or "").strip()
                if model:
                    return model
            except Exception:
                pass

        app_model_box = getattr(self.app_window, "model_box", None)
        if app_model_box is not None:
            try:
                model_value = app_model_box.currentData(Qt.UserRole)
            except Exception:
                model_value = None
            model = str(model_value or app_model_box.currentText() or "").strip()
            if model:
                return model

        return DEFAULT_MODEL_NAME

    def select_model(self, model_name: str) -> bool:
        model = str(model_name or "").strip()
        if not model:
            return False

        index = self.model_box.findData(model, Qt.UserRole)
        if index < 0:
            index = self.model_box.findText(model)
        if index < 0:
            self.model_box.addItem(model, model)
            index = self.model_box.count() - 1

        self.model_box.setCurrentIndex(index)
        return True

    def select_active_app_model(self):
        model = self.active_app_model_name()
        if self.select_model(model):
            self.status_label.setText(f"Ready: {model}")

    def _benchmark_model_changed(self, model_name: str):
        model = str(model_name or "").strip()
        if not model:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        if self.model_discovery_worker is not None:
            return
        self.status_label.setText(f"Ready: {model}")

    def selected_model_name(self) -> str:
        try:
            model_value = self.model_box.currentData(Qt.UserRole)
        except Exception:
            model_value = None

        return str(model_value or self.model_box.currentText() or "").strip()

    def refresh_models_from_app(self, set_status: bool = True):
        current = self.selected_model_name()
        app_model_box = getattr(self.app_window, "model_box", None)
        models = self._combo_model_names(app_model_box)
        active_model = self.active_app_model_name()

        for model in (current, active_model):
            if model and model not in models:
                models.insert(0, model)

        self._replace_model_items(models, preferred_model=current or active_model)

        if set_status:
            self.status_label.setText("Models loaded" if models else "No models")

    def refresh_models_from_runtime(self, show_errors: bool = True):
        if self.worker is not None and self.worker.isRunning():
            return

        previous_worker = self.model_discovery_worker
        if previous_worker is not None:
            try:
                previous_worker.stop()
            except Exception:
                pass

        if hasattr(self.app_window, "sync_runtime_client"):
            try:
                self.app_window.sync_runtime_client()
            except Exception as exc:
                log_warning(
                    "LlmBenchmarkDialog.refresh_models_from_runtime sync_runtime_client",
                    exc,
                )

        base_url = (
            self.app_window.current_base_url()
            if hasattr(self.app_window, "current_base_url")
            else ""
        )
        api_key = (
            self.app_window.current_api_key()
            if hasattr(self.app_window, "current_api_key")
            else ""
        )
        preferred_model = self.selected_model_name()
        self.status_label.setText("Refreshing models…")
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing…")
        self.use_active_model_button.setEnabled(False)
        self.model_box.setEnabled(False)
        self.run_button.setEnabled(False)
        self.run_all_button.setEnabled(False)

        worker = ModelDiscoveryWorker(base_url, api_key)
        self.model_discovery_worker = worker

        def handle_ready(models, current_worker=worker, selected_model=preferred_model):
            self.handle_model_discovery_ready(current_worker, models, selected_model)

        def handle_error(
            error_message, current_worker=worker, selected_model=preferred_model
        ):
            self.handle_model_discovery_error(
                current_worker, error_message, selected_model, show_errors
            )

        def handle_stopped(current_worker=worker):
            self.handle_model_discovery_stopped(current_worker)

        def handle_ollama_process_started(process):
            self.handle_ollama_process_started(process)

        def handle_finished(current_worker=worker):
            self.finish_model_discovery_worker(current_worker)

        worker.models_ready.connect(handle_ready)
        worker.error_received.connect(handle_error)
        worker.stopped.connect(handle_stopped)
        worker.ollama_process_started.connect(handle_ollama_process_started)
        worker.finished.connect(handle_finished)
        worker.start()

    def handle_model_discovery_ready(
        self, worker: ModelDiscoveryWorker, models: list[str], preferred_model: str
    ):
        if worker is not self.model_discovery_worker:
            return

        merged_models = list(models or [])
        for model in (preferred_model, self.active_app_model_name()):
            if model and model not in merged_models:
                merged_models.insert(0, model)

        self._replace_model_items(merged_models, preferred_model=preferred_model)
        self.status_label.setText(f"Loaded {len(merged_models or [])} model(s)")
        self._set_model_discovery_controls_enabled(True)

    def handle_model_discovery_error(
        self,
        worker: ModelDiscoveryWorker,
        error_message: str,
        preferred_model: str,
        show_error_dialog: bool = True,
    ):
        if worker is not self.model_discovery_worker:
            return

        existing_models = self._combo_model_names(self.model_box)
        for model in (preferred_model, self.active_app_model_name()):
            if model and model not in existing_models:
                existing_models.insert(0, model)
        if not existing_models:
            existing_models = [DEFAULT_MODEL_NAME]

        self._replace_model_items(existing_models, preferred_model=preferred_model)
        self.status_label.setText("Model refresh failed — kept local list")
        self._set_model_discovery_controls_enabled(True)
        if show_error_dialog:
            QMessageBox.warning(
                self,
                "Refresh Models",
                (
                    str(error_message or "No models found.")
                    + "\n\nKept the existing model list in the benchmark window."
                ),
            )

    def handle_model_discovery_stopped(self, worker: ModelDiscoveryWorker):
        if worker is self.model_discovery_worker:
            self.status_label.setText("Model refresh stopped")
            self._set_model_discovery_controls_enabled(True)

    def handle_ollama_process_started(self, process):
        try:
            self.app_window._fzastro_owned_ollama_process = process
        except Exception as exc:
            log_warning("LlmBenchmarkDialog.handle_ollama_process_started", exc)

    def finish_model_discovery_worker(self, worker: ModelDiscoveryWorker):
        if worker is self.model_discovery_worker:
            self.model_discovery_worker = None

        try:
            worker.deleteLater()
        except Exception:
            pass

    def _set_model_discovery_controls_enabled(self, enabled: bool):
        running = self.worker is not None and self.worker.isRunning()
        self.refresh_button.setEnabled(bool(enabled) and not running)
        self.refresh_button.setText("Refresh Models")
        self.use_active_model_button.setEnabled(bool(enabled) and not running)
        self.model_box.setEnabled(bool(enabled) and not running)
        self.run_button.setEnabled(bool(enabled) and not running)
        self.run_all_button.setEnabled(bool(enabled) and not running)

    def _replace_model_items(
        self, models: list[str], preferred_model: str | None = None
    ):
        clean_models = []
        seen = set()

        for model in models or []:
            clean_model = str(model or "").strip()
            if not clean_model or clean_model in seen:
                continue
            clean_models.append(clean_model)
            seen.add(clean_model)

        if not clean_models:
            clean_models = [DEFAULT_MODEL_NAME]

        current = str(preferred_model or self.model_box.currentText() or "").strip()
        if current and current not in clean_models:
            clean_models.insert(0, current)

        self.model_box.blockSignals(True)
        self.model_box.clear()
        for clean_model in clean_models:
            self.model_box.addItem(clean_model, clean_model)

        target_model = (
            current
            if current in clean_models
            else (clean_models[0] if clean_models else "")
        )
        if target_model:
            target_index = self.model_box.findData(target_model, Qt.UserRole)
            if target_index < 0:
                target_index = self.model_box.findText(target_model)
            if target_index >= 0:
                self.model_box.setCurrentIndex(target_index)
        self.model_box.blockSignals(False)
        if target_model:
            self.model_box.setToolTip(
                "Benchmark model selector. Uses the same model list/runtime endpoint as the main app.\n"
                f"Selected benchmark model: {target_model}"
            )

    def refresh_personas_from_app(self):
        current_key = self.selected_persona_key()
        profiles = getattr(self.app_window, "calibration_profiles", {}) or {}

        self.persona_box.blockSignals(True)
        self.persona_box.clear()
        self.persona_box.addItem(
            "Raw model (no persona)",
            {"kind": "baseline", "key": "baseline", "name": "Raw model"},
        )
        self.persona_box.addItem(
            "Active app persona",
            {"kind": "active", "key": "active", "name": "Active app persona"},
        )

        for profile_key, profile in profiles.items():
            clean_key = str(profile_key or "").strip()
            clean_name = str(profile.get("name") or clean_key or "Profile").strip()
            if not clean_key:
                continue
            self.persona_box.addItem(
                f"{clean_name} profile",
                {"kind": "profile", "key": clean_key, "name": clean_name},
            )

        target_index = 0
        if current_key:
            for index in range(self.persona_box.count()):
                data = self.persona_box.itemData(index, Qt.UserRole) or {}
                if str(data.get("key") or "") == current_key:
                    target_index = index
                    break
        self.persona_box.setCurrentIndex(target_index)
        self.persona_box.blockSignals(False)
        self._benchmark_persona_changed()

    def selected_persona_key(self) -> str:
        data = self.persona_box.currentData(Qt.UserRole)
        if isinstance(data, dict):
            return str(data.get("key") or "baseline").strip() or "baseline"
        return "baseline"

    def selected_persona_payload(self) -> dict[str, str]:
        data = self.persona_box.currentData(Qt.UserRole)
        if not isinstance(data, dict):
            data = {"kind": "baseline", "key": "baseline", "name": "Raw model"}

        kind = str(data.get("kind") or "baseline").strip()
        key = str(data.get("key") or kind or "baseline").strip()

        if kind == "active":
            active_key = str(
                getattr(self.app_window, "active_calibration_profile", "") or ""
            )
            profiles = getattr(self.app_window, "calibration_profiles", {}) or {}
            profile = profiles.get(active_key) or {}
            name = (
                str(profile.get("name") or active_key or "Custom").strip() or "Custom"
            )
            prompt_widget = getattr(self.app_window, "system_prompt", None)
            try:
                prompt = (
                    prompt_widget.toPlainText().strip()
                    if prompt_widget is not None
                    else ""
                )
            except Exception:
                prompt = ""
            return {
                "key": active_key or "active",
                "name": f"Active: {name}",
                "system_prompt": prompt,
            }

        if kind == "profile":
            profiles = getattr(self.app_window, "calibration_profiles", {}) or {}
            profile = profiles.get(key) or {}
            name = str(profile.get("name") or key or "Profile").strip() or "Profile"
            prompt = str(profile.get("prompt") or "").strip()
            return {"key": key, "name": name, "system_prompt": prompt}

        return {"key": "baseline", "name": "Raw model", "system_prompt": ""}

    def _benchmark_persona_changed(self):
        payload = self.selected_persona_payload()
        persona_name = payload.get("name") or "Raw model"
        system_prompt = payload.get("system_prompt") or ""
        if system_prompt:
            tip = (
                "Benchmark persona selector. This adds the chosen calibration/profile system prompt "
                "to the benchmark request without changing the main app profile.\n"
                f"Selected persona: {persona_name} • ~{LlmBenchmarkWorker._estimate_tokens(system_prompt)} system tokens"
            )
        else:
            tip = (
                "Benchmark persona selector. Raw model runs send no persona/system prompt, "
                "which is best for pure speed baselines."
            )
        self.persona_box.setToolTip(tip)

    def selected_preset(self):
        selected_name = self.preset_box.currentText().strip()
        for preset in BENCHMARK_PRESETS:
            if preset.name == selected_name:
                return preset
        return None

    def selected_suite_depth(self) -> str:
        try:
            value = self.suite_depth_box.currentData(Qt.UserRole)
        except Exception:
            value = None
        depth = str(value or "deep").strip().lower()
        return depth if depth in {"standard", "deep"} else "deep"

    def selected_repeat_count(self) -> int:
        try:
            return max(1, int(self.repeat_spin.value()))
        except Exception:
            return 1

    @staticmethod
    def _preset_prompts_for_depth(
        preset: BenchmarkPreset, suite_depth: str
    ) -> tuple[str, ...]:
        prompts = tuple(preset.prompts or ())
        if suite_depth == "standard":
            return prompts[:1]
        return prompts

    @staticmethod
    def _append_repeated_jobs(
        jobs: list[dict[str, Any]],
        *,
        preset_name: str,
        prompts: tuple[str, ...] | list[str],
        max_tokens: int,
        suite_depth: str,
        repeat_count: int,
    ):
        repeat_total = max(1, int(repeat_count or 1))
        for repeat_index in range(1, repeat_total + 1):
            for prompt_index, prompt in enumerate(prompts, start=1):
                jobs.append(
                    {
                        "preset": preset_name,
                        "prompt_name": f"Prompt {prompt_index}",
                        "prompt": prompt,
                        "max_tokens": max_tokens,
                        "suite_depth": suite_depth,
                        "repeat_index": repeat_index,
                        "repeat_total": repeat_total,
                    }
                )

    def _load_selected_preset(self):
        preset = self.selected_preset()
        self.prompt_list.clear()

        custom_mode = preset is None
        self.custom_prompt_caption.setVisible(custom_mode)
        self.custom_prompt_edit.setVisible(custom_mode)

        if preset is None:
            self.prompt_summary_label.setText(
                "Custom prompt mode. Type one prompt below, then use Run Selected. "
                "Run All Presets still executes the built-in suite."
            )
            if not self.custom_prompt_edit.toPlainText().strip():
                self.custom_prompt_edit.setPlaceholderText(
                    "Type a custom benchmark prompt here…"
                )
            return

        self.max_tokens_spin.setValue(preset.max_tokens)
        self.custom_prompt_edit.blockSignals(True)
        self.custom_prompt_edit.clear()
        self.custom_prompt_edit.blockSignals(False)

        suite_depth = self.selected_suite_depth()
        prompts = self._preset_prompts_for_depth(preset, suite_depth)
        for index, prompt in enumerate(prompts, start=1):
            item = QListWidgetItem(f"{index}. {prompt}")
            item.setToolTip(prompt)
            self.prompt_list.addItem(item)

        shown_count = len(prompts)
        total_count = len(preset.prompts)
        depth_label = "Deep" if suite_depth == "deep" else "Standard"
        self.prompt_summary_label.setText(
            f"{preset.name}: {shown_count} prompt(s) queued in {depth_label} mode. "
            f"{preset.subtitle} Select Custom Prompt to type your own test."
        )

        if suite_depth == "standard" and total_count > shown_count:
            item = QListWidgetItem(
                f"Standard mode selected. Switch Suite Depth to Deep to run all {total_count} prompts."
            )
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.prompt_list.addItem(item)

    def _custom_prompt_changed(self):
        if self.custom_prompt_edit.toPlainText().strip():
            self.preset_box.setCurrentText("Custom Prompt")
            self.prompt_list.clear()

    def benchmark_jobs(self):
        custom_prompt = self.custom_prompt_edit.toPlainText().strip()
        suite_depth = self.selected_suite_depth()
        repeat_count = self.selected_repeat_count()
        jobs: list[dict[str, Any]] = []

        if custom_prompt:
            self._append_repeated_jobs(
                jobs,
                preset_name="Custom Prompt",
                prompts=(custom_prompt,),
                max_tokens=int(self.max_tokens_spin.value()),
                suite_depth="custom",
                repeat_count=repeat_count,
            )
            return jobs

        preset = self.selected_preset()
        if preset is not None:
            self._append_repeated_jobs(
                jobs,
                preset_name=preset.name,
                prompts=self._preset_prompts_for_depth(preset, suite_depth),
                max_tokens=int(self.max_tokens_spin.value()),
                suite_depth=suite_depth,
                repeat_count=repeat_count,
            )
            return jobs

        return []

    def all_preset_jobs(self):
        jobs: list[dict[str, Any]] = []
        suite_depth = self.selected_suite_depth()
        repeat_count = self.selected_repeat_count()
        for preset in BENCHMARK_PRESETS:
            self._append_repeated_jobs(
                jobs,
                preset_name=preset.name,
                prompts=self._preset_prompts_for_depth(preset, suite_depth),
                max_tokens=preset.max_tokens,
                suite_depth=suite_depth,
                repeat_count=repeat_count,
            )
        return jobs

    def run_benchmark(self):
        self.start_benchmark(self.benchmark_jobs(), "Benchmark running…")

    def run_all_presets(self):
        self.start_benchmark(self.all_preset_jobs(), "Benchmark suite running…")

    def start_benchmark(self, jobs: list[dict[str, Any]], response_message: str):
        if self.worker is not None and self.worker.isRunning():
            return

        model = self.selected_model_name()
        persona = self.selected_persona_payload()

        if not model:
            QMessageBox.warning(
                self, "Benchmark", "Select a model before running a benchmark."
            )
            return

        if not jobs:
            QMessageBox.warning(self, "Benchmark", "Add at least one benchmark prompt.")
            return

        if hasattr(self.app_window, "sync_runtime_client"):
            try:
                self.app_window.sync_runtime_client()
            except Exception as exc:
                log_warning(
                    "LlmBenchmarkDialog.start_benchmark sync_runtime_client", exc
                )

        base_url = (
            self.app_window.current_base_url()
            if hasattr(self.app_window, "current_base_url")
            else ""
        )
        api_key = (
            self.app_window.current_api_key()
            if hasattr(self.app_window, "current_api_key")
            else ""
        )

        self.latest_table.setRowCount(0)
        persona_name = persona.get("name") or "Raw model"
        persona_note = (
            f"Persona: **{persona_name}**"
            if persona.get("system_prompt")
            else "Persona: **Raw model / no system prompt**"
        )
        self.response_browser.setMarkdown(
            f"{response_message}\n\nQueued prompts: **{len(jobs)}**. "
            f"{persona_note}. Use Stop to cancel the remaining prompts."
        )
        self.set_running_state(True)
        self.tabs.setCurrentWidget(self.dashboard_tab)

        self.worker = LlmBenchmarkWorker(
            base_url=base_url,
            api_key=api_key,
            model=model,
            jobs=jobs,
            temperature=float(self.temperature_spin.value()),
            system_prompt=persona.get("system_prompt", ""),
            persona_key=persona.get("key", "baseline"),
            persona_name=persona.get("name", "Raw model"),
            parent=self,
        )
        self.worker.progress.connect(self.status_label.setText)
        self.worker.sample_finished.connect(self.handle_sample_finished)
        self.worker.benchmark_finished.connect(self.handle_benchmark_finished)
        self.worker.benchmark_stopped.connect(self.handle_benchmark_stopped)
        self.worker.error_received.connect(self.handle_benchmark_error)
        self.worker.finished.connect(lambda: self.set_running_state(False))
        self.worker.start()

    def stop_benchmark(self):
        if self.worker is not None and self.worker.isRunning():
            self.status_label.setText("Stopping…")
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def set_running_state(self, running: bool):
        model_refreshing = self.model_discovery_worker is not None
        self.run_button.setEnabled(not running and not model_refreshing)
        self.run_all_button.setEnabled(not running and not model_refreshing)
        self.refresh_button.setEnabled(not running and not model_refreshing)
        self.use_active_model_button.setEnabled(not running and not model_refreshing)
        self.clear_history_button.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.model_box.setEnabled(not running and not model_refreshing)
        self.persona_box.setEnabled(not running)
        self.preset_box.setEnabled(not running)
        self.suite_depth_box.setEnabled(not running)
        self.repeat_spin.setEnabled(not running)
        self.temperature_spin.setEnabled(not running)
        self.max_tokens_spin.setEnabled(not running)
        self.custom_prompt_edit.setEnabled(not running)
        self.prompt_list.setEnabled(not running)
        self.update_history_action_state()
        if not running and self.status_label.text() in {"Stopping…", "Running…"}:
            self.status_label.setText("Idle")

    def result_response_markdown(self, result: dict) -> str:
        quality_score = _fmt_quality(result.get("quality_score"))
        accuracy_score = _fmt_quality(
            result.get("accuracy_score", result.get("quality_score"))
        )
        trust_score = _fmt_quality(result.get("trust_score"))
        instruction_score = _fmt_quality(result.get("instruction_score"))
        quality_label = str(result.get("quality_label") or "Unscored")
        quality_notes = result.get("quality_notes") or []
        if isinstance(quality_notes, str):
            quality_notes = [quality_notes]
        notes_text = (
            "\n".join(f"- {note}" for note in quality_notes)
            or "- No quality notes recorded."
        )
        trust_notes = result.get("trust_notes") or []
        if isinstance(trust_notes, str):
            trust_notes = [trust_notes]
        trust_text = (
            "\n".join(f"- {note}" for note in trust_notes)
            or "- No trust notes recorded."
        )
        grader_rows = []
        for grader in result.get("grader_results") or []:
            status = "PASS" if grader.get("passed") else "FAIL"
            score = _fmt_quality(grader.get("score"))
            grader_rows.append(
                f"| {grader.get('name', '')} | {status} | {score} | {grader.get('evidence', '')} |"
            )
        grader_text = (
            "| Check | Status | Score | Evidence |\n|---|---:|---:|---|\n"
            + "\n".join(grader_rows)
            if grader_rows
            else "No deterministic grader results recorded."
        )
        prompt_name = str(result.get("prompt_name") or "").strip()
        case_id = str(result.get("case_id") or "").strip()
        repeat_total = int(result.get("repeat_total") or 1)
        repeat_index = int(result.get("repeat_index") or 1)
        repeat_text = (
            f"\n**Repeat:** {repeat_index}/{repeat_total}" if repeat_total > 1 else ""
        )
        prompt_name_text = f"\n**Prompt ID:** {prompt_name}" if prompt_name else ""
        case_text = f"\n**Case ID:** `{case_id}`" if case_id else ""
        persona_name = str(result.get("persona_name") or "Raw model")
        system_tokens = int(result.get("system_prompt_tokens") or 0)
        persona_text = (
            f"**Persona:** {persona_name} (~{system_tokens} system tokens)\n\n"
            if system_tokens > 0
            else "**Persona:** Raw model / no system prompt\n\n"
        )
        gpu_text = str(result.get("gpu_telemetry") or "").strip()
        system_text = str(result.get("system_telemetry") or "").strip()
        telemetry_text = (
            f"**Telemetry snapshot:** {gpu_text} | {system_text}\n\n"
            if gpu_text or system_text
            else ""
        )
        return (
            f"**Preset:** {result.get('preset', '')}{prompt_name_text}{case_text}{repeat_text}\n\n"
            f"{persona_text}"
            f"{telemetry_text}"
            f"**Accuracy:** {accuracy_score}  |  **Speed:** {_fmt_tps(result.get('tokens_per_second'))}  |  "
            f"**Trust:** {trust_score}  |  **Instruction:** {instruction_score}\n\n"
            f"**Overall quality:** {quality_score} — {quality_label} "
            f"_({result.get('quality_method', 'benchmark checks')})_\n\n"
            f"**Deterministic grader evidence:**\n\n{grader_text}\n\n"
            f"**Quality / trust notes:**\n{notes_text}\n\n**Trust notes:**\n{trust_text}\n\n---\n\n"
            f"**Prompt:**\n\n{result.get('prompt', '')}\n\n---\n\n"
            f"**Response:**\n\n{result.get('response', '') or '_No text returned._'}"
        )

    def handle_sample_finished(self, result: dict):
        self.current_response_result_id = str(result.get("id") or "") or None
        self.refresh_telemetry_from_app()
        result["gpu_telemetry"] = self.gpu_telemetry_label.text()
        result["system_telemetry"] = self.system_telemetry_label.text()
        result["evidence"] = build_result_evidence(result)
        self.history.insert(0, result)
        save_benchmark_history(self.history)
        self.add_result_to_table(self.latest_table, result, prepend=False)
        self.response_browser.setMarkdown(self.result_response_markdown(result))
        self.refresh_history_tables()
        self.refresh_dashboard()

    def handle_benchmark_finished(self, payload: dict):
        results = payload.get("results") or []
        self.status_label.setText(f"Completed {len(results)} prompt(s)")
        self.refresh_history_tables()
        self.refresh_dashboard()

    def handle_benchmark_stopped(self, payload: dict):
        results = payload.get("results") or []
        self.status_label.setText(f"Stopped after {len(results)} prompt(s)")
        self.refresh_history_tables()
        self.refresh_dashboard()

    def handle_benchmark_error(self, message: str):
        self.status_label.setText("Error")
        self.set_running_state(False)
        QMessageBox.critical(
            self, "Benchmark Error", str(message or "Benchmark failed.")
        )

    def refresh_dashboard(self):
        completed = len(self.history)
        models = sorted(
            {entry.get("model", "") for entry in self.history if entry.get("model")}
        )
        tps_values = [
            float(entry.get("tokens_per_second") or 0.0) for entry in self.history
        ]
        ttft_values = [
            float(entry.get("time_to_first_token_s") or 0.0) for entry in self.history
        ]
        gen_values = [
            float(entry.get("generation_time_s") or 0.0) for entry in self.history
        ]
        accuracy_values = [
            float(entry.get("accuracy_score", entry.get("quality_score")))
            for entry in self.history
            if entry.get("accuracy_score", entry.get("quality_score")) is not None
        ]
        trust_values = [
            float(entry.get("trust_score"))
            for entry in self.history
            if entry.get("trust_score") is not None
        ]
        tps_stats = run_statistics(tps_values)

        self.metric_total_runs.set_metric(
            str(completed), f"{completed} completed, 0 errors"
        )
        self.metric_models_tested.set_metric(
            str(len(models)), f"{len(models)} model(s)"
        )
        self.metric_avg_accuracy.set_metric(
            _fmt_quality(_mean(accuracy_values)) if accuracy_values else "—",
            "deterministic graded checks",
        )
        self.metric_avg_trust.set_metric(
            _fmt_quality(_mean(trust_values)) if trust_values else "—",
            "auditability and evidence",
        )
        self.metric_avg_throughput.set_metric(
            _fmt_tps(tps_stats["mean"]),
            (
                f"p95 {_fmt_tps(tps_stats['p95'])}"
                if tps_values
                else "tokens/sec generation"
            ),
        )
        self.metric_avg_latency.set_metric(
            _fmt_seconds(_mean(ttft_values)), "time to first token"
        )
        self.metric_avg_stability.set_metric(
            _fmt_quality(_stability_score(tps_values)) if tps_values else "—",
            "throughput consistency",
        )
        self.metric_avg_gen.set_metric(
            _fmt_seconds(_mean(gen_values)), "token generation time"
        )

    def refresh_history_tables(self):
        self.populate_table(self.history_table, self.history)
        self.refresh_compare_table()
        self.update_history_action_state()

    def populate_table(self, table: QTableWidget, results: list[dict]):
        table.setRowCount(0)
        for result in results[:500]:
            self.add_result_to_table(table, result, prepend=False)

    def add_result_to_table(
        self, table: QTableWidget, result: dict, prepend: bool = False
    ):
        row = 0 if prepend else table.rowCount()
        table.insertRow(row)
        input_tokens = result.get("input_tokens")
        if input_tokens is None:
            input_tokens = int(result.get("prompt_tokens") or 0) + int(
                result.get("system_prompt_tokens") or 0
            )
        values = [
            _fmt_started(result.get("started_at")),
            result.get("model", ""),
            result.get("persona_name", "Raw model"),
            result.get("preset", ""),
            _fmt_quality(result.get("accuracy_score", result.get("quality_score"))),
            _fmt_quality(result.get("trust_score")),
            _fmt_quality(result.get("quality_score")),
            _fmt_tps(result.get("tokens_per_second")),
            _fmt_seconds(result.get("time_to_first_token_s")),
            _fmt_seconds(result.get("total_time_s")),
            str(input_tokens),
            str(result.get("completion_tokens", "")),
        ]
        result_id = str(result.get("id") or "")
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            item.setData(Qt.UserRole, result_id)
            table.setItem(row, column, item)

    def refresh_compare_table(self):
        grouped: dict[tuple[str, str], list[dict]] = {}
        for entry in self.history:
            model = str(entry.get("model") or "Unknown")
            persona = str(entry.get("persona_name") or "Raw model")
            grouped.setdefault((model, persona), []).append(entry)

        preset_names = {preset.name for preset in BENCHMARK_PRESETS}
        row_models = []
        for (model, persona), entries in grouped.items():
            tps = [float(entry.get("tokens_per_second") or 0.0) for entry in entries]
            ttft = [
                float(entry.get("time_to_first_token_s") or 0.0) for entry in entries
            ]
            accuracy = [
                float(entry.get("accuracy_score", entry.get("quality_score")))
                for entry in entries
                if entry.get("accuracy_score", entry.get("quality_score")) is not None
            ]
            instruction = [
                float(entry.get("instruction_score", entry.get("quality_score")))
                for entry in entries
                if entry.get("instruction_score", entry.get("quality_score"))
                is not None
            ]
            trust = [
                float(entry.get("trust_score"))
                for entry in entries
                if entry.get("trust_score") is not None
            ]
            covered_presets = {
                str(entry.get("preset") or "")
                for entry in entries
                if str(entry.get("preset") or "") in preset_names
            }
            coverage_count = len(covered_presets)
            coverage_ratio = coverage_count / max(1, len(preset_names))
            row_models.append(
                {
                    "model": model,
                    "persona": persona,
                    "runs": len(entries),
                    "coverage": f"{coverage_count}/{len(preset_names)}",
                    "coverage_score": coverage_ratio * 100.0,
                    "avg_accuracy": _mean(accuracy) if accuracy else 0.0,
                    "avg_instruction": _mean(instruction) if instruction else 0.0,
                    "avg_trust": _mean(trust) if trust else 0.0,
                    "avg_tps": _mean(tps),
                    "avg_ttft": _mean(ttft),
                    "stability": _stability_score(tps),
                }
            )

        max_tps = max((row["avg_tps"] for row in row_models), default=0.0)
        positive_ttft = [row["avg_ttft"] for row in row_models if row["avg_ttft"] > 0]
        best_ttft = min(positive_ttft) if positive_ttft else 0.0
        for row in row_models:
            throughput_score = (
                (row["avg_tps"] / max_tps * 100.0) if max_tps > 0 else 0.0
            )
            latency_score = (
                (best_ttft / row["avg_ttft"] * 100.0)
                if row["avg_ttft"] > 0 and best_ttft > 0
                else 0.0
            )
            row["speed_score"] = throughput_score * 0.70 + latency_score * 0.30
            row["composite"] = composite_score(
                accuracy=row["avg_accuracy"],
                speed=row["speed_score"],
                trust=row["avg_trust"],
                instruction=row["avg_instruction"],
                stability=row["stability"],
                coverage=row["coverage_score"],
            )

        row_models.sort(key=lambda row: row["composite"], reverse=True)
        self.compare_table.setRowCount(0)
        for row_index, row_data in enumerate(row_models):
            self.compare_table.insertRow(row_index)
            values = [
                row_data["model"],
                row_data["persona"],
                str(row_data["runs"]),
                row_data["coverage"],
                _fmt_quality(row_data["avg_accuracy"]),
                _fmt_quality(row_data["speed_score"]),
                _fmt_quality(row_data["avg_trust"]),
                _fmt_quality(row_data["avg_instruction"]),
                _fmt_quality(row_data["stability"]),
                _fmt_quality(row_data["composite"]),
                _fmt_tps(row_data["avg_tps"]),
                _fmt_seconds(row_data["avg_ttft"]),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.compare_table.setItem(row_index, column, item)

    def open_history_context_menu(self, position: QPoint):
        if self.worker is not None and self.worker.isRunning():
            return

        item = self.history_table.itemAt(position)
        if item is not None and not item.isSelected():
            self.history_table.selectRow(item.row())

        menu = QMenu(self)
        delete_action = QAction("Delete selected history record(s)", self)
        delete_action.setEnabled(bool(self.selected_history_record_ids()))
        delete_action.triggered.connect(self.delete_selected_history_records)
        menu.addAction(delete_action)
        menu.exec(self.history_table.viewport().mapToGlobal(position))

    def selected_history_record_ids(self) -> set[str]:
        table = getattr(self, "history_table", None)
        if table is None or table.selectionModel() is None:
            return set()

        record_ids = set()
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 0)
            if item is None:
                continue
            record_id = str(item.data(Qt.UserRole) or "").strip()
            if record_id:
                record_ids.add(record_id)

        return record_ids

    def update_history_action_state(self):
        button = getattr(self, "delete_history_button", None)
        if button is None:
            return

        running = self.worker is not None and self.worker.isRunning()
        button.setEnabled(bool(self.selected_history_record_ids()) and not running)

    def remove_ids_from_table(self, table: QTableWidget, record_ids: set[str]):
        if table is None or not record_ids:
            return

        for row in range(table.rowCount() - 1, -1, -1):
            item = table.item(row, 0)
            if item is None:
                continue
            record_id = str(item.data(Qt.UserRole) or "").strip()
            if record_id in record_ids:
                table.removeRow(row)

    def delete_selected_history_records(self):
        record_ids = self.selected_history_record_ids()
        if not record_ids:
            QMessageBox.information(
                self,
                "Delete benchmark history",
                "Select one or more history rows first.",
            )
            return

        count = len(record_ids)
        noun = "record" if count == 1 else "records"
        answer = QMessageBox.question(
            self,
            "Delete benchmark history",
            f"Delete {count} selected benchmark history {noun}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        before_count = len(self.history)
        self.history = [
            entry
            for entry in self.history
            if str(entry.get("id") or "").strip() not in record_ids
        ]
        deleted_count = before_count - len(self.history)
        if deleted_count <= 0:
            self.update_history_action_state()
            return

        save_benchmark_history(self.history)
        self.remove_ids_from_table(self.latest_table, record_ids)
        if self.current_response_result_id in record_ids:
            self.current_response_result_id = None
            self.response_browser.setMarkdown(
                "Run a benchmark to see the model output here."
            )
        self.refresh_history_tables()
        self.refresh_dashboard()
        self.status_label.setText(f"Deleted {deleted_count} history {noun}")

    def clear_history(self):
        if not self.history:
            return

        answer = QMessageBox.question(
            self,
            "Clear benchmark history",
            "Clear all saved benchmark history?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.history = []
        self.current_response_result_id = None
        save_benchmark_history(self.history)
        self.latest_table.setRowCount(0)
        self.response_browser.setMarkdown(
            "Run a benchmark to see the model output here."
        )
        self.refresh_history_tables()
        self.refresh_dashboard()
        self.status_label.setText("History cleared")

    def export_history(self):
        if not self.history:
            QMessageBox.information(
                self, "Export Benchmark History", "No benchmark history to export."
            )
            return

        default_path = Path.home() / "llm_benchmark_history.json"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export benchmark history",
            str(default_path),
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            Path(path).write_text(json.dumps(self.history, indent=2), encoding="utf-8")
            self.status_label.setText("Exported")
        except Exception as exc:
            log_exception("LlmBenchmarkDialog.export_history", exc)
            QMessageBox.critical(self, "Export Benchmark History", str(exc))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)

        if self.model_discovery_worker is not None:
            try:
                self.model_discovery_worker.stop()
                self.model_discovery_worker.wait(1500)
            except Exception as exc:
                log_warning("LlmBenchmarkDialog.closeEvent model discovery", exc)

        super().closeEvent(event)


def _mean(values):
    clean_values = [float(value) for value in values if value is not None]
    if not clean_values:
        return 0.0
    return statistics.fmean(clean_values)


def _fmt_seconds(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
    if number >= 60:
        return f"{number:.1f}s"
    return f"{number:.2f}s"


def _fmt_tps(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
    return f"{number:.1f}"


def _prompt_hash(text: str) -> str:
    clean_text = str(text or "").strip()
    if not clean_text:
        return ""
    return hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:12]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(text or "")))


def _contains_any(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    value = str(text or "").casefold()
    return any(str(pattern).casefold() in value for pattern in patterns)


def _has_number_like(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    value = re.sub(r"[,\s]+", "", str(text or "").casefold())
    return any(
        str(pattern).casefold().replace(" ", "") in value for pattern in patterns
    )


def _extract_json_object(text: str):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        return json.loads(value)
    except Exception:
        pass

    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _add_quality_check(
    notes: list[str], passed: bool, points: float, pass_note: str, fail_note: str
) -> float:
    if passed:
        notes.append(f"PASS: {pass_note}")
        return points
    notes.append(f"CHECK: {fail_note}")
    return 0.0


def _generic_quality_score(response: str, max_tokens: int, notes: list[str]) -> float:
    words = _word_count(response)
    score = 0.0
    score += _add_quality_check(
        notes,
        bool(str(response or "").strip()),
        20.0,
        "response is non-empty",
        "empty response",
    )
    score += _add_quality_check(
        notes,
        words >= 20,
        12.0,
        "response has enough substance for inspection",
        "response is very short",
    )
    score += _add_quality_check(
        notes,
        not _contains_any(
            response,
            (
                "as an ai language model",
                "i cannot answer",
                "i can't answer",
                "sorry, but i can't",
            ),
        ),
        10.0,
        "no obvious refusal boilerplate",
        "possible refusal/boilerplate detected",
    )
    tokens_estimate = max(1, len(str(response or "")) // 4)
    score += _add_quality_check(
        notes,
        tokens_estimate < max(16, int(max_tokens or 0)) * 0.98,
        8.0,
        "does not look max-token truncated",
        "may have hit the max-token ceiling",
    )
    return score


def evaluate_response_quality(
    *, preset_name: str, prompt: str, response: str, max_tokens: int
) -> dict[str, Any]:
    """Return a lightweight local sense-check score for benchmark output.

    This is intentionally heuristic. It helps flag obviously weak, truncated, or
    instruction-breaking answers so speed is not the only comparison signal.
    """
    notes: list[str] = []
    preset = str(preset_name or "").casefold()
    prompt_text = str(prompt or "").casefold()
    response_text = str(response or "")
    response_lower = response_text.casefold()

    score = _generic_quality_score(response_text, max_tokens, notes)

    if "math reasoning" in preset:
        if "train leaves station" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(
                    response_text, ("80", "1.33", "1.333", "1h20", "1hour20")
                ),
                28.0,
                "contains the expected meeting time around 80 minutes / 1.33 hours",
                "expected meeting time around 80 minutes / 1.33 hours not found",
            )
            score += _add_quality_check(
                notes,
                _contains_any(response_text, ("60", "75", "135", "180")),
                12.0,
                "uses the relative-speed setup",
                "relative-speed setup not obvious",
            )
        elif "240 light frames" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("12", "12.0")),
                24.0,
                "finds 12 light-frame exposure hours",
                "expected 12 light-frame exposure hours not found",
            )
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("140",)),
                16.0,
                "finds 140 calibration frames",
                "expected 140 calibration frames not found",
            )
        elif "800 mm focal length" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("0.97", "0.969", "0.96")),
                26.0,
                "estimates image scale near 0.97 arcsec/pixel",
                "expected image scale near 0.97 arcsec/pixel not found",
            )
            score += _add_quality_check(
                notes,
                _contains_any(response_text, ("206.265", "arcsec", "pixel")),
                14.0,
                "uses the requested image-scale formula context",
                "formula context is incomplete",
            )
        else:
            score += _add_quality_check(
                notes,
                _contains_any(
                    response_text, ("because", "therefore", "calculation", "=")
                ),
                30.0,
                "shows reasoning/calculation",
                "reasoning/calculation is hard to identify",
            )

    elif "logical reasoning" in preset:
        if "roses" in prompt_text:
            score += _add_quality_check(
                notes,
                _contains_any(
                    response_text,
                    ("cannot", "can't", "not conclude", "does not follow", "no"),
                ),
                32.0,
                "identifies that the conclusion does not follow",
                "may incorrectly accept the conclusion",
            )
        elif "three filters" in prompt_text:
            score += _add_quality_check(
                notes,
                _contains_any(
                    response_text,
                    (
                        "cannot determine",
                        "not enough",
                        "ambiguous",
                        "two possible",
                        "not uniquely",
                    ),
                ),
                32.0,
                "recognizes the schedule is not uniquely determined",
                "may overstate an ambiguous filter schedule",
            )
        elif "corrupted" in prompt_text:
            score += _add_quality_check(
                notes,
                _contains_any(
                    response_text,
                    ("cannot be calibrated", "not calibrated", "no", "contradiction"),
                ),
                32.0,
                "applies the corrupted-frame contradiction correctly",
                "expected conclusion that the corrupted frame cannot be calibrated is unclear",
            )
        score += _add_quality_check(
            notes,
            _word_count(response_text) <= 140,
            8.0,
            "stays reasonably concise",
            "answer is much longer than needed",
        )

    elif "data analysis" in preset:
        if "coffee shop revenue" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("1413", "1,413")),
                16.0,
                "finds $1,413 total revenue",
                "expected $1,413 total revenue not found",
            )
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("201.86", "201.9", "202")),
                12.0,
                "finds average around $201.86",
                "expected average around $201.86 not found",
            )
            score += _add_quality_check(
                notes,
                "sat" in response_lower or "saturday" in response_lower,
                12.0,
                "identifies Saturday as best day",
                "expected Saturday as best day not found",
            )
        elif "seeing values" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("1.99", "2.0", "1.986")),
                14.0,
                "finds average seeing around 1.99 arcsec",
                "expected average seeing around 1.99 arcsec not found",
            )
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("1.4", "2.7")),
                14.0,
                "identifies best/worst seeing values",
                "best/worst seeing values not clear",
            )
            score += _add_quality_check(
                notes,
                _contains_any(response_text, ("high-resolution", "schedule", "seeing")),
                12.0,
                "includes scheduling advice",
                "scheduling advice missing",
            )
        elif "tps values" in prompt_text:
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("28",)),
                16.0,
                "finds mean/median 28",
                "expected mean/median 28 not found",
            )
            score += _add_quality_check(
                notes,
                _has_number_like(response_text, ("7",)),
                10.0,
                "finds range 7",
                "expected range 7 not found",
            )
            score += _add_quality_check(
                notes,
                _contains_any(
                    response_text, ("stable", "comparison", "variance", "range")
                ),
                14.0,
                "comments on stability",
                "stability comment missing",
            )

    elif "instruction following" in preset:
        if "exactly 5 fruits" in prompt_text:
            fruit_hits = sum(
                1
                for fruit in (
                    "mango",
                    "melon",
                    "mandarin",
                    "mulberry",
                    "mangosteen",
                    "mirabelle",
                    "muskmelon",
                    "marionberry",
                )
                if fruit in response_lower
            )
            score += _add_quality_check(
                notes,
                "|" in response_text and fruit_hits >= 5,
                34.0,
                "returns a markdown-style fruit table with five M fruits",
                "markdown table or five M fruits not obvious",
            )
        elif "exactly 7 bullet" in prompt_text:
            bullet_count = len(re.findall(r"(?m)^\s*[-*•]\s+", response_text))
            score += _add_quality_check(
                notes,
                bullet_count == 7,
                34.0,
                "returns exactly seven bullets",
                f"found {bullet_count} bullet lines, expected seven",
            )
        elif "json object" in prompt_text:
            payload = _extract_json_object(response_text)
            has_keys = isinstance(payload, dict) and {
                "model",
                "benchmark",
                "metrics",
                "verdict",
            }.issubset(payload)
            metrics = payload.get("metrics") if isinstance(payload, dict) else None
            numeric_metrics = (
                isinstance(metrics, dict)
                and isinstance(metrics.get("tokens_per_second"), (int, float))
                and isinstance(metrics.get("quality_score"), (int, float))
            )
            score += _add_quality_check(
                notes,
                has_keys and numeric_metrics,
                34.0,
                "returns parseable JSON with required keys and numeric metrics",
                "JSON object or required numeric metrics are invalid",
            )
        score += _add_quality_check(
            notes,
            not response_text.strip().startswith("Here"),
            6.0,
            "avoids extra introduction",
            "may include extra introduction",
        )

    elif "code generation" in preset:
        score += _add_quality_check(
            notes,
            _contains_any(response_text, ("def ", "class ", "@dataclass")),
            16.0,
            "contains Python function/class structure",
            "Python function/class structure not found",
        )
        score += _add_quality_check(
            notes,
            _contains_any(response_text, ("assert ", "pytest", "unittest", "test_")),
            14.0,
            "includes tests or test-style assertions",
            "tests are missing or unclear",
        )
        score += _add_quality_check(
            notes,
            _contains_any(response_text, ("try", "raise", "valueerror", "none", "if ")),
            10.0,
            "mentions edge/error handling",
            "edge/error handling not obvious",
        )

    elif "creative writing" in preset:
        score += _add_quality_check(
            notes,
            _word_count(response_text) >= 250,
            24.0,
            "meets the requested long-form length",
            "creative response is shorter than requested",
        )
        score += _add_quality_check(
            notes,
            _contains_any(
                response_text,
                ("observatory", "telescope", "mars", "satellite", "orbit", "storm"),
            ),
            10.0,
            "keeps to the requested scene/topic",
            "scene/topic alignment is unclear",
        )
        score += _add_quality_check(
            notes,
            not _contains_any(response_text, ("once upon a time", "in conclusion")),
            6.0,
            "avoids obvious boilerplate phrasing",
            "boilerplate phrasing detected",
        )

    elif "translation" in preset:
        score += _add_quality_check(
            notes,
            bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", response_text))
            or "japanese" in response_lower,
            14.0,
            "includes Japanese content/label",
            "Japanese translation not obvious",
        )
        score += _add_quality_check(
            notes,
            bool(re.search(r"[\u0370-\u03ff]", response_text))
            or "greek" in response_lower,
            14.0,
            "includes Greek content/label",
            "Greek translation not obvious",
        )
        score += _add_quality_check(
            notes,
            _contains_any(
                response_text, ("summary", "meaning", "hard to translate", "terms")
            ),
            12.0,
            "includes the requested summary/translation notes",
            "requested summary/translation notes missing",
        )

    elif "summarization" in preset:
        key_terms = (
            "attention",
            "positional",
            "feed-forward",
            "dark",
            "flat",
            "bias",
            "streaming",
            "throughput",
            "model discovery",
        )
        hits = sum(1 for term in key_terms if term in response_lower)
        score += _add_quality_check(
            notes,
            hits >= 3,
            24.0,
            "covers several required technical concepts",
            "coverage of required technical concepts may be thin",
        )
        score += _add_quality_check(
            notes,
            _word_count(response_text) <= 350,
            10.0,
            "summary stays compact",
            "summary may be too long",
        )
        score += _add_quality_check(
            notes,
            _contains_any(response_text, ("-", "•", "1.", "2.")),
            6.0,
            "uses compact structure",
            "compact structure not obvious",
        )

    elif "quick q&a" in preset:
        score += _add_quality_check(
            notes,
            _word_count(response_text) <= 120,
            18.0,
            "keeps the short-answer style",
            "answer may be too long for quick Q&A",
        )
        score += _add_quality_check(
            notes,
            _contains_any(
                response_text,
                (
                    "moon",
                    "phase",
                    "atmosphere",
                    "turbulence",
                    "horizon",
                    "altitude",
                    "light pollution",
                    "sky",
                ),
            ),
            22.0,
            "uses relevant science terms",
            "relevant science terms not obvious",
        )

    else:
        score += _add_quality_check(
            notes,
            _word_count(response_text) >= 30,
            30.0,
            "custom response has enough content to inspect",
            "custom response is very short",
        )

    score = max(0.0, min(100.0, score))
    if score >= 85:
        label = "Strong"
    elif score >= 70:
        label = "Good"
    elif score >= 50:
        label = "Needs review"
    else:
        label = "Weak"

    return {
        "score": round(score, 1),
        "label": label,
        "notes": notes[:8],
        "method": "local heuristic v2",
    }


def _stability_score(values) -> float:
    clean_values = [float(value) for value in values if float(value or 0.0) > 0.0]
    if not clean_values:
        return 0.0
    if len(clean_values) == 1:
        return 100.0
    mean_value = statistics.fmean(clean_values)
    if mean_value <= 0:
        return 0.0
    coefficient = statistics.pstdev(clean_values) / mean_value
    return max(0.0, min(100.0, 100.0 * (1.0 - min(coefficient, 1.0))))


def _fmt_quality(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
    return f"{number:.0f}/100"


def _fmt_started(value: str) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value or "")


def load_benchmark_history() -> list[dict]:
    try:
        if not BENCHMARK_HISTORY_FILE.exists():
            return []
        payload = json.loads(BENCHMARK_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
    except Exception as exc:
        log_warning("load_benchmark_history", exc)
    return []


def save_benchmark_history(history: list[dict]):
    try:
        BENCHMARK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        trimmed = list(history or [])[:1000]
        temp_path = BENCHMARK_HISTORY_FILE.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")
        temp_path.replace(BENCHMARK_HISTORY_FILE)
    except Exception as exc:
        log_exception("save_benchmark_history", exc)


def open_llm_benchmark_dialog(app_window):
    if app_window is not None and hasattr(app_window, "open_workspace_tab"):
        def _clear_reference(_widget=None):
            try:
                if getattr(app_window, "llm_benchmark_dialog", None) is _widget:
                    setattr(app_window, "llm_benchmark_dialog", None)
            except Exception:
                pass

        def _create_benchmark_tab():
            dialog = LlmBenchmarkDialog(app_window)
            app_window.llm_benchmark_dialog = dialog
            dialog.destroyed.connect(lambda *_args: _clear_reference(dialog))
            return dialog

        return app_window.open_workspace_tab(
            "llm.benchmark",
            "LLM BENCH",
            _create_benchmark_tab,
            tooltip="LLM benchmark dashboard",
            on_close=_clear_reference,
        )

    existing = getattr(app_window, "llm_benchmark_dialog", None)
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:
            pass

    dialog = LlmBenchmarkDialog(app_window)
    app_window.llm_benchmark_dialog = dialog
    dialog.destroyed.connect(
        lambda *_args: setattr(app_window, "llm_benchmark_dialog", None)
    )
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog

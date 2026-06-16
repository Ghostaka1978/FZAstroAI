"""Deterministic LLM benchmark scoring helpers.

The benchmark dashboard should be useful as a local model decision tool.  This
module keeps the non-UI evaluation logic separate from the PySide dialog so the
scoring rules can be tested, versioned, and exported with each run.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from typing import Any

BENCHMARK_ENGINE_VERSION = "2.0"


@dataclass(frozen=True)
class GraderSpec:
    """Declarative deterministic check for one benchmark prompt."""

    grader: str
    name: str
    weight: float = 1.0
    expected: Any = None
    tolerance: float | None = None
    pattern: str = ""
    flags: int = re.IGNORECASE | re.MULTILINE
    required_keys: tuple[str, ...] = ()
    min_count: int | None = None
    max_count: int | None = None
    min_words: int | None = None
    max_words: int | None = None
    category: str = "accuracy"


@dataclass(frozen=True)
class BenchmarkCase:
    """One prompt plus the checks that make it auditable."""

    case_id: str
    category: str
    prompt: str
    graders: tuple[GraderSpec, ...] = ()
    tags: tuple[str, ...] = ()
    expected_answer: str = ""
    max_tokens: int | None = None


@dataclass(frozen=True)
class GraderResult:
    name: str
    grader: str
    category: str
    score: float
    weight: float
    passed: bool
    note: str
    evidence: str = ""


def case_id_for_prompt(preset_name: str, prompt: str) -> str:
    """Build a stable human-readable case id from a preset and prompt."""

    import hashlib

    slug = re.sub(r"[^a-z0-9]+", "_", str(preset_name or "custom").lower()).strip("_")
    digest = hashlib.sha256(
        str(prompt or "").encode("utf-8", errors="ignore")
    ).hexdigest()[:10]
    return f"{slug or 'custom'}_{digest}"


def prompt_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[
        :16
    ]


def estimate_tokens(text: str) -> int:
    clean_text = str(text or "")
    if not clean_text:
        return 0
    return max(1, len(clean_text) // 4)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(text or "")))


def _extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?", str(text or "")):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return values


def _extract_json_object(text: str) -> Any:
    clean = str(text or "").strip()
    if not clean:
        return None
    try:
        return json.loads(clean)
    except Exception:
        pass

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    first = clean.find("{")
    last = clean.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(clean[first : last + 1])
        except Exception:
            return None
    return None


def _grade_numeric_tolerance(spec: GraderSpec, response: str) -> GraderResult:
    expected = float(spec.expected)
    tolerance = float(spec.tolerance if spec.tolerance is not None else 0.0)
    numbers = _extract_numbers(response)
    closest = min(numbers, key=lambda value: abs(value - expected), default=None)
    passed = closest is not None and abs(closest - expected) <= tolerance
    evidence = "" if closest is None else f"closest={closest:g}, expected={expected:g}"
    return _result(spec, passed, evidence=evidence)


def _grade_exact_match(spec: GraderSpec, response: str) -> GraderResult:
    expected = str(spec.expected or "").strip()
    passed = response.strip() == expected
    return _result(spec, passed, evidence="exact" if passed else "response differs")


def _grade_regex_contains(spec: GraderSpec, response: str) -> GraderResult:
    passed = bool(re.search(spec.pattern, response, spec.flags))
    return _result(spec, passed, evidence=spec.pattern)


def _grade_json_schema(spec: GraderSpec, response: str) -> GraderResult:
    payload = _extract_json_object(response)
    required = set(spec.required_keys or ())
    has_keys = isinstance(payload, dict) and required.issubset(payload)
    passed = has_keys
    evidence = "valid json object" if passed else "missing json object/required keys"
    return _result(spec, passed, evidence=evidence)


def _grade_bullet_count(spec: GraderSpec, response: str) -> GraderResult:
    count = len(re.findall(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", response))
    passed = True
    if spec.min_count is not None:
        passed = passed and count >= spec.min_count
    if spec.max_count is not None:
        passed = passed and count <= spec.max_count
    return _result(spec, passed, evidence=f"count={count}")


def _grade_markdown_table(spec: GraderSpec, response: str) -> GraderResult:
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    pipe_rows = [line for line in lines if "|" in line]
    has_separator = any(re.search(r"\|?\s*:?-{3,}:?\s*\|", line) for line in pipe_rows)
    count = max(0, len(pipe_rows) - (1 if has_separator else 0) - 1)
    passed = bool(pipe_rows and has_separator)
    if spec.min_count is not None:
        passed = passed and count >= spec.min_count
    if spec.max_count is not None:
        passed = passed and count <= spec.max_count
    return _result(spec, passed, evidence=f"table_rows={count}")


def _grade_word_count(spec: GraderSpec, response: str) -> GraderResult:
    count = _word_count(response)
    passed = True
    if spec.min_words is not None:
        passed = passed and count >= spec.min_words
    if spec.max_words is not None:
        passed = passed and count <= spec.max_words
    return _result(spec, passed, evidence=f"words={count}")


def _result(spec: GraderSpec, passed: bool, evidence: str = "") -> GraderResult:
    return GraderResult(
        name=spec.name,
        grader=spec.grader,
        category=spec.category or "accuracy",
        score=100.0 if passed else 0.0,
        weight=max(0.0, float(spec.weight or 0.0)),
        passed=bool(passed),
        note=f"{spec.name}: {'pass' if passed else 'fail'}",
        evidence=str(evidence or ""),
    )


_GRADER_FUNCTIONS = {
    "exact_match": _grade_exact_match,
    "numeric_tolerance": _grade_numeric_tolerance,
    "regex_contains": _grade_regex_contains,
    "json_schema": _grade_json_schema,
    "bullet_count": _grade_bullet_count,
    "markdown_table": _grade_markdown_table,
    "word_count": _grade_word_count,
}


def infer_graders(preset_name: str, prompt: str) -> tuple[GraderSpec, ...]:
    """Infer deterministic checks for built-in prompts.

    These checks intentionally cover the high-signal facts in the prompt.  They
    are not a replacement for human review, but they make the score auditable.
    """

    preset = str(preset_name or "").lower()
    prompt_lower = str(prompt or "").lower()

    def regex(name: str, pattern: str, weight: float = 1.0, category: str = "accuracy"):
        return GraderSpec(
            grader="regex_contains",
            name=name,
            pattern=pattern,
            weight=weight,
            category=category,
        )

    def numeric(name: str, expected: float, tolerance: float, weight: float = 1.0):
        return GraderSpec(
            grader="numeric_tolerance",
            name=name,
            expected=expected,
            tolerance=tolerance,
            weight=weight,
        )

    if "math reasoning" in preset:
        if "180 miles" in prompt_lower and "75 mph" in prompt_lower:
            return (
                regex("states combined speed", r"\b135\b|60\s*\+\s*75", 1.0),
                regex("finds meeting time", r"1\s*(?:hour|hr)|80\s*minutes|1\.33", 2.0),
            )
        if "240 light frames" in prompt_lower:
            return (
                numeric("finds light hours", 12.0, 0.05, 2.0),
                numeric("finds calibration frame count", 140.0, 0.0, 1.0),
            )
        if "image scale" in prompt_lower:
            return (numeric("finds image scale", 0.97, 0.04, 2.0),)

    if "logical reasoning" in preset:
        if "some roses fade" in prompt_lower:
            return (
                regex(
                    "does not overclaim",
                    r"\b(no|cannot|can't|not\s+necessarily)\b",
                    2.0,
                ),
            )
        if "which filter is used tuesday" in prompt_lower:
            return (regex("finds Tuesday filter", r"\bO\s*-?III\b|\bOIII\b", 2.0),)
        if "new frame is corrupted" in prompt_lower:
            return (
                regex(
                    "rejects calibrated conclusion",
                    r"\b(cannot|can't|not)\b.*\bcalibrated\b",
                    2.0,
                ),
            )

    if "data analysis" in preset:
        if "coffee shop revenue" in prompt_lower:
            return (
                numeric("finds total revenue", 1413.0, 0.5, 2.0),
                numeric("finds average revenue", 201.86, 1.0, 1.0),
                regex("finds best day", r"\bSat(?:urday)?\b", 1.0),
            )
        if "seeing values" in prompt_lower:
            return (
                numeric("finds average seeing", 1.99, 0.05, 2.0),
                numeric("finds best seeing", 1.4, 0.01, 1.0),
                numeric("finds worst seeing", 2.7, 0.01, 1.0),
            )
        if "tps values" in prompt_lower:
            return (
                numeric("finds mean TPS", 28.0, 0.01, 1.0),
                numeric("finds median TPS", 28.0, 0.01, 1.0),
                numeric("finds TPS range", 7.0, 0.01, 1.0),
            )

    if "instruction following" in preset:
        if "exactly 5 fruits" in prompt_lower:
            return (
                GraderSpec(
                    grader="markdown_table",
                    name="returns markdown table with five rows",
                    min_count=5,
                    max_count=5,
                    weight=2.0,
                    category="instruction",
                ),
                regex(
                    "uses M fruits",
                    r"\b(mango|melon|mandarin|mulberry|mangosteen|mirabelle|muskmelon)\b",
                    1.0,
                ),
            )
        if "exactly 7 bullet" in prompt_lower:
            return (
                GraderSpec(
                    grader="bullet_count",
                    name="returns exactly seven bullets",
                    min_count=7,
                    max_count=7,
                    weight=2.0,
                    category="instruction",
                ),
            )
        if "json object" in prompt_lower:
            return (
                GraderSpec(
                    grader="json_schema",
                    name="returns JSON with required keys",
                    required_keys=("model", "benchmark", "metrics", "verdict"),
                    weight=2.0,
                    category="instruction",
                ),
                regex("keeps JSON-only style", r"^\s*\{.*\}\s*$", 1.0, "instruction"),
            )

    if "code generation" in preset:
        return (
            regex("contains Python definition", r"\b(def|class)\s+\w+", 1.5),
            regex("includes tests", r"\b(assert|pytest|unittest|test_)\b", 1.0),
            regex(
                "mentions edge/error handling",
                r"\b(raise|try|except|ValueError|None)\b",
                0.8,
            ),
        )

    if "quick q&a" in preset:
        return (
            GraderSpec(
                grader="word_count",
                name="keeps compact answer",
                max_words=120,
                weight=1.0,
                category="instruction",
            ),
            regex(
                "uses relevant science terms",
                r"moon|phase|atmosphere|turbulence|horizon|altitude|sky|light pollution",
                1.0,
            ),
        )

    if "creative writing" in preset:
        return (
            GraderSpec(
                grader="word_count",
                name="meets long-form length",
                min_words=250,
                weight=1.0,
                category="instruction",
            ),
            regex(
                "stays on requested scene",
                r"observatory|telescope|Mars|satellite|orbit|storm",
                1.0,
            ),
        )

    if "translation" in preset:
        return (
            regex(
                "includes non-Latin/Greek script where requested",
                r"[\u0370-\u03ff\u3040-\u30ff\u4e00-\u9fff]",
                1.0,
            ),
            regex(
                "includes requested summary or translation notes",
                r"summary|meaning|hard to translate|terms",
                1.0,
            ),
        )

    if "summarization" in preset:
        return (
            regex(
                "covers required technical terms",
                r"attention|positional|feed-forward|dark|flat|bias|streaming|throughput|model discovery",
                1.0,
            ),
            GraderSpec(
                grader="word_count",
                name="stays compact",
                max_words=380,
                weight=0.8,
                category="instruction",
            ),
        )

    return ()


def run_graders(
    *,
    preset_name: str,
    prompt: str,
    response: str,
    graders: tuple[GraderSpec, ...] | list[GraderSpec] | None = None,
) -> list[GraderResult]:
    specs = tuple(graders or infer_graders(preset_name, prompt))
    results: list[GraderResult] = []
    for spec in specs:
        grader_fn = _GRADER_FUNCTIONS.get(spec.grader)
        if grader_fn is None:
            results.append(
                GraderResult(
                    name=spec.name or spec.grader,
                    grader=spec.grader,
                    category=spec.category or "accuracy",
                    score=0.0,
                    weight=max(0.0, float(spec.weight or 0.0)),
                    passed=False,
                    note=f"{spec.name or spec.grader}: unsupported grader",
                    evidence="unsupported",
                )
            )
            continue
        try:
            results.append(grader_fn(spec, response))
        except Exception as exc:
            results.append(
                GraderResult(
                    name=spec.name or spec.grader,
                    grader=spec.grader,
                    category=spec.category or "accuracy",
                    score=0.0,
                    weight=max(0.0, float(spec.weight or 0.0)),
                    passed=False,
                    note=f"{spec.name or spec.grader}: grader error",
                    evidence=str(exc),
                )
            )
    return results


def weighted_score(
    results: list[GraderResult], category: str | None = None
) -> float | None:
    selected = [
        result
        for result in results
        if result.weight > 0 and (category is None or result.category == category)
    ]
    if not selected:
        return None
    weight_total = sum(result.weight for result in selected)
    if weight_total <= 0:
        return None
    return sum(result.score * result.weight for result in selected) / weight_total


def trust_score_for_result(
    *,
    prompt: str,
    response: str,
    max_tokens: int,
    deterministic_grader_count: int,
    repeat_total: int,
    token_estimation_method: str,
    model: str,
    base_url: str,
) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 100.0

    if not str(model or "").strip():
        score -= 25.0
        notes.append("model name missing")
    if not str(base_url or "").strip():
        score -= 10.0
        notes.append("runtime/base URL not recorded")
    if not str(prompt or "").strip():
        score -= 25.0
        notes.append("prompt missing")
    if not str(response or "").strip():
        score = min(score, 20.0)
        notes.append("empty response")
    if deterministic_grader_count <= 0:
        score -= 25.0
        notes.append("no deterministic grader attached; heuristic-only score")
    if "estimated" in str(token_estimation_method or "").lower():
        score -= 8.0
        notes.append("token counts are estimated")

    completion_estimate = estimate_tokens(response)
    if max_tokens > 0 and completion_estimate >= max_tokens * 0.95:
        score -= 8.0
        notes.append("response may have reached max-token cap")

    if repeat_total <= 1:
        score -= 4.0
        notes.append("single repeat; variance unknown")
    else:
        notes.append(f"repeat plan recorded: {repeat_total} per prompt")

    if deterministic_grader_count > 0:
        notes.append(f"{deterministic_grader_count} deterministic grader(s) recorded")

    return max(0.0, min(100.0, round(score, 1))), notes[:8]


def quality_label(score: float | None) -> str:
    if score is None:
        return "Unscored"
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Needs review"
    return "Weak"


def grade_benchmark_response(
    *,
    preset_name: str,
    prompt: str,
    response: str,
    max_tokens: int,
    model: str = "",
    base_url: str = "",
    repeat_total: int = 1,
    case_id: str = "",
    graders: tuple[GraderSpec, ...] | list[GraderSpec] | None = None,
    heuristic_score: float | None = None,
    heuristic_notes: list[str] | None = None,
    token_estimation_method: str = "estimated char/4",
) -> dict[str, Any]:
    """Return accuracy, instruction, trust, and compatibility quality fields."""

    clean_case_id = str(case_id or case_id_for_prompt(preset_name, prompt)).strip()
    grader_results = run_graders(
        preset_name=preset_name,
        prompt=prompt,
        response=response,
        graders=graders,
    )
    deterministic_score = weighted_score(grader_results)
    accuracy_score = weighted_score(grader_results, "accuracy")
    instruction_score = weighted_score(grader_results, "instruction")

    if accuracy_score is None:
        accuracy_score = deterministic_score
    if instruction_score is None:
        instruction_score = deterministic_score

    try:
        heuristic_value = None if heuristic_score is None else float(heuristic_score)
    except (TypeError, ValueError):
        heuristic_value = None

    if deterministic_score is None:
        quality_score = heuristic_value if heuristic_value is not None else 0.0
    elif heuristic_value is None:
        quality_score = deterministic_score
    else:
        quality_score = deterministic_score * 0.80 + heuristic_value * 0.20

    trust_score, trust_notes = trust_score_for_result(
        prompt=prompt,
        response=response,
        max_tokens=max_tokens,
        deterministic_grader_count=len(grader_results),
        repeat_total=repeat_total,
        token_estimation_method=token_estimation_method,
        model=model,
        base_url=base_url,
    )

    grader_payload = [
        {
            "name": result.name,
            "grader": result.grader,
            "category": result.category,
            "score": round(result.score, 1),
            "weight": result.weight,
            "passed": result.passed,
            "note": result.note,
            "evidence": result.evidence,
        }
        for result in grader_results
    ]
    deterministic_notes = [result.note for result in grader_results]
    notes = deterministic_notes + list(heuristic_notes or [])[:4] + trust_notes[:4]

    return {
        "benchmark_engine_version": BENCHMARK_ENGINE_VERSION,
        "case_id": clean_case_id,
        "prompt_hash": prompt_hash(prompt),
        "response_hash": prompt_hash(response),
        "accuracy_score": round(float(accuracy_score or 0.0), 1),
        "instruction_score": round(float(instruction_score or 0.0), 1),
        "trust_score": trust_score,
        "deterministic_score": round(float(deterministic_score or 0.0), 1),
        "heuristic_quality_score": round(float(heuristic_value or 0.0), 1),
        "quality_score": round(float(quality_score or 0.0), 1),
        "quality_label": quality_label(float(quality_score or 0.0)),
        "quality_method": f"benchmark engine {BENCHMARK_ENGINE_VERSION} deterministic+heuristic",
        "quality_notes": notes[:10],
        "grader_results": grader_payload,
        "trust_notes": trust_notes,
        "token_estimation_method": token_estimation_method,
    }


def composite_score(
    *,
    accuracy: float,
    speed: float,
    trust: float,
    instruction: float,
    stability: float,
    coverage: float,
) -> float:
    """FZAstro benchmark composite: accuracy first, then speed/trust."""

    return (
        float(accuracy or 0.0) * 0.40
        + float(speed or 0.0) * 0.20
        + float(trust or 0.0) * 0.15
        + float(instruction or 0.0) * 0.10
        + float(stability or 0.0) * 0.10
        + float(coverage or 0.0) * 0.05
    )


def percentile(values: list[float], percentile_value: float) -> float:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return 0.0
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * min(100.0, max(0.0, percentile_value)) / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return clean[int(rank)]
    return clean[low] * (high - rank) + clean[high] * (rank - low)


def run_statistics(values: list[float]) -> dict[str, float]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stddev": 0.0,
            "p50": 0.0,
            "p95": 0.0,
        }
    return {
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "stddev": statistics.pstdev(clean) if len(clean) > 1 else 0.0,
        "p50": percentile(clean, 50),
        "p95": percentile(clean, 95),
    }


def build_result_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Export compact evidence with hashes and grader outcomes for auditability."""

    return {
        "benchmark_engine_version": result.get(
            "benchmark_engine_version", BENCHMARK_ENGINE_VERSION
        ),
        "case_id": result.get("case_id"),
        "model": result.get("model"),
        "persona_key": result.get("persona_key"),
        "preset": result.get("preset"),
        "prompt_hash": result.get("prompt_hash")
        or prompt_hash(result.get("prompt", "")),
        "response_hash": result.get("response_hash")
        or prompt_hash(result.get("response", "")),
        "system_prompt_hash": result.get("system_prompt_hash"),
        "temperature": result.get("temperature"),
        "max_tokens": result.get("max_tokens"),
        "scores": {
            "accuracy": result.get("accuracy_score"),
            "instruction": result.get("instruction_score"),
            "quality": result.get("quality_score"),
            "trust": result.get("trust_score"),
        },
        "grader_results": result.get("grader_results") or [],
        "token_estimation_method": result.get(
            "token_estimation_method", "estimated char/4"
        ),
    }

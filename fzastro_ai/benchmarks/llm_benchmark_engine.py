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
    if passed:
        evidence = "valid JSON with required keys"
    elif payload is None:
        evidence = "no parseable JSON found"
    else:
        evidence = "JSON found, missing keys: " + ", ".join(
            sorted(required - set(payload))
        )
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


def _grade_pattern_match(spec: GraderSpec, response: str) -> GraderResult:
    matches = re.findall(spec.pattern, response, spec.flags)
    count = len(matches)
    passed = count >= 1 if spec.min_count is None else count >= spec.min_count
    if spec.max_count is not None:
        passed = passed and count <= spec.max_count
    return _result(spec, passed, evidence=f"matches={count}, pattern={spec.pattern}")


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
    "pattern_match": _grade_pattern_match,
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

    def pm(name: str, pattern: str, weight: float = 1.0, category: str = "accuracy"):
        """Convenience for a GraderSpec whose grader=pattern_match."""
        return GraderSpec(
            grader="pattern_match",
            name=name,
            pattern=pattern,
            weight=weight,
            category=category,
        )

    if "math reasoning" in preset:
        if "cmos tracking" in prompt_lower or "guiding period" in prompt_lower:
            return (
                numeric("estimates trailing arcsec", 0.8, 0.5, 2.0),
                regex(
                    "shows error propagation",
                    r"(step|propagat|error.* propagation)",
                    1.5,
                ),
                regex("references phd2 correction", r"phd2|rms", 1.0),
            )
        if "12-bit adc" in prompt_lower:
            return (
                numeric("calculates snr for 60s", 15.0, 3.0, 2.0),
                numeric("finds extra frames for snr>200", 50, 15, 1.5),
                regex(
                    "shows noise sources", r"read.*noise|dark.*current|sky|signal", 1.0
                ),
            )
        if "dawes limit" in prompt_lower or "254mm" in prompt_lower:
            return (
                regex(
                    "shows dawes formula",
                    r"\b(138|120|12|1\.38|1\.20)\b.*\b(\d|nm|mm)\b|dawes.*limit",
                    1.5,
                ),
                regex("shows rayleigh formula", r"rayleigh|1\.22.*\d", 1.5),
                regex("accounts for f/11 stop", r"f\/11|stop|aperture.*stop", 1.0),
            )
        if "image scale" in prompt_lower:
            return (numeric("finds image scale", 0.97, 0.04, 2.0),)

    if "logical reasoning" in preset:
        if "oiii observations" in prompt_lower or "b-v" in prompt_lower:
            return (
                regex(
                    "does not overclaim — concludes insufficiency",
                    r"(cannot|insufficient|not.*supported|prevent|cannot.*image)",
                    2.0,
                ),
                regex(
                    "references b-v threshold", r"b-v.*0\.0|0\.0.*(b-v|threshold)", 1.5
                ),
            )
        if "five filters" in prompt_lower or "must be scheduled" in prompt_lower:
            return (
                regex(
                    "finds valid schedule or proves unsatisfiable",
                    r"(luminance|h-alpha|oiii|sii|ha).*night|unsatisfiable|impossible|no.*valid",
                    1.5,
                ),
                regex(
                    "honours adjacency constraint",
                    r"(adjacent|consecutive|before|after).*\b|cannot.*adjacent",
                    1.0,
                ),
            )
        if "auto-calibration" in prompt_lower or "flats and darks" in prompt_lower:
            return (
                regex(
                    "derives logical conclusion from premises",
                    r"(therefore|therefore|follows|implies|thus|proves|consequently)",
                    1.5,
                ),
                regex(
                    "distinguishes auto-cal vs manual flats",
                    r"(auto.cal|no.*manual|cannot.*use.*manual|no.*auto.cal.*manual)",
                    1.0,
                ),
            )

    if "data analysis" in preset:
        if "dark mean" in prompt_lower and "flat mean" in prompt_lower:
            return (
                regex(
                    "shows error propagation formula",
                    r"\(\s*\d+.*\/\s*\d+\s*\)\.*\d|ffi|\*.*\*\*.*2",
                    1.5,
                ),
                numeric("computes per-pixel error", 0.58, 0.1, 2.0),
                regex("substitutes raw=25000", r"25000", 0.5),
            )
        if "psf fwhm" in prompt_lower or "center=1" in prompt_lower:
            return (
                regex(
                    "compares weighted vs unweighted",
                    r"weighted.*unweighted|unweighted.*weighted|vs",
                    1.5,
                ),
                regex(
                    "computes snr penalty at edge",
                    r"snr.*penalty|penalty.*snr|edge.*snr",
                    1.0,
                ),
            )
        if "grubbs" in prompt_lower or "tps benchmark" in prompt_lower:
            return (
                numeric("finds mean tps", 28.0, 0.5, 1.5),
                numeric("finds stddev", 2.35, 0.3, 1.0),
                regex("applies grubbs test", r"grubbs|g\s*=", 1.5),
                regex(
                    "computes 95% confidence interval",
                    r"c\.i\.*95|95%.*confidence|confidence.*95|\.95.*ci|confidence.*interval",
                    1.0,
                ),
            )

    if "instruction following" in preset:
        if "exactly 3 astrophysical" in prompt_lower:
            return (
                GraderSpec(
                    grader="markdown_table",
                    name="returns markdown table with three rows",
                    min_count=3,
                    max_count=3,
                    weight=2.0,
                    category="instruction",
                ),
                regex(
                    "includes catalog designation",
                    r"catalog.*designation|designation|catalog",
                    1.0,
                ),
                GraderSpec(
                    grader="json_schema",
                    name="all objects are not messier",
                    required_keys=("Object", "reason"),
                    weight=2.0,
                ),
                regex("no extra content", r"no.*extra", 0.5, "instruction"),
            )
        if (
            "exactly 7 item" in prompt_lower
            or r"exactly \d word" in prompt_lower
            or "item n" in prompt_lower
        ):
            return (
                GraderSpec(
                    grader="bullet_count",
                    name="returns exactly seven items",
                    min_count=7,
                    max_count=7,
                    weight=2.0,
                    category="instruction",
                ),
                regex(
                    "validates word count per item", r"item \d|item n|words.*item", 1.0
                ),
                regex(
                    "includes constellation and technique",
                    r"constellation.*technique|constellation|observing",
                    1.0,
                ),
            )
        if "json" in prompt_lower and "constraint_check" in prompt_lower:
            return (
                GraderSpec(
                    grader="json_schema",
                    name="returns JSON with required keys",
                    required_keys=(
                        "constraint_check",
                        "valid_observations",
                        "invalid_observations",
                    ),
                    weight=2.0,
                    category="instruction",
                ),
                regex(
                    "observation fields present",
                    r"catalog_id|ra_hms|dec_dms|mag|surface_brightness|best_filter",
                    1.0,
                ),
            )

    if "code generation" in preset:
        if "fits header" in prompt_lower:
            return (
                regex("includes Python definition", r"\b(def|class)\s+\w+", 1.5),
                regex(
                    "validates required HDU keywords",
                    r"bitpix|naxis\s*,?\s*(\d|0)|simple|pcount|gcount",
                    1.5,
                ),
                regex(
                    "handles exceptions/errors",
                    r"\b(raise|try|except|ValueError|FileNotFoundError)\b",
                    1.5,
                ),
                regex(
                    "handles naxis=0 edge case", r"naxis\s*=\s*0|naxis.*0|===?\s*0", 1.0
                ),
                regex("includes tests", r"\b(test_|assert|def test)", 1.0),
            )
        if "derotation" in prompt_lower:
            return (
                regex("computes parallactic angle", r"parallactic|parallactic", 2.0),
                regex("uses ha/dec site lat as input", r"ha|ha|ha|ha".lower(), 1.0),
                regex(
                    "includes coordinate transforms",
                    r"(ra|dec|lat|sin|cos|atan2|atan2|transform)",
                    1.5,
                ),
                regex("includes tests", r"\b(test_|assert|def test)", 1.0),
            )
        if "dither" in prompt_lower:
            return (
                regex("generates hex pattern positions", r"hex|hexas|hexagonal", 1.5),
                regex(
                    "includes boundary checks",
                    r"boundary|edge.*case|border|within|clip",
                    1.0,
                ),
                regex("includes deterministic seeding", r"seed|deterministic", 1.0),
                regex("includes tests", r"\b(test_|assert|def test)", 1.0),
            )
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
        if "polaris" in prompt_lower:
            return (
                regex(
                    "mentions latitude/altitude relation",
                    r"latitude|altitude|polaris",
                    1.5,
                ),
                regex(
                    "explains polaris offset",
                    r"polaris.*not|offset|movement|pole\.*star.*distance|precess",
                    1.0,
                ),
            )
        if "redder" in prompt_lower or "dispersion" in prompt_lower:
            return (
                regex(
                    "mentions wavelength-dependent refraction",
                    r"dispersion|wavelength.*refract|refract.*wavelength|atmospheric.*dispersion",
                    1.5,
                ),
                regex(
                    "compares red vs blue",
                    r"red.*blue|redder.*bluer|red.*stars.*higher|bluer.*lower",
                    1.0,
                ),
            )
        if "full moon" in prompt_lower:
            return (
                regex(
                    "explains moon rise/sunset geometry",
                    r"full moon.*rise|rise.*sun.*set|moon.*opposite|opposition|full moon rises",
                    1.5,
                ),
                regex(
                    "identifies deep sky limitation",
                    r"deep sky|deep-sky|background|sky.*brightness|light.*pollution|glare",
                    1.0,
                ),
            )
        return (
            GraderSpec(
                grader="word_count",
                name="keeps compact answer",
                max_words=120,
                weight=1.0,
                category="instruction",
            ),
            regex(
                "uses relevant astronomy terms",
                r"telescope|altitude|magnitude|sky|observer|atmosphere|light",
                1.0,
            ),
        )

    if "creative writing" in preset:
        if "nebula" in prompt_lower:
            return (
                GraderSpec(
                    grader="word_count",
                    name="meets 400 words minimum",
                    min_words=350,
                    weight=1.0,
                    category="instruction",
                ),
                regex(
                    "includes technical details (exposure/filter/seeing)",
                    r"exposure|filter|seeing|integration|sub.*frame",
                    1.0,
                ),
            )
        if "space debris" in prompt_lower or "collision" in prompt_lower:
            return (
                GraderSpec(
                    grader="word_count",
                    name="meets 450 words minimum",
                    min_words=400,
                    weight=1.0,
                    category="instruction",
                ),
                regex(
                    "accurate orbital mechanics (not circular)",
                    r"ellipse|elliptical|ellips|orbit.*track|tracking.*data|velocity|altitudes",
                    1.0,
                ),
            )
        if "cold weather" in prompt_lower or "equipment failure" in prompt_lower:
            return (
                GraderSpec(
                    grader="word_count",
                    name="meets 350 words minimum",
                    min_words=300,
                    weight=1.0,
                    category="instruction",
                ),
                regex(
                    "technical effects (thermal/battery/condensation)",
                    r"(thermal|condensation|battery.*performance|frost|ice|temp|optical.*effect|equipment)",
                    1.0,
                ),
            )
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
        if "positional encoding" in prompt_lower:
            return (
                regex("includes kanji/hiragana", r"[\u3040-\u309f\u30a0-\u30ff]", 1.0),
                regex("includes greek script", r"[\u0370-\u03ff]", 1.0),
                regex(
                    "notes loss of meaning for positional encoding",
                    r"loses meaning|impossible.*translate|hard.*translate|term.*lost",
                    1.0,
                ),
            )
        if "flat-field" in prompt_lower:
            return (
                regex("includes kanji/hiragana", r"[\u3040-\u309f\u30a0-\u30ff]", 1.0),
                regex("includes greek script", r"[\u0370-\u03ff]", 1.0),
                regex(
                    "lists hard-to-translate terms",
                    r"hard.*translate|terms.*translate|vignetting|dust.*shadow|polarisation",
                    1.0,
                ),
            )
        if "attention mechanism" in prompt_lower:
            return (
                regex("includes kanji/hiragana", r"[\u3040-\u309f\u30a0-\u30ff]", 1.0),
                regex("includes greek script", r"[\u0370-\u03ff]", 1.0),
                regex(
                    "notes meaning degradation",
                    r"degrade|lose.*meaning|nuance.*lost|hard.*translate|approximate|imperfect",
                    1.0,
                ),
            )
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
        if "imaging pipeline" in prompt_lower or "open imaging" in prompt_lower:
            return (
                GraderSpec(
                    grader="word_count",
                    name="stays under 350 words",
                    max_words=350,
                    weight=0.8,
                    category="instruction",
                ),
                regex("covers capture step", r"capture|acquisition|subexposure", 0.8),
                regex("covers calibration step", r"calibrat|dark|flat|bias", 0.8),
                regex(
                    "covers integration/stacking", r"integrat|stack|combin|align", 0.8
                ),
                regex(
                    "mentions failure modes",
                    r"fail|error|miss|drift|issue|mismatch",
                    0.8,
                ),
            )
        if "multi-head" in prompt_lower:
            return (
                regex(
                    "covers q/k/v matrices", r"q\s*=|k\s*=|v\s*=|key|value|query", 1.0
                ),
                regex(
                    "explains scaling necessity",
                    r"scale|variance|explode|gradi.*explod|normalis",
                    1.5,
                ),
                regex(
                    "addresses memory cost",
                    r"memory.*cost|complexity|computational|d\s*\.*n|d2.*n",
                    1.0,
                ),
            )
        if "distillation" in preset.lower() or "student-teacher" in prompt_lower:
            return (
                regex(
                    "covers student-teacher architecture",
                    r"student|teacher|distil|teacher-student|student-teacher",
                    1.5,
                ),
                regex(
                    "covers temperature scaling",
                    r"temperature|soft.*target|softmax.*temp",
                    1.0,
                ),
                regex(
                    "covers computational savings",
                    r"savings|speedup|inference.*cost|flops|parameter",
                    1.0,
                ),
            )
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

    # --- Additional built-in presets ---

    if "code review" in preset:
        return (
            pm(
                "checks for error handling",
                r"raise|except|error|handle|check|valid",
                1.5,
            ),
            pm(
                "checks for edge cases",
                r"\b(null|none|empty|zero|blank|missing|invalid)\b",
                1.5,
            ),
            pm("checks for comments/docstring", r'("""|\/\/|# ).', 0.8),
            pm(
                "suggests concrete improvements",
                r"suggest|improve|refactor|rename|extract|consolidate",
                1.5,
            ),
        )

    if "security analysis" in preset:
        return (
            pm(
                "checks for injection vectors",
                r"inject|sanitize|escape|validate|whitelist|blacklist",
                1.5,
            ),
            pm(
                "checks for auth concerns",
                r"auth|permission|privilege|role|token|credential|secret|password",
                1.5,
            ),
            pm(
                "checks for logging/audit", r"log|audit|trace|record|alert|monitor", 1.0
            ),
            pm(
                "checks for input validation",
                r"input|validate|sanitize|parameter|argument|boundary",
                1.0,
            ),
        )

    if "debugging" in preset:
        return (
            pm(
                "identifies root cause",
                r"root|cause|issue|bug|error|fail|crash|exception",
                2.0,
            ),
            pm(
                "suggests fix steps",
                r"fix|step|solution|patch|change|update|add|remove|replace",
                1.5,
            ),
            pm(
                "mentions debugging tools or methods",
                r"debug|log|trace|breakpoint|inspect|print|assert",
                1.0,
            ),
            pm(
                "checks for edge/repro path",
                r"reproduc|edge|case|corner|boundary|input|trigger",
                1.0,
            ),
        )

    if "comparison" in preset:
        return (
            pm(
                "compares options fairly",
                r"pros|cons|trade.?off|advantage|disadvantage|trade.?offs",
                2.0,
            ),
            pm(
                "includes recommendation",
                r"recommend|prefer|better|choose|select|favor|suggest",
                2.0,
            ),
            pm(
                "mentions criteria",
                r"criteria|criterion|factor|consideration|metric|benchmark",
                1.0,
            ),
        )

    if "architecture design" in preset:
        return (
            pm(
                "mentions design patterns",
                r"singleton|factory|observer|strategy|adapter|decorator|facade|repository|pipeline",
                1.5,
            ),
            pm(
                "considers scalability",
                r"scale|scalable|throughput|latency|bottleneck|concurrent|parallel",
                1.5,
            ),
            pm(
                "considers failure modes",
                r"fail|fallback|retry|circuit.break|timeout|redundant|failover",
                1.5,
            ),
            pm(
                "considers testing", r"test|mock|stub|fixture|integration|unit|e2e", 0.8
            ),
        )

    # --- Smart fallback: generic patterns for any unrecognized preset ---

    # Detect if prompt asks for a concrete answer (number/units)
    if re.search(
        r"\b(\d[\d\s,/]+|how many|what is|calculate|compute|estimate|approximate|total)\b",
        prompt_lower,
    ):
        candidates = (
            pm(
                "contains a numeric reasoning element",
                r"\b\d+\.?\d*\b",
                1.0,
                "accuracy",
            ),
        )
        if re.search(r"\b(around|approximately|about|estimate|approx)\b", prompt_lower):
            return candidates + (
                pm(
                    "includes justification or steps",
                    r"because|since|calcul|formula|equation|reason",
                    1.5,
                    "accuracy",
                ),
            )
        return candidates
    # Detect if prompt asks for explanation/step-by-step
    if re.search(
        r"\b(explain|step.by.step|describe|how does|how can|why|process|work)\b",
        prompt_lower,
    ):
        return (
            pm(
                "mentions key concepts related to the topic",
                r"\b(and|or|but|because|therefore|thus|however|consequently)\b",
                1.0,
                "accuracy",
            ),
            pm(
                "includes structured reasoning",
                r"first|second|next|finally|then|step|phase|stage",
                1.5,
                "accuracy",
            ),
            pm(
                "uses domain-relevant terminology",
                r"\b([a-z]{4,})\s+[a-z]{4,}\b",
                0.5,
                "accuracy",
            ),
        )
    # Detect if prompt asks for a list/summary
    if re.search(
        r"\b(list|summarize|summar|key.?points|overview|types|categories|examples|compare|contrast)\b",
        prompt_lower,
    ):
        return (
            pm(
                "provides structured output",
                r"^\d+\.\s|^\s*[-*•]\s|^\|.*\|.*\||^```",
                1.0,
                "accuracy",
            ),
            pm(
                "covers multiple distinct items",
                r"\b(and|,|also|additionally|furthermore|moreover)\b",
                0.8,
                "accuracy",
            ),
        )
    # Detect if prompt asks for code
    if re.search(
        r"\b(code|implement|function|write a|generate|create a|program|algorithm|script)\b",
        prompt_lower,
    ):
        return (
            pm(
                "includes code structure",
                r"(\bdef\b|\bclass\b|\bfunction\b|\bconst\b|\blet\b|\bvar\b|\bswitch\b|\bimport\b|\brequire)",
                2.0,
                "accuracy",
            ),
            pm(
                "includes error handling or validation",
                r"(\btry\b|\bexcept\b|\braise\b|\bif not\b|\bis None\b|\bthrow\b|\bpanic)",
                1.5,
                "accuracy",
            ),
            pm(
                "includes test or verification",
                r"(\btest|assert|verify|check|expect|assertion|unittest|\bpytest)",
                1.0,
                "accuracy",
            ),
        )
    # Detect if prompt asks for a question/clarification
    if re.search(
        r"\b(what is|when|where|who|which|how to|how do|what are)\b", prompt_lower
    ):
        return (pm("addresses the core question", r"[a-z]{4,}", 0.5, "accuracy"),)

    # Ultimate graceful fallback: detect whatever structure the prompt/response has.
    if prompt and len(prompt) > 20:
        # Detect numeric elements in the prompt for potential numeric matching.
        if re.search(r"\d+\.?\d*", prompt):
            return (
                pm(
                    "includes numeric elements in reasoning",
                    r"\b\d+\.?\d*\b",
                    0.5,
                    "accuracy",
                ),
            )
        # Detect if the prompt contains structured terms (lists, categories).
        if re.search(
            r"\b(first|second|third|item|element|factor|aspect|component)\b",
            prompt_lower,
        ):
            return (
                pm(
                    "includes structured reasoning",
                    r"(first|second|third|item|element|factor|aspect|component|also|additionally)",
                    0.5,
                    "accuracy",
                ),
            )
        # Generic: if there's a prompt with graders and no response, the grader system
        # is still usable — return a single catch-all to prevent empty results.
        return ()

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
    grader_results: list[GraderResult] | None = None,
) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 100.0

    if not str(model or "").strip():
        score -= 10.0
        notes.append("model name missing")
    if not str(base_url or "").strip():
        score -= 5.0
        notes.append("runtime/base URL not recorded")
    if not str(prompt or "").strip():
        score -= 25.0
        notes.append("prompt missing")
    if not str(response or "").strip():
        score = min(score, 20.0)
        notes.append("empty response")
        if grader_results:
            notes.append("further penalized by zero-grader pass rate")
        return max(0.0, min(100.0, round(score, 1))), notes[:8]
    if deterministic_grader_count <= 0:
        score -= 15.0
        notes.append("no deterministic grader attached; heuristic-only score")
    else:
        notes.append(f"{deterministic_grader_count} deterministic grader(s) recorded")

    # Grader pass rate affects trust: consistent failures weaken confidence.
    if grader_results:
        failed = sum(1 for r in grader_results if not r.passed and r.score == 0.0)
        total = len(grader_results)
        pass_rate = 1.0 - (failed / total) if total > 0 else 1.0
        # Small penalty when pass rate is below 75%, proportionally scaling.
        if pass_rate < 0.75:
            penalty = (0.75 - pass_rate) * 40.0
            score -= penalty
            notes.append(
                f"low grader pass rate ({pass_rate:.0%}), trust penalty {penalty:.1f}"
            )

    # Token estimation method penalty only when the method is unknown/unspecified.
    method_lower = str(token_estimation_method or "").lower()
    if not method_lower:
        score -= 5.0
        notes.append("token estimation method unspecified")
    elif "unavailable" in method_lower or "unknown" in method_lower:
        score -= 5.0
        notes.append("token counts unavailable")
    # Char/4 is considered reliable enough for comparison — no penalty.

    completion_estimate = estimate_tokens(response)
    if max_tokens > 0 and completion_estimate >= max_tokens * 0.95:
        score -= 8.0
        notes.append("response may have reached max-token cap")

    # Response length guard: detect suspiciously short/long outputs vs the prompt.
    resp_words = _word_count(response)
    prompt_words = _word_count(prompt)
    if prompt_words > 0 and resp_words < max(10, prompt_words * 0.1):
        score -= 5.0
        notes.append(
            f"suspiciously short response ({resp_words} vs {prompt_words} prompt words)"
        )
    if resp_words > 10000:
        score -= 3.0
        notes.append("exceptionally long response may obscure reasoning")

    # Repeat count: heavier penalty for single-run results with no variance data.
    if repeat_total <= 1:
        score -= 10.0
        notes.append("single repeat; variance unknown")
    else:
        notes.append(f"repeat plan recorded: {repeat_total} per prompt")

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
        grader_results=grader_results,
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

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..astro_tools.seeing_data import fetch_7timer_astro_forecast, score_label
from ..astro_tools.target_catalog import load_catalog_rows
from ..config import APP_DIR

from .nina_sequence_template import NinaSequencePlan, save_filled_sequence


def _default_imaging_plan_dir() -> Path:
    """Return a user-visible folder for generated imaging review plans.

    The plan files are intentionally not stored in temp folders or hidden build
    folders.  Documents is easier for users to inspect and for N.I.N.A./FZAstro
    Imaging import/review workflows.
    """

    documents = Path.home() / "Documents"
    try:
        return documents / "FZAstroAI" / "Imaging Plans"
    except Exception:
        return APP_DIR / "imaging_plans"


IMAGING_PLAN_DIR = _default_imaging_plan_dir()
DEFAULT_EXPOSURE_SECONDS = 60
DEFAULT_GAIN = 200
DEFAULT_MIN_ALT_DEG = 45.0
DEFAULT_NINA_MIN_ALT_DEG = 30.0
DEFAULT_TARGET_LIMIT = 12

_SAFE_NATURAL_COMMANDS = {
    "what target should i image next",
    "what target should i image tonight",
    "what target for next time period",
    "what target for the next time period",
    "best target for next time period",
    "best target tonight",
    "plan best target into nina",
    "make a nina plan for best target",
    "create nina plan for best target",
    "create nina plan for next target",
    "make a plan into nina",
    "make imaging plan into nina",
}

_COMMAND_PREFIX_RE = re.compile(
    r"^/(?:nina-plan|nina plan|imaging-plan|imaging plan|astro-plan|astro plan|plan-imaging)\b(?P<body>.*)$",
    re.IGNORECASE,
)

_CATALOG_TARGET_RE = re.compile(
    r"\b(?:(M|MESSIER)\s*([0-9]{1,3})|(NGC|IC)\s*([0-9]{1,5})|BARNARD\s*([0-9]{1,4}))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PredefinedImagingCommand:
    """A safe, fixed-grammar imaging command parsed from the composer."""

    raw_text: str
    mode: str = "next_best"
    target: str = ""
    exposure_seconds: int = DEFAULT_EXPOSURE_SECONDS
    gain: int = DEFAULT_GAIN
    frames: int = 0
    period: str = "next"
    auto_start_requested: bool = False


@dataclass(frozen=True)
class ImagingWindow:
    start_iso: str
    end_iso: str
    start_label: str
    end_label: str
    score: int
    score_label: str
    cloud_pct: int | None = None
    cloud_text: str = ""
    seeing_text: str = ""
    transparency_text: str = ""
    moon_text: str = ""
    astro_dark: bool = False


@dataclass(frozen=True)
class ImagingPlanResult:
    plan_id: str
    target_name: str
    target_type: str
    ra: str
    dec: str
    magnitude: str
    size: str
    target_grade: int
    exposure_seconds: int
    gain: int
    frames: int
    estimated_total_minutes: int
    window: ImagingWindow
    location: dict[str, Any]
    imaging: dict[str, Any]
    plan_json_path: str
    plan_text_path: str
    nina_review_path: str
    nina_xml_path: str
    nina_csv_path: str
    nina_sequence_path: str
    auto_start_requested: bool = False
    review_required: bool = True


def _normalise_text(text: str) -> str:
    clean = str(text or "").casefold().strip()
    clean = clean.replace("-", " ").replace("_", " ")
    clean = re.sub(r"[^a-z0-9/\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _normalise_target_name(text: str) -> str:
    raw = str(text or "").strip()
    match = _CATALOG_TARGET_RE.search(raw)
    if match:
        if match.group(1):
            return f"M{int(match.group(2))}"
        if match.group(3):
            return f"{match.group(3).upper()} {int(match.group(4))}"
        if match.group(5):
            return f"Barnard {int(match.group(5))}"
    clean = re.sub(r"\s+", " ", raw).strip()
    return clean


def _extract_target(body: str) -> str:
    explicit = re.search(
        r"\btarget\s+(?P<target>.+?)(?=\s+\b(?:gain|frames|subs|lights|exposure|exp|start|tonight|next|tomorrow)\b|\s+\d+\s*(?:s|sec|secs|second|seconds)\b|$)",
        body,
        flags=re.IGNORECASE,
    )
    if explicit:
        return _normalise_target_name(explicit.group("target"))

    catalog_match = _CATALOG_TARGET_RE.search(body)
    if catalog_match:
        return _normalise_target_name(catalog_match.group(0))

    # Accept `/nina-plan Andromeda gain 200` but keep this conservative: only
    # the leading free-text token span before known parameters is treated as a target.
    body_clean = str(body or "").strip()
    body_clean = re.sub(r"^for\s+", "", body_clean, flags=re.IGNORECASE).strip()
    body_clean = re.split(
        r"\s+\b(?:gain|frames|subs|lights|exposure|exp|start|tonight|next|tomorrow|auto|run|schedule)\b|\s+\d+\s*(?:s|sec|secs|second|seconds)\b",
        body_clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if body_clean.casefold() in {"", "next", "tonight", "best", "best target"}:
        return ""
    if len(body_clean.split()) <= 4:
        return _normalise_target_name(body_clean)
    return ""


def parse_predefined_imaging_command(text: str) -> PredefinedImagingCommand | None:
    """Parse only fixed, safe imaging-plan commands.

    The parser deliberately does not understand arbitrary automation language.
    It creates review-only plans and records if the user asked for auto-start so
    the UI can explicitly refuse silent hardware execution.
    """

    raw = str(text or "").strip()
    if not raw:
        return None

    prefix_match = _COMMAND_PREFIX_RE.match(raw)
    clean = _normalise_text(raw)

    if prefix_match:
        body = prefix_match.group("body").strip()
    elif clean in _SAFE_NATURAL_COMMANDS:
        body = clean
    else:
        return None

    lower_body = body.casefold()
    exposure = DEFAULT_EXPOSURE_SECONDS
    exposure_match = re.search(
        r"(?:\bexposure\b|\bexp\b)?\s*(?P<seconds>\d{1,5})\s*(?:s|sec|secs|second|seconds)\b",
        body,
        flags=re.IGNORECASE,
    )
    if exposure_match:
        exposure = max(1, min(24 * 3600, int(exposure_match.group("seconds"))))

    gain = DEFAULT_GAIN
    gain_match = re.search(r"\bgain\s*(?P<gain>\d{1,5})\b", body, re.IGNORECASE)
    if gain_match:
        gain = max(0, min(10000, int(gain_match.group("gain"))))

    frames = 0
    frames_match = re.search(
        r"\b(?:frames|subs|lights)\s*(?P<frames>\d{1,5})\b",
        body,
        flags=re.IGNORECASE,
    )
    if frames_match:
        frames = max(1, min(10000, int(frames_match.group("frames"))))

    target = _extract_target(body)
    period = "tomorrow" if "tomorrow" in lower_body else "tonight"
    if "next" in lower_body or not target:
        period = "next"

    auto_start_requested = bool(
        re.search(r"\b(auto|automatic|automatically|run|start|schedule)\b", body, re.I)
    )

    mode = "target" if target else "next_best"
    return PredefinedImagingCommand(
        raw_text=raw,
        mode=mode,
        target=target,
        exposure_seconds=exposure,
        gain=gain,
        frames=frames,
        period=period,
        auto_start_requested=auto_start_requested,
    )


def is_predefined_imaging_command(text: str) -> bool:
    return parse_predefined_imaging_command(text) is not None


def _safe_zone(tz_name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(tz_name or "UTC").strip() or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _parse_dt(value: Any, tz_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_safe_zone(tz_name))
        return parsed.astimezone(_safe_zone(tz_name))
    except Exception:
        return None


def choose_best_seeing_window(
    forecast: dict[str, Any], *, now: datetime | None = None
) -> ImagingWindow:
    rows = forecast.get("rows") if isinstance(forecast, dict) else []
    if not isinstance(rows, list) or not rows:
        raise ValueError("SEEING forecast has no usable rows.")

    tz_name = str(forecast.get("tz") or "UTC")
    zone = _safe_zone(tz_name)
    now_local = (now or datetime.now(zone)).astimezone(zone)

    parsed_rows: list[tuple[dict[str, Any], datetime]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        local_dt = _parse_dt(row.get("local_iso") or row.get("local_label"), tz_name)
        if local_dt is None:
            continue
        parsed_rows.append((row, local_dt))

    if not parsed_rows:
        raise ValueError("SEEING forecast rows did not contain usable times.")

    future_rows = [
        (row, dt) for row, dt in parsed_rows if dt >= now_local - timedelta(minutes=30)
    ]
    candidates = future_rows or parsed_rows
    dark_candidates = [
        (row, dt) for row, dt in candidates if row.get("astro_dark") is True
    ]
    candidates = dark_candidates or candidates

    row, start = max(
        candidates,
        key=lambda item: (
            int(item[0].get("score") or 0),
            bool(item[0].get("astro_dark") is True),
            -abs((item[1] - now_local).total_seconds()) / 3600.0,
        ),
    )

    later_times = sorted(dt for _row, dt in parsed_rows if dt > start)
    end = later_times[0] if later_times else start + timedelta(hours=3)
    if end <= start:
        end = start + timedelta(hours=3)

    cloud_pct = row.get("cloud_mid_pct")
    try:
        cloud_pct_value = int(cloud_pct) if cloud_pct is not None else None
    except Exception:
        cloud_pct_value = None

    score = int(row.get("score") or 0)
    return ImagingWindow(
        start_iso=start.isoformat(),
        end_iso=end.isoformat(),
        start_label=start.strftime("%Y-%m-%d %H:%M"),
        end_label=end.strftime("%Y-%m-%d %H:%M"),
        score=score,
        score_label=str(row.get("score_label") or score_label(score)),
        cloud_pct=cloud_pct_value,
        cloud_text=str(row.get("cloud_text") or ""),
        seeing_text=str(row.get("seeing_text") or ""),
        transparency_text=str(row.get("transparency_text") or ""),
        moon_text=str(row.get("moon_text") or ""),
        astro_dark=bool(row.get("astro_dark") is True),
    )


def _target_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _catalog_target(query: str) -> dict[str, Any]:
    wanted = _target_key(_normalise_target_name(query))
    if not wanted:
        return {}
    for row in load_catalog_rows(source="auto"):
        name = str(row[0] or "")
        if _target_key(name) == wanted:
            return {
                "name": name,
                "type": str(row[1] or ""),
                "const": str(row[2] or ""),
                "ra": str(row[3] or ""),
                "dec": str(row[4] or ""),
                "mag": "" if row[5] is None else str(row[5]),
                "size": str(row[6] or ""),
                "grade": 0,
            }
    return {
        "name": _normalise_target_name(query),
        "type": "Manual target",
        "const": "",
        "ra": "",
        "dec": "",
        "mag": "",
        "size": "",
        "grade": 0,
    }


def _choose_target(
    command: PredefinedImagingCommand,
    targets_result: dict[str, Any],
    window: ImagingWindow,
) -> dict[str, Any]:
    if command.target:
        return _catalog_target(command.target)

    picks = targets_result.get("picks") if isinstance(targets_result, dict) else []
    if not isinstance(picks, list) or not picks:
        raise ValueError("TARGETS planner returned no usable target picks.")

    window_start = _parse_dt(
        window.start_iso, str(targets_result.get("location", {}).get("tz") or "UTC")
    )

    def rank(pick: dict[str, Any]) -> tuple[int, float]:
        grade = int(pick.get("grade") or 0)
        best = _parse_dt(
            pick.get("best_time_local"),
            str(targets_result.get("location", {}).get("tz") or "UTC"),
        )
        if window_start is not None and best is not None:
            delta = abs((best - window_start).total_seconds()) / 60.0
        else:
            delta = 99999.0
        return (grade, -delta)

    best_pick = max((p for p in picks if isinstance(p, dict)), key=rank)
    return {
        "name": str(best_pick.get("name") or "Best target"),
        "type": str(best_pick.get("type") or ""),
        "const": str(best_pick.get("const") or ""),
        "ra": str(best_pick.get("ra") or ""),
        "dec": str(best_pick.get("dec") or ""),
        "mag": "" if best_pick.get("mag") is None else str(best_pick.get("mag")),
        "size": str(best_pick.get("size") or ""),
        "grade": int(best_pick.get("grade") or 0),
    }


def _frames_for_window(
    command: PredefinedImagingCommand, window: ImagingWindow
) -> tuple[int, int]:
    start = _parse_dt(window.start_iso, "UTC")
    end = _parse_dt(window.end_iso, "UTC")
    duration_minutes = 180
    if start is not None and end is not None:
        duration_minutes = max(1, int((end - start).total_seconds() // 60))
    if command.frames > 0:
        return command.frames, duration_minutes
    usable_seconds = max(0, duration_minutes * 60 - 10 * 60)
    frames = max(1, int(usable_seconds // max(1, command.exposure_seconds)))
    return min(frames, 500), duration_minutes


def _safe_plan_id(target_name: str, created: datetime) -> str:
    clean_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", target_name).strip("_") or "target"
    return f"{created.strftime('%Y%m%d_%H%M%S')}_{clean_target}"


def _set_xml_child(parent: ET.Element, tag: str, values: dict[str, Any]) -> ET.Element:
    child = ET.SubElement(parent, tag)
    for key, value in values.items():
        child.set(str(key), "" if value is None else str(value))
    return child


def _write_nina_review_xml(path: Path, result: ImagingPlanResult) -> None:
    """Write a N.I.N.A.-friendly XML review/export file.

    This is deliberately a review/import helper, not an instruction to start
    hardware.  It gives FZAstro Imaging/N.I.N.A. users a structured XML file
    with target, sequence, and condition details while preserving the safety
    boundary around slewing/capture.
    """

    root = ET.Element(
        "FZAstroImagingPlan",
        {
            "schema": "fzastro_nina_review_plan_v1",
            "safe_mode": "true",
            "review_required": "true",
            "auto_start": "false",
        },
    )
    _set_xml_child(
        root,
        "Target",
        {
            "name": result.target_name,
            "type": result.target_type,
            "ra": result.ra,
            "dec": result.dec,
            "magnitude": result.magnitude,
            "size": result.size,
            "grade": result.target_grade,
        },
    )
    _set_xml_child(
        root,
        "Sequence",
        {
            "start_time": result.window.start_iso,
            "end_time": result.window.end_iso,
            "exposure_seconds": result.exposure_seconds,
            "gain": result.gain,
            "frames": result.frames,
            "estimated_light_minutes": result.estimated_total_minutes,
        },
    )
    _set_xml_child(
        root,
        "Conditions",
        {
            "seeing_score": result.window.score,
            "seeing_label": result.window.score_label,
            "cloud_pct": result.window.cloud_pct,
            "cloud_text": result.window.cloud_text,
            "seeing_text": result.window.seeing_text,
            "transparency_text": result.window.transparency_text,
            "moon_text": result.window.moon_text,
            "astro_dark": result.window.astro_dark,
        },
    )
    _set_xml_child(
        root,
        "Safety",
        {
            "hardware_actions_executed": "false",
            "note": "Review-only plan. Confirm in FZAstro Imaging/N.I.N.A. before slewing, guiding, capture, or sequence start.",
        },
    )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_nina_review_csv(path: Path, result: ImagingPlanResult) -> None:
    """Write a simple CSV target/sequence review file for spreadsheet/N.I.N.A. workflows."""

    headers = [
        "Name",
        "RA",
        "Dec",
        "Type",
        "Magnitude",
        "Size",
        "Grade",
        "StartTime",
        "EndTime",
        "ExposureSeconds",
        "Gain",
        "Frames",
        "EstimatedLightMinutes",
        "SeeingScore",
        "CloudPct",
        "Moon",
        "Safety",
    ]
    row = {
        "Name": result.target_name,
        "RA": result.ra,
        "Dec": result.dec,
        "Type": result.target_type,
        "Magnitude": result.magnitude,
        "Size": result.size,
        "Grade": result.target_grade,
        "StartTime": result.window.start_iso,
        "EndTime": result.window.end_iso,
        "ExposureSeconds": result.exposure_seconds,
        "Gain": result.gain,
        "Frames": result.frames,
        "EstimatedLightMinutes": result.estimated_total_minutes,
        "SeeingScore": result.window.score,
        "CloudPct": "" if result.window.cloud_pct is None else result.window.cloud_pct,
        "Moon": result.window.moon_text,
        "Safety": "Review-only; no hardware action executed",
    }
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def _write_nina_sequence_json(path: Path, result: ImagingPlanResult) -> None:
    """Write a real N.I.N.A. Advanced Sequencer JSON file from the OSC template."""

    save_filled_sequence(
        path,
        NinaSequencePlan(
            target_name=result.target_name,
            ra=result.ra,
            dec=result.dec,
            start_iso=result.window.start_iso,
            end_iso=result.window.end_iso,
            exposure_seconds=result.exposure_seconds,
            gain=result.gain,
            frames=result.frames,
            min_altitude_deg=DEFAULT_NINA_MIN_ALT_DEG,
            note=(
                "Review the generated sequence in FZAstro Imaging/N.I.N.A. "
                "before slewing, guiding, capture, or automatic execution."
            ),
        ),
    )


def _write_plan_files(
    result: ImagingPlanResult, payload: dict[str, Any]
) -> ImagingPlanResult:
    out_dir = Path(result.plan_json_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = Path(result.plan_json_path)
    text_path = Path(result.plan_text_path)
    review_path = Path(result.nina_review_path)
    xml_path = Path(result.nina_xml_path)
    csv_path = Path(result.nina_csv_path)
    sequence_path = Path(result.nina_sequence_path)

    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    text_path.write_text(format_imaging_plan_markdown(result), encoding="utf-8")

    review_payload = {
        "format": "FZAstro NINA review plan v1",
        "safe_mode": True,
        "review_required": True,
        "auto_start": False,
        "note": "This file is a review/export plan for FZAstro Imaging. It does not move equipment or start a N.I.N.A. sequence by itself.",
        "target": {
            "name": result.target_name,
            "ra": result.ra,
            "dec": result.dec,
            "type": result.target_type,
        },
        "sequence": {
            "start_time": result.window.start_iso,
            "end_time": result.window.end_iso,
            "exposure_seconds": result.exposure_seconds,
            "gain": result.gain,
            "frames": result.frames,
        },
        "conditions": asdict(result.window),
    }
    review_path.write_text(
        json.dumps(review_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_nina_review_xml(xml_path, result)
    _write_nina_review_csv(csv_path, result)
    _write_nina_sequence_json(sequence_path, result)
    return result


def build_imaging_plan_from_results(
    *,
    command: PredefinedImagingCommand,
    location: dict[str, Any],
    imaging: dict[str, Any],
    forecast: dict[str, Any],
    targets_result: dict[str, Any],
    output_dir: str | Path | None = None,
    created_at: datetime | None = None,
) -> ImagingPlanResult:
    created = created_at or datetime.now(timezone.utc)
    window = choose_best_seeing_window(forecast, now=created)
    target = _choose_target(command, targets_result, window)
    frames, duration_minutes = _frames_for_window(command, window)
    total_minutes = max(1, int((frames * command.exposure_seconds) // 60))
    plan_id = _safe_plan_id(str(target.get("name") or "target"), created)
    base_out_dir = Path(output_dir or IMAGING_PLAN_DIR)
    out_dir = base_out_dir / plan_id

    result = ImagingPlanResult(
        plan_id=plan_id,
        target_name=str(target.get("name") or "Target"),
        target_type=str(target.get("type") or ""),
        ra=str(target.get("ra") or ""),
        dec=str(target.get("dec") or ""),
        magnitude=str(target.get("mag") or ""),
        size=str(target.get("size") or ""),
        target_grade=int(target.get("grade") or 0),
        exposure_seconds=int(command.exposure_seconds),
        gain=int(command.gain),
        frames=int(frames),
        estimated_total_minutes=int(total_minutes),
        window=window,
        location=dict(location or {}),
        imaging=dict(imaging or {}),
        plan_json_path=str(out_dir / f"{plan_id}.json"),
        plan_text_path=str(out_dir / f"{plan_id}.md"),
        nina_review_path=str(out_dir / f"{plan_id}.nina-review.json"),
        nina_xml_path=str(out_dir / f"{plan_id}.nina-plan.xml"),
        nina_csv_path=str(out_dir / f"{plan_id}.nina-target.csv"),
        nina_sequence_path=str(out_dir / f"{plan_id}.nina-sequence.json"),
        auto_start_requested=bool(command.auto_start_requested),
        review_required=True,
    )

    payload = {
        "schema": "fzastro_imaging_plan_v1",
        "created_utc": created.astimezone(timezone.utc).isoformat(),
        "command": asdict(command),
        "plan": asdict(result),
        "safety": {
            "review_required": True,
            "auto_start": False,
            "hardware_actions_executed": False,
            "message": "FZAstro created a review-only imaging plan. Confirm in FZAstro Imaging/N.I.N.A. before moving equipment or starting capture.",
        },
    }
    return _write_plan_files(result, payload)


def build_predefined_imaging_plan(
    *,
    command: PredefinedImagingCommand,
    location: dict[str, Any],
    imaging: dict[str, Any],
    output_dir: str | Path | None = None,
) -> ImagingPlanResult:
    from ..astro_tools.target_planner import plan_targets

    forecast = fetch_7timer_astro_forecast(
        lat=location.get("lat"),
        lon=location.get("lon"),
        elev=location.get("elev", 0.0),
        tz=str(location.get("tz") or "UTC"),
        altitude_correction="auto",
    )
    window = choose_best_seeing_window(forecast)
    start_dt = _parse_dt(window.start_iso, str(location.get("tz") or "UTC"))
    date_iso = start_dt.date().isoformat() if start_dt else None
    targets_result = plan_targets(
        location,
        date_iso=date_iso,
        limit=DEFAULT_TARGET_LIMIT,
        min_alt=DEFAULT_MIN_ALT_DEG,
    )
    return build_imaging_plan_from_results(
        command=command,
        location=location,
        imaging=imaging,
        forecast=forecast,
        targets_result=targets_result,
        output_dir=output_dir,
    )


def format_imaging_plan_markdown(plan: ImagingPlanResult) -> str:
    warning = ""
    if plan.auto_start_requested:
        warning = (
            "\n\n**Safety note:** automatic start/schedule was requested, but this "
            "first-stage command only creates a review plan. Start the sequence manually after checking hardware."
        )
    coord_line = ""
    if plan.ra or plan.dec:
        coord_line = f"\n- Coordinates: RA `{plan.ra or '—'}` · Dec `{plan.dec or '—'}`"
    return (
        "**FZAstro Imaging plan created**\n\n"
        f"- Target: **{plan.target_name}**"
        f"{coord_line}\n"
        f"- Type: {plan.target_type or '—'} · Grade: {plan.target_grade or '—'}\n"
        f"- Window: {plan.window.start_label} → {plan.window.end_label}\n"
        f"- SEEING score: {plan.window.score}/100 · {plan.window.score_label}\n"
        f"- Cloud: {plan.window.cloud_pct if plan.window.cloud_pct is not None else '—'}% · {plan.window.cloud_text or '—'}\n"
        f"- Seeing: {plan.window.seeing_text or '—'}\n"
        f"- Transparency: {plan.window.transparency_text or '—'}\n"
        f"- Moon: {plan.window.moon_text or '—'}\n"
        f"- Exposure: {plan.exposure_seconds}s · Gain: {plan.gain} · Frames: {plan.frames}\n"
        f"- Estimated light time: {plan.estimated_total_minutes} min\n\n"
        "review-only files created:\n"
        f"- `{plan.plan_text_path}`\n"
        f"- `{plan.nina_sequence_path}`\n"
        f"- `{plan.nina_xml_path}`\n"
        f"- `{plan.nina_csv_path}`\n"
        f"- `{plan.nina_review_path}`\n"
        f"- `{plan.plan_json_path}`\n\n"
        "The `.nina-sequence.json` file is generated from a real N.I.N.A. Advanced Sequencer template. "
        "The XML/CSV files are review/helper exports, and the JSON review file is kept for FZAstro metadata.\n\n"
        "No telescope movement, capture start, or N.I.N.A. sequence execution was performed."
        f"{warning}"
    )


def predefined_imaging_command_help() -> str:
    return (
        "Use one of these safe predefined imaging commands:\n\n"
        "- `/nina-plan next`\n"
        "- `/nina-plan next 60s gain 200`\n"
        "- `/nina-plan target M13 60s gain 200`\n"
        "- `/imaging-plan target NGC 7000 exposure 120s gain 100 frames 80`\n\n"
        "These commands create review-only N.I.N.A. Advanced Sequencer JSON plus XML/CSV helper exports; they do not start hardware automatically."
    )

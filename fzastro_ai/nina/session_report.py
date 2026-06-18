from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_session_dir() -> Path:
    return Path.home() / "Documents" / "FZAstroAI" / "Imaging Sessions"


IMAGING_SESSION_DIR = _default_session_dir()


@dataclass(frozen=True)
class NinaSessionReport:
    """Files produced for a FZAstro Imaging / N.I.N.A. session report."""

    session_id: str
    session_dir: str
    report_markdown_path: str
    report_json_path: str


def _safe_name(value: Any, default: str = "session") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or default)).strip("_")
    return text or default


def _minutes_text(minutes: Any) -> str:
    try:
        value = int(float(minutes))
    except Exception:
        return "—"
    hours, mins = divmod(max(0, value), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _load_plan(plan_json_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(plan_json_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan = dict(payload.get("plan") or {})
    if not plan:
        raise ValueError(f"Plan JSON did not contain a plan object: {path}")
    return payload, plan


def _location_lines(location: dict[str, Any]) -> list[str]:
    if not isinstance(location, dict):
        return ["- Site: —"]
    site = (
        location.get("name")
        or location.get("label")
        or location.get("site_name")
        or "Current observing site"
    )
    lat = location.get("lat")
    lon = location.get("lon")
    elev = (
        location.get("elev")
        if location.get("elev") is not None
        else location.get("elevation_m")
    )
    tz = location.get("tz") or location.get("timezone") or "—"
    lines = [
        f"- Site: {site}",
        f"- Coordinates: {lat if lat is not None else '—'}, {lon if lon is not None else '—'}",
    ]
    lines.append(f"- Elevation: {elev if elev is not None else '—'} m")
    lines.append(f"- Timezone: {tz}")
    quality = (
        location.get("sky_quality")
        if isinstance(location.get("sky_quality"), dict)
        else {}
    )
    bortle = location.get("bortle") or quality.get("bortle")
    sqm = location.get("sqm") or quality.get("sqm") or quality.get("sqm_mag_arcsec2")
    if bortle or sqm:
        lines.append(f"- Sky quality: Bortle {bortle or '—'} · SQM {sqm or '—'}")
    return lines


def create_session_report(
    plan_json_path: str | Path,
    *,
    status: str = "planned",
    execution_mode: str = "manual_start_in_nina",
    notes: str = "",
    events: list[dict[str, Any]] | None = None,
    output_dir: str | Path | None = None,
) -> NinaSessionReport:
    """Create a session report from a confirmed FZAstro/N.I.N.A. plan.

    This report is generated from FZAstro structured plan data and optional N.I.N.A.
    execution events.  It does not infer data by scraping UI HTML and it does not
    start equipment-control actions.
    """

    payload, plan = _load_plan(plan_json_path)
    target_name = str(plan.get("target_name") or "Target")
    created = datetime.now(timezone.utc)
    session_id = f"{created.strftime('%Y%m%d_%H%M%S')}_{_safe_name(target_name)}"
    session_dir = Path(output_dir or IMAGING_SESSION_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    window = dict(plan.get("window") or {})
    framing = dict(plan.get("framing") or {})
    location = dict(plan.get("location") or {})
    event_list = list(events or [])

    report = {
        "schema": "fzastro_nina_session_report_v1",
        "created_utc": created.isoformat(),
        "status": str(status or "planned"),
        "execution_mode": str(execution_mode or "manual_start_in_nina"),
        "plan_json_path": str(plan_json_path),
        "nina_sequence_path": str(plan.get("nina_sequence_path") or ""),
        "target": {
            "name": target_name,
            "type": plan.get("target_type") or "",
            "ra": plan.get("ra") or "",
            "dec": plan.get("dec") or "",
            "magnitude": plan.get("magnitude") or "",
            "size": plan.get("size") or "",
        },
        "location": location,
        "conditions": window,
        "capture": {
            "camera_model": framing.get("camera_model") or "",
            "focal_length_mm": framing.get("focal_length_mm")
            or framing.get("effective_focal_length_mm"),
            "fov_width_deg": framing.get("fov_width_deg"),
            "fov_height_deg": framing.get("fov_height_deg"),
            "image_scale_arcsec_px": framing.get("image_scale_arcsec_px"),
            "target_fit": framing.get("target_fit"),
            "exposure_seconds": plan.get("exposure_seconds"),
            "gain": plan.get("gain"),
            "frames_planned": plan.get("frames"),
            "estimated_total_minutes": plan.get("estimated_total_minutes"),
        },
        "events": event_list,
        "notes": str(notes or ""),
        "safety": {
            "fzastro_started_sequence": False,
            "hardware_actions_executed_by_fzastro": False,
            "message": "FZAstro generated this report from the confirmed plan and optional N.I.N.A. execution notes/events.",
        },
    }

    report_json_path = session_dir / "session-report.json"
    report_md_path = session_dir / "session-report.md"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines = [
        f"# FZAstro Imaging Session Report — {target_name}",
        "",
        f"- Status: {report['status']}",
        f"- Execution mode: {report['execution_mode']}",
        f"- Plan: `{plan_json_path}`",
        f"- N.I.N.A. sequence: `{report['nina_sequence_path'] or '—'}`",
        "",
        "## Target",
        f"- Name: {target_name}",
        f"- Type: {plan.get('target_type') or '—'}",
        f"- RA / Dec: {plan.get('ra') or '—'} / {plan.get('dec') or '—'}",
        f"- Magnitude: {plan.get('magnitude') or '—'}",
        f"- Size: {plan.get('size') or '—'}",
        "",
        "## Location / Site",
        *_location_lines(location),
        "",
        "## Weather / SEEING Evaluation",
        f"- Best window: {window.get('start_label') or window.get('start_iso') or '—'} → {window.get('end_label') or window.get('end_iso') or '—'}",
        f"- SEEING score: {window.get('score') or '—'}/100 · {window.get('score_label') or '—'}",
        f"- Cloud: {window.get('cloud_pct') if window.get('cloud_pct') is not None else '—'}% · {window.get('cloud_text') or '—'}",
        f"- Seeing: {window.get('seeing_text') or '—'}",
        f"- Transparency: {window.get('transparency_text') or '—'}",
        f"- Moon: {window.get('moon_text') or '—'}",
        f"- Astro dark: {'yes' if window.get('astro_dark') else 'no'}",
        "",
        "## Capture / Framing",
        f"- Camera: {framing.get('camera_model') or '—'}",
        f"- Focal length: {framing.get('effective_focal_length_mm') or framing.get('focal_length_mm') or '—'} mm",
        f"- FOV: {framing.get('fov_width_deg') or '—'}° × {framing.get('fov_height_deg') or '—'}°",
        f"- Image scale: {framing.get('image_scale_arcsec_px') or '—'} arcsec/px",
        f"- Target fit: {framing.get('target_fit') or '—'}",
        f"- Exposure: {plan.get('exposure_seconds') or '—'}s",
        f"- Gain: {plan.get('gain') if plan.get('gain') is not None else '—'}",
        f"- Frames planned: {plan.get('frames') or '—'}",
        f"- Estimated integration: {_minutes_text(plan.get('estimated_total_minutes'))}",
        "",
        "## Session Events",
    ]
    if event_list:
        for event in event_list:
            lines.append(
                f"- {event.get('time') or event.get('timestamp') or '—'} · {event.get('message') or event}"
            )
    else:
        lines.append("- No execution events were attached yet.")
    lines.extend(
        [
            "",
            "## Notes",
            str(notes or "No additional notes."),
            "",
            "## Safety",
            "FZAstro AI generated the plan/report and may open the confirmed sequence for review. Hardware execution remains under N.I.N.A. and explicit user control unless a future execution bridge is explicitly armed and configured.",
        ]
    )
    report_md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    return NinaSessionReport(
        session_id=session_id,
        session_dir=str(session_dir),
        report_markdown_path=str(report_md_path),
        report_json_path=str(report_json_path),
    )

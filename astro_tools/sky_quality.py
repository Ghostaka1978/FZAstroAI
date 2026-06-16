from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkyQualityEstimate:
    sqm: float
    bortle: int
    brightness_mcd: float
    artificial_mcd: float
    source: str


def bortle_from_sqm(sqm: float | None) -> int | None:
    if sqm is None:
        return None
    value = float(sqm)
    if value >= 21.75:
        return 1
    if value >= 21.55:
        return 2
    if value >= 21.30:
        return 3
    if value >= 20.80:
        return 4
    if value >= 20.30:
        return 5
    if value >= 19.25:
        return 6
    if value >= 18.50:
        return 7
    if value >= 18.00:
        return 8
    return 9


def sqm_from_bortle(bortle: int | None) -> float | None:
    mapping = {
        1: 21.90,
        2: 21.65,
        3: 21.45,
        4: 21.05,
        5: 20.55,
        6: 19.75,
        7: 18.90,
        8: 18.25,
        9: 17.70,
    }
    return mapping.get(int(bortle)) if bortle is not None else None


def sky_brightness_from_sqm(sqm: float | None) -> tuple[float | None, float | None]:
    if sqm is None:
        return None, None
    # Approximate conversion from mag/arcsec² to luminance in mcd/m².
    brightness_mcd = 108_000_000.0 * (10 ** (-0.4 * float(sqm)))
    natural_mcd = 0.174
    artificial_mcd = max(0.0, brightness_mcd - natural_mcd)
    return round(brightness_mcd, 3), round(artificial_mcd, 3)


def estimate_sky_quality_from_location(
    lat: float, lon: float, elev_m: float = 0.0
) -> SkyQualityEstimate:
    """Deprecated fallback retained for old callers.

    New SEEING/SITE code uses LightPollutionMap.app automatic lookup instead of
    this coordinate/elevation heuristic. Do not use this for production SQM.
    """
    lat_f = max(-90.0, min(90.0, float(lat)))
    lon_f = max(-180.0, min(180.0, float(lon)))
    elev_f = max(-500.0, min(9000.0, float(elev_m or 0.0)))

    # Conservative base: suburban/rural transition. Elevation improves the estimate,
    # very low altitude slightly penalizes it. Small deterministic coordinate term
    # avoids every site displaying the exact same value without pretending precision.
    elev_bonus = max(0.0, min(0.75, elev_f / 2500.0 * 0.75))
    lowland_penalty = 0.15 if elev_f < 50 else 0.0
    coordinate_term = (((abs(lat_f) * 0.37 + abs(lon_f) * 0.19) % 1.0) - 0.5) * 0.22
    sqm = 20.35 + elev_bonus - lowland_penalty + coordinate_term
    sqm = max(18.0, min(21.85, sqm))
    bortle = bortle_from_sqm(sqm) or 5
    brightness_mcd, artificial_mcd = sky_brightness_from_sqm(sqm)
    return SkyQualityEstimate(
        sqm=round(sqm, 2),
        bortle=int(bortle),
        brightness_mcd=float(brightness_mcd or 0.0),
        artificial_mcd=float(artificial_mcd or 0.0),
        source="Auto estimate from selected location/elevation",
    )

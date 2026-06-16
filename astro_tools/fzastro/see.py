from __future__ import annotations

import argparse, json, math
from datetime import datetime, timezone, timedelta, date
from typing import List, Tuple, Optional, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API_BASE_FORECAST = "https://api.open-meteo.com/v1/forecast"
API_BASE_SUNRISE = "https://api.met.no/weatherapi/sunrise/3.0/moon"


DEFAULT_LAT = 50.2459
DEFAULT_LON = 8.4923
DEFAULT_ELEV = 660.0
import sys

# DEFAULT_TZ = sys.argv[sys.argv.index("--tz")+1] if "--tz" in sys.argv else "Europe/Berlin"
DEFAULT_TZ = "Europe/Berlin"


def _jd_from_dt_utc(dt_utc: datetime) -> float:
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def _norm360(x: float) -> float:
    return (x % 360.0 + 360.0) % 360.0


def solar_altitude_deg(dt_utc: datetime, lat_deg: float, lon_deg: float) -> float:
    jd = _jd_from_dt_utc(dt_utc)
    n = jd - 2451545.0
    L = _norm360(280.460 + 0.9856474 * n)
    g = math.radians(_norm360(357.528 + 0.9856003 * n))
    lam = math.radians(_norm360(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)))
    eps = math.radians(23.439 - 0.000013 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = _norm360(280.46061837 + 360.98564736629 * (jd - 2451545.0))
    lst = _norm360(gmst + lon_deg)
    ha = math.radians(_norm360(lst) - math.degrees(ra))
    lat = math.radians(lat_deg)
    alt = math.asin(
        math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)
    )
    return math.degrees(alt)


def _alts_for_times_utc(
    times_local_iso: List[str], tz_str: str, lat: float, lon: float
) -> List[float]:
    tz = ZoneInfo(tz_str)
    alts: List[float] = []
    for s in times_local_iso:
        dt_local = datetime.fromisoformat(s).replace(tzinfo=tz)
        dt_utc = dt_local.astimezone(timezone.utc)
        alts.append(solar_altitude_deg(dt_utc, lat, lon))
    return alts


def _interpolate_crossing(
    t0_local: datetime,
    a0: float,
    t1_local: datetime,
    a1: float,
    target_alt: float = -18.0,
) -> datetime:
    if a0 == a1:
        return t0_local
    f = (target_alt - a0) / (a1 - a0)
    f = max(0.0, min(1.0, f))
    return t0_local + (t1_local - t0_local) * f


def find_all_astro_dark_segments_with_exact(
    times_local_iso: List[str], tz_str: str, lat: float, lon: float
) -> List[Tuple[int, int, datetime, datetime]]:
    tz = ZoneInfo(tz_str)
    alts = _alts_for_times_utc(times_local_iso, tz_str, lat, lon)
    segs: List[Tuple[int, int, datetime, datetime]] = []
    below = False
    start_idx = 0
    exact_start: Optional[datetime] = None

    for i in range(len(times_local_iso)):
        a = alts[i]
        if not below and a < -18.0:
            below = True
            start_idx = i
            if i > 0:
                t0 = datetime.fromisoformat(times_local_iso[i - 1]).replace(tzinfo=tz)
                t1 = datetime.fromisoformat(times_local_iso[i]).replace(tzinfo=tz)
                exact_start = _interpolate_crossing(t0, alts[i - 1], t1, alts[i], -18.0)
            else:
                exact_start = datetime.fromisoformat(times_local_iso[i]).replace(
                    tzinfo=tz
                )
        elif below and a >= -18.0:
            below = False
            end_idx = i - 1
            t0 = datetime.fromisoformat(times_local_iso[i - 1]).replace(tzinfo=tz)
            t1 = datetime.fromisoformat(times_local_iso[i]).replace(tzinfo=tz)
            exact_end = _interpolate_crossing(t0, alts[i - 1], t1, alts[i], -18.0)
            segs.append((start_idx, end_idx, exact_start, exact_end))

    if below:
        end_idx = len(times_local_iso) - 1
        exact_end = datetime.fromisoformat(times_local_iso[end_idx]).replace(tzinfo=tz)
        segs.append((start_idx, end_idx, exact_start, exact_end))

    return segs


def pick_next_n_segments(
    segments: List[Tuple[int, int, datetime, datetime]], now_local: datetime, n: int
) -> List[Tuple[int, int, datetime, datetime]]:
    picked: List[Tuple[int, int, datetime, datetime]] = []
    for seg in segments:
        _, _, t_start, t_end = seg
        if t_start <= now_local <= t_end or now_local < t_start:
            picked.append(seg)
        if len(picked) >= n:
            break
    return picked


_SYNODIC = 29.53058867
_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def moon_illum_and_name(dt_utc: datetime) -> Tuple[float, str]:
    days = (dt_utc - _EPOCH).total_seconds() / 86400.0
    age = (days % _SYNODIC + _SYNODIC) % _SYNODIC
    k = 2.0 * math.pi * age / _SYNODIC
    illum = 0.5 * (1 - math.cos(k))
    if age < 1.84566:
        name = "New Moon"
    elif age < 5.53699:
        name = "Waxing Crescent"
    elif age < 9.22831:
        name = "First Quarter"
    elif age < 12.91963:
        name = "Waxing Gibbous"
    elif age < 16.61096:
        name = "Full Moon"
    elif age < 20.30228:
        name = "Waning Gibbous"
    elif age < 23.99361:
        name = "Last Quarter"
    elif age < 27.68493:
        name = "Waning Crescent"
    else:
        name = "New Moon"
    return illum, name


def fetch_hourly(
    lat: float, lon: float, tz: str, elev: Optional[float], forecast_days: int
):
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "cloud_cover",
                "cloud_cover_low",
                "cloud_cover_mid",
                "cloud_cover_high",
                "pressure_msl",
                "wind_speed_10m",
                "wind_gusts_10m",
                "dew_point_2m",
                "wind_direction_10m",
            ]
        ),
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "timezone": tz,
        "forecast_days": str(forecast_days),
        "past_days": "1",
    }
    if elev is not None:
        params["elevation"] = f"{elev:.1f}"

    url = f"{API_BASE_FORECAST}?{urlencode(params)}"
    req = Request(
        url, headers={"User-Agent": "astro-multi-nights/1.6 (+https://fzastro.com)"}
    )
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as r:
                data = json.load(r)
            break
        except HTTPError as e:
            last_error = e
            if e.code not in (502, 503, 504) or attempt == 2:
                raise SystemExit(
                    f"HTTP error {e.code} from Open-Meteo (forecast): {e.reason}"
                )
            import time

            time.sleep(1.5 * (attempt + 1))
        except URLError as e:
            last_error = e
            if attempt == 2:
                raise SystemExit(
                    f"Network error contacting Open-Meteo (forecast): {last_error}"
                )
            import time

            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_error = e
            if attempt == 2:
                raise SystemExit(
                    f"Network error contacting Open-Meteo (forecast): {last_error}"
                )
            import time

            time.sleep(1.5 * (attempt + 1))
    else:
        raise SystemExit(
            f"Network error contacting Open-Meteo (forecast): {last_error}"
        )

    h = data.get("hourly", {})
    times = h.get("time", [])
    temps = h.get("temperature_2m", [])
    rh = h.get("relative_humidity_2m", [])
    cc = h.get("cloud_cover", [])
    ccl = h.get("cloud_cover_low", [])
    ccm = h.get("cloud_cover_mid", [])
    cch = h.get("cloud_cover_high", [])
    pmsl = h.get("pressure_msl", [])
    ws = h.get("wind_speed_10m", [])
    wg = h.get("wind_gusts_10m", [])
    dp = h.get("dew_point_2m", [])
    wd = h.get("wind_direction_10m", [])
    tz_out = data.get("timezone", tz)

    n = min(
        *(len(x) for x in [times, temps, rh, cc, ccl, ccm, cch, pmsl, ws, wg, dp, wd])
    )
    if n == 0:
        raise SystemExit("No hourly data returned.")

    def cut(a):
        return a[:n]

    return (
        times[:n],
        cut(temps),
        cut(rh),
        cut(cc),
        cut(ccl),
        cut(ccm),
        cut(cch),
        cut(pmsl),
        cut(ws),
        cut(wg),
        cut(dp),
        cut(wd),
        tz_out,
    )


def _date_range_inclusive(d0: date, d1: date) -> List[date]:
    out = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _offset_str_for_date(tz_str: str, d: date) -> str:
    tz = ZoneInfo(tz_str)
    dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=tz)
    off = dt.utcoffset() or timedelta(0)
    sign = "+" if off >= timedelta(0) else "-"
    off = abs(off)
    hh = int(off.total_seconds() // 3600)
    mm = int((off.total_seconds() % 3600) // 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def fetch_moonrise_set(
    lat: float, lon: float, tz: str, start_d: date, end_d: date
) -> Dict[date, Dict[str, Optional[str]]]:
    out: Dict[date, Dict[str, Optional[str]]] = {}
    for d in _date_range_inclusive(start_d, end_d):
        params = {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "date": d.isoformat(),
            "offset": _offset_str_for_date(tz, d),
        }
        url = f"{API_BASE_SUNRISE}?{urlencode(params)}"
        req = Request(
            url, headers={"User-Agent": "astro-multi-nights/1.6 (+https://fzastro.com)"}
        )
        try:
            with urlopen(req, timeout=20) as r:
                data = json.load(r)
        except Exception:
            out[d] = {"moonrise": None, "moonset": None}
            continue
        props = (data or {}).get("properties", {})
        mr = (props.get("moonrise") or {}).get("time")
        ms = (props.get("moonset") or {}).get("time")
        out[d] = {"moonrise": mr, "moonset": ms}
    return out


def _fmt_time_iso_local(s: str) -> str:
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s.replace("T", " ")


def _fmt_hhmm_local_or_dash(s: Optional[str]) -> str:
    if not s:
        return "--:--"
    try:
        return datetime.fromisoformat(s).strftime("%H:%M")
    except Exception:
        try:
            return datetime.fromisoformat(s.replace(" ", "T")).strftime("%H:%M")
        except Exception:
            return "--:--"


def _coalesce_moon_time(primary: Optional[str], fallback: Optional[str]) -> str:
    a = _fmt_hhmm_local_or_dash(primary)
    if a == "--:--":
        b = _fmt_hhmm_local_or_dash(fallback)
        return b
    return a


def _print_one_segment(
    times,
    temps,
    rh,
    cc,
    ccl,
    ccm,
    cch,
    pmsl,
    ws,
    wg,
    dp,
    wd,
    tz: str,
    seg: Tuple[int, int, datetime, datetime],
    lat: float,
    lon: float,
    elev: Optional[float],
    moon_rs_by_date: Dict[date, Dict[str, Optional[str]]],
) -> None:

    s_idx, e_idx, exact_start, exact_end = seg
    start_print_idx = max(s_idx - 1, 0)

    tzinfo = ZoneInfo(tz)
    start_local = exact_start.astimezone(tzinfo)
    end_local = exact_end.astimezone(tzinfo)

    midpoint_local = exact_start + (exact_end - exact_start) / 2
    midpoint_utc = midpoint_local.astimezone(timezone.utc)
    illum_mid, phase_name = moon_illum_and_name(midpoint_utc)
    illum_mid_pct = int(round(illum_mid * 100))

    rs_start = moon_rs_by_date.get(
        start_local.date(), {"moonrise": None, "moonset": None}
    )
    rs_end = moon_rs_by_date.get(end_local.date(), {"moonrise": None, "moonset": None})

    mr = _coalesce_moon_time(rs_start.get("moonrise"), rs_end.get("moonrise"))
    ms = _coalesce_moon_time(rs_start.get("moonset"), rs_end.get("moonset"))

    W_TIME = 22
    press_label = "MSLP (hPa)"
    headers = (
        f"{'Local Time':<{W_TIME}} "
        f"{'Score':>6} "
        f"{'Cloud %':>8} {'Low %':>7} {'Mid %':>7} {'High %':>7} "
        f"{'Moon %':>8} "
        f"{'Temp (°C)':>10} {'DewPt (°C)':>12} {'RH (%)':>7} "
        f"{'Wind (m/s)':>15} {'Gust (m/s)':>12} {'Dir (°)':>8} {press_label:>12}"
    )
    line = "-" * len(headers)

    site_str = f"Site: lat {lat:.2f}°, lon {lon:.2f}°, elevation {elev:.0f} meters"
    dur_min = int((exact_end - exact_start).total_seconds() // 60)
    dark_str = (
        f"Astronomical darkness: "
        f"{start_local.strftime('%A %Y-%m-%d %H:%M')} → {end_local.strftime('%A %Y-%m-%d %H:%M')}  "
        f"({dur_min // 60}h {dur_min % 60:02d}m)"
    )
    moon_str = f"Moon Phase: {illum_mid_pct}% — {phase_name}  •  Rise {mr}  •  Set {ms}"

    print()
    print(f"Timezone: {tz}")
    print(f"{site_str}")
    print(f"{dark_str}")
    print(f"{moon_str}\n")
    print(
        "\nScore ≥80 = Good · 50–79 = OK · <50 = Poor - Score breakdown: Clouds 0–60 · Moon 0–20 · Humidity/Dew 0–10 · Wind 0–10"
    )
    print(line)
    print(headers)
    print(line)

    for i in range(start_print_idx, e_idx + 1):
        dt_local = datetime.fromisoformat(times[i]).replace(tzinfo=tzinfo)
        dt_utc = dt_local.astimezone(timezone.utc)
        illum, _ = moon_illum_and_name(dt_utc)
        moon_pct = int(round(illum * 100))
        cc_i = cc[i] if cc[i] is not None else 0
        ccl_i = ccl[i] if ccl[i] is not None else 0
        rh_i = rh[i] if rh[i] is not None else 0
        t_i = temps[i] if temps[i] is not None else 0.0
        dp_i = dp[i] if dp[i] is not None else t_i - 10.0
        ws_i = ws[i] if ws[i] is not None else 0.0
        wg_i = wg[i] if wg[i] is not None else 0.0

        def clamp(x, a, b):
            return a if x < a else b if x > b else x

        cloud_pen = clamp(cc_i, 0.0, 60.0)

        mr_str = _coalesce_moon_time(rs_start.get("moonrise"), rs_end.get("moonrise"))
        ms_str = _coalesce_moon_time(rs_start.get("moonset"), rs_end.get("moonset"))
        t_hm = dt_local.strftime("%H:%M")
        moon_up = False
        if mr_str != "--:--" and ms_str != "--:--":
            if mr_str <= ms_str:
                moon_up = (t_hm >= mr_str) and (t_hm < ms_str)
            else:
                moon_up = (t_hm >= mr_str) or (t_hm < ms_str)
        elif mr_str != "--:--":
            moon_up = t_hm >= mr_str
        elif ms_str != "--:--":
            moon_up = t_hm < ms_str

        illum_s = clamp((moon_pct - 10.0) / 70.0, 0.0, 1.0)
        moon_pen = 20.0 * illum_s * (1.0 if moon_up else 0.0)

        spread = t_i - dp_i
        if spread >= 4.0 and rh_i <= 80:
            hum_pen = 0.0
        elif spread < 2.0 or rh_i > 90:
            hum_pen = 10.0
        else:
            k = max(0.0, min(1.0, (4.0 - spread) / 2.0, (rh_i - 80.0) / 10.0))
            hum_pen = 5.0 + 5.0 * k

        wind_v = max(ws_i, wg_i)
        if wind_v <= 3.0:
            wind_pen = 0.0
        elif wind_v <= 6.0:
            wind_pen = 3.0 + (wind_v - 3.0) * (4.0 / 3.0)
        elif wind_v <= 9.0:
            wind_pen = 7.0 + (wind_v - 6.0) * (3.0 / 3.0)
        else:
            wind_pen = 10.0

        score = int(round(100.0 - (cloud_pen + moon_pen + hum_pen + wind_pen)))
        if score < 0:
            score = 0
        if score > 100:
            score = 100
        score_str = f"{score:>6d}"

        temp_str = f"{temps[i]:10.1f}" if temps[i] is not None else f"{'N/A':>10}"
        rh_str = f"{rh[i]:7d}" if rh[i] is not None else f"{'N/A':>7}"
        cc_str = f"{cc[i]:8d}" if cc[i] is not None else f"{'N/A':>8}"
        ccl_str = f"{ccl[i]:7d}" if ccl[i] is not None else f"{'N/A':>7}"
        ccm_str = f"{ccm[i]:7d}" if ccm[i] is not None else f"{'N/A':>7}"
        cch_str = f"{cch[i]:7d}" if cch[i] is not None else f"{'N/A':>7}"
        moon_str_val = f"{moon_pct:8d}" if moon_pct is not None else f"{'N/A':>8}"
        press_str = f"{pmsl[i]:12.1f}" if pmsl[i] is not None else f"{'N/A':>12}"
        ws_str = f"{ws[i]:15.2f}" if ws[i] is not None else f"{'N/A':>15}"
        wg_str = f"{wg[i]:12.2f}" if wg[i] is not None else f"{'N/A':>12}"
        dp_str = f"{dp[i]:12.1f}" if dp[i] is not None else f"{'N/A':>12}"
        wd_str = f"{wd[i]:8d}" if wd[i] is not None else f"{'N/A':>8}"
        if cc[i] is None:
            status = "CLOUDS"
        elif cc[i] == 0:
            status = "CLEAR"
        elif cc[i] <= 20:
            status = "PARTLY"
        else:
            status = "CLOUDS"
        print(
            f"{_fmt_time_iso_local(times[i]):<{W_TIME}} "
            f"{score_str} "
            f"{cc_str} {ccl_str} {ccm_str} {cch_str} "
            f"{moon_str_val} "
            f"{temp_str} {dp_str} {rh_str} "
            f"{ws_str} {wg_str} {wd_str} {press_str}"
        )

    print(line)


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Show astronomical darkness periods with hourly weather forecast, "
            "moon phase, and moon rise/set times."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 see.py --lat 50.2459 --lon 8.4923 --elev 660 --tz Europe/Berlin
  python3 see.py --lat 48.85 --lon 2.35 --tz Europe/Paris -n 2
  python3 see.py --lat 34.05 --lon -118.25 --tz America/Los_Angeles --elev 300""",
    )
    p.add_argument(
        "--lat",
        type=float,
        default=DEFAULT_LAT,
        help=f"Latitude in decimal degrees (north positive). Default: {DEFAULT_LAT}",
    )
    p.add_argument(
        "--lon",
        type=float,
        default=DEFAULT_LON,
        help=f"Longitude in decimal degrees (east positive). Default: {DEFAULT_LON}",
    )
    p.add_argument(
        "--tz",
        type=str,
        default=DEFAULT_TZ,
        help=f"IANA time zone string (e.g., Europe/Berlin). Default: {DEFAULT_TZ}",
    )
    p.add_argument(
        "--elev",
        type=float,
        default=DEFAULT_ELEV,
        help=f"Elevation above sea level in meters (display only). Default: {DEFAULT_ELEV:.0f}",
    )
    p.add_argument(
        "-n",
        "--nights",
        type=int,
        choices=[1, 2, 3, 4],
        default=2,
        help="Number of upcoming astro-dark nights to show (1–4). Default: 2",
    )
    args = p.parse_args()

    nights = args.nights
    forecast_days = max(2, nights + 1)

    elev_for_api: Optional[float] = args.elev
    if elev_for_api is not None and elev_for_api > 6000:
        print(f"Note: --elev {elev_for_api:.0f} m is unrealistic; ignoring elevation.")
        elev_for_api = None

    # Fetch, ignore API timezone, and use the requested one
    times, temps, rh, cc, ccl, ccm, cch, pmsl, ws, wg, dp, wd, _tz_api = fetch_hourly(
        args.lat, args.lon, args.tz, elev_for_api, forecast_days
    )
    tz = args.tz  # <- force Europe/Berlin (or whatever was passed)

    tzinfo = ZoneInfo(tz)
    all_dt_local = [datetime.fromisoformat(t).replace(tzinfo=tzinfo) for t in times]
    start_d = (all_dt_local[0] - timedelta(days=1)).date()
    end_d = (all_dt_local[-1] + timedelta(days=1)).date()
    moon_rs_by_date = fetch_moonrise_set(args.lat, args.lon, tz, start_d, end_d)

    now_local = datetime.now(ZoneInfo(tz))
    segs_all = find_all_astro_dark_segments_with_exact(times, tz, args.lat, args.lon)
    segs = pick_next_n_segments(segs_all, now_local, nights)

    if not segs:
        print("No astronomical darkness in the available forecast horizon.")
        return

    for seg in segs:
        _print_one_segment(
            times,
            temps,
            rh,
            cc,
            ccl,
            ccm,
            cch,
            pmsl,
            ws,
            wg,
            dp,
            wd,
            args.tz,  # force Europe/Berlin
            seg,
            args.lat,
            args.lon,
            args.elev,
            moon_rs_by_date,
        )


if __name__ == "__main__":
    main()

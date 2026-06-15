from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import List, Optional, Tuple, Iterable, Dict
import json
import argparse
import math

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord, AltAz, EarthLocation, get_sun, Angle
from astropy.time import Time
from zoneinfo import ZoneInfo
import os, sys

USE_TTY_COLOR = sys.stdout.isatty() and (os.getenv("NO_COLOR") is None)
DIM = "\x1b[2m" if USE_TTY_COLOR else ""
RESET = "\x1b[0m" if USE_TTY_COLOR else ""

LAT, LON, ELEV = 50.2459, 8.4923, 660.0
DEFAULT_TZ = (
    sys.argv[sys.argv.index("--tz") + 1] if "--tz" in sys.argv else "Europe/Berlin"
)
TZ = ZoneInfo(DEFAULT_TZ)
LIMIT = 500
MIN_ALT = 30.0
STEP_MIN = 3
MIN_DURATION_MIN = 15
MAX_AIRMASS = 2.0
EDGE_GUARD_MIN = 5


def _astro_night_bounds(day_local: date, tz: ZoneInfo) -> Tuple[datetime, datetime]:
    loc = EarthLocation(lat=LAT * u.deg, lon=LON * u.deg, height=ELEV * u.m)
    t0 = datetime.combine(day_local, datetime.min.time(), tz)
    t1 = t0 + timedelta(days=1)
    dt_list = [t0 + timedelta(minutes=m) for m in range(24 * 60 + 1)]
    t = Time(dt_list)
    alt = get_sun(t).transform_to(AltAz(obstime=t, location=loc)).alt.degree
    idx = np.where(alt <= -18.0)[0]
    if idx.size == 0:
        return t0, t1
    return dt_list[int(idx[0])], dt_list[int(idx[-1])]


def _ref_hour_local(dark_start_local: datetime, dark_end_local: datetime) -> float:
    if dark_end_local <= dark_start_local:
        dark_end_local = dark_end_local + timedelta(days=1)
    mid = dark_start_local + (dark_end_local - dark_start_local) / 2
    return (mid.hour + mid.minute / 60 + mid.second / 3600) % 24


dark_start_local, dark_end_local = _astro_night_bounds(date.today(), TZ)
REF_HOUR_LOCAL = _ref_hour_local(dark_start_local, dark_end_local)
MIN_ALT_AT_REF = 30.0
DEC_MAX_N = +90.0
DIURNAL_SWING_MIN = 1.0
API_BASE_SUNRISE = "https://api.met.no/weatherapi/sunrise/3.0/moon"

CATALOG = [
    {
        "name": "M 2",
        "type": "Globular",
        "constellation": "Aqr",
        "ra": "21:33:27.0",
        "dec": "-00:49:23",
        "mag": 6.5,
        "size_deg": "0.267°",
        "width_deg": 0.26666666666666666,
        "height_deg": 0.26666666666666666,
        "size_src": "16'",
    },
    {
        "name": "M 3",
        "type": "Globular",
        "constellation": "CVn",
        "ra": "13:42:11.6",
        "dec": "+28:22:32",
        "mag": 6.2,
        "size_deg": "0.300°",
        "width_deg": 0.3,
        "height_deg": 0.3,
        "size_src": "18'",
    },
    {
        "name": "M 4",
        "type": "Globular",
        "constellation": "Sco",
        "ra": "16:23:35.2",
        "dec": "-26:31:32",
        "mag": 5.6,
        "size_deg": "0.433°",
        "width_deg": 0.43333333333333335,
        "height_deg": 0.43333333333333335,
        "size_src": "26'",
    },
    {
        "name": "M 5",
        "type": "Globular",
        "constellation": "Ser",
        "ra": "15:18:33.2",
        "dec": "+02:04:57",
        "mag": 5.6,
        "size_deg": "0.383°",
        "width_deg": 0.38333333333333336,
        "height_deg": 0.38333333333333336,
        "size_src": "23'",
    },
    {
        "name": "M 8",
        "aliases": ["Lagoon Nebula"],
        "type": "Emission",
        "constellation": "Sgr",
        "ra": "18:03:37.0",
        "dec": "-24:23:12",
        "mag": 6.0,
        "size_deg": "1.500°×0.667°",
        "width_deg": 1.5,
        "height_deg": 0.6666666666666666,
        "size_src": "90'×40'",
    },
    {
        "name": "M 9",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "17:19:11.8",
        "dec": "-18:30:58",
        "mag": 7.7,
        "size_deg": "0.150°",
        "width_deg": 0.15,
        "height_deg": 0.15,
        "size_src": "9'",
    },
    {
        "name": "M 10",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "16:57:09.0",
        "dec": "-04:05:58",
        "mag": 6.6,
        "size_deg": "0.250°",
        "width_deg": 0.25,
        "height_deg": 0.25,
        "size_src": "15'",
    },
    {
        "name": "M 11",
        "aliases": ["Wild Duck Cluster"],
        "type": "Open",
        "constellation": "Sct",
        "ra": "18:51:05.0",
        "dec": "-06:16:12",
        "mag": 5.8,
        "size_deg": "0.233°",
        "width_deg": 0.23333333333333334,
        "height_deg": 0.23333333333333334,
        "size_src": "14'",
    },
    {
        "name": "M 12",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "16:47:14.0",
        "dec": "-01:56:54",
        "mag": 6.7,
        "size_deg": "0.233°",
        "width_deg": 0.23333333333333334,
        "height_deg": 0.23333333333333334,
        "size_src": "14'",
    },
    {
        "name": "M 13",
        "aliases": ["Hercules Cluster"],
        "type": "Globular",
        "constellation": "Her",
        "ra": "16:41:41.5",
        "dec": "+36:27:37",
        "mag": 5.8,
        "size_deg": "0.333°",
        "width_deg": 0.3333333333333333,
        "height_deg": 0.3333333333333333,
        "size_src": "20'",
    },
    {
        "name": "M 14",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "17:37:36.0",
        "dec": "-03:14:45",
        "mag": 7.6,
        "size_deg": "0.183°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.18333333333333332,
        "size_src": "11'",
    },
    {
        "name": "M 15",
        "type": "Globular",
        "constellation": "Peg",
        "ra": "21:29:58.3",
        "dec": "+12:10:01",
        "mag": 6.2,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "M 16",
        "aliases": ["Eagle Nebula"],
        "type": "Emission",
        "constellation": "Ser",
        "ra": "18:18:48.0",
        "dec": "-13:49:00",
        "mag": 6.0,
        "size_deg": "0.583°×0.467°",
        "width_deg": 0.5833333333333334,
        "height_deg": 0.4666666666666667,
        "size_src": "35'×28'",
    },
    {
        "name": "M 17",
        "aliases": ["Omega Nebula"],
        "type": "Emission",
        "constellation": "Sgr",
        "ra": "18:20:26.0",
        "dec": "-16:10:36",
        "mag": 6.0,
        "size_deg": "0.767°×0.500°",
        "width_deg": 0.7666666666666667,
        "height_deg": 0.5,
        "size_src": "46'×30'",
    },
    {
        "name": "M 18",
        "type": "Open",
        "constellation": "Sgr",
        "ra": "18:19:58.0",
        "dec": "-17:06:00",
        "mag": 6.9,
        "size_deg": "0.150°",
        "width_deg": 0.15,
        "height_deg": 0.15,
        "size_src": "9'",
    },
    {
        "name": "M 19",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "17:02:37.0",
        "dec": "-26:16:04",
        "mag": 6.8,
        "size_deg": "0.150°",
        "width_deg": 0.15,
        "height_deg": 0.15,
        "size_src": "9'",
    },
    {
        "name": "M 20",
        "aliases": ["Trifid Nebula"],
        "type": "Emission",
        "constellation": "Sgr",
        "ra": "18:02:42.0",
        "dec": "-23:01:48",
        "mag": 6.3,
        "size_deg": "0.467°×0.467°",
        "width_deg": 0.4666666666666667,
        "height_deg": 0.4666666666666667,
        "size_src": "28'×28'",
    },
    {
        "name": "M 21",
        "type": "Open",
        "constellation": "Sgr",
        "ra": "18:04:13.0",
        "dec": "-22:29:24",
        "mag": 6.5,
        "size_deg": "0.217°",
        "width_deg": 0.21666666666666667,
        "height_deg": 0.21666666666666667,
        "size_src": "13'",
    },
    {
        "name": "M 22",
        "type": "Globular",
        "constellation": "Sgr",
        "ra": "18:36:24.0",
        "dec": "-23:54:12",
        "mag": 5.1,
        "size_deg": "0.533°",
        "width_deg": 0.5333333333333333,
        "height_deg": 0.5333333333333333,
        "size_src": "32'",
    },
    {
        "name": "M 23",
        "type": "Open",
        "constellation": "Sgr",
        "ra": "17:56:54.0",
        "dec": "-19:01:48",
        "mag": 5.5,
        "size_deg": "0.450°",
        "width_deg": 0.45,
        "height_deg": 0.45,
        "size_src": "27'",
    },
    {
        "name": "M 25",
        "type": "Open",
        "constellation": "Sgr",
        "ra": "18:31:47.0",
        "dec": "-19:07:00",
        "mag": 6.5,
        "size_deg": "0.533°",
        "width_deg": 0.5333333333333333,
        "height_deg": 0.5333333333333333,
        "size_src": "32'",
    },
    {
        "name": "M 26",
        "type": "Open",
        "constellation": "Sct",
        "ra": "18:45:18.0",
        "dec": "-09:23:00",
        "mag": 8.0,
        "size_deg": "0.117°",
        "width_deg": 0.11666666666666667,
        "height_deg": 0.11666666666666667,
        "size_src": "7'",
    },
    {
        "name": "M 27",
        "aliases": ["Dumbbell Nebula"],
        "type": "Planetary",
        "constellation": "Vul",
        "ra": "19:59:36.3",
        "dec": "+22:43:16",
        "mag": 7.4,
        "size_deg": "0.133°×0.093°",
        "width_deg": 0.13333333333333333,
        "height_deg": 0.09333333333333332,
        "size_src": "8'×5.6'",
    },
    {
        "name": "M 28",
        "type": "Globular",
        "constellation": "Sgr",
        "ra": "18:24:33.0",
        "dec": "-24:52:12",
        "mag": 6.9,
        "size_deg": "0.183°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.18333333333333332,
        "size_src": "11'",
    },
    {
        "name": "M 29",
        "type": "Open",
        "constellation": "Cyg",
        "ra": "20:23:57.0",
        "dec": "+38:30:30",
        "mag": 7.1,
        "size_deg": "0.117°",
        "width_deg": 0.11666666666666667,
        "height_deg": 0.11666666666666667,
        "size_src": "7'",
    },
    {
        "name": "M 30",
        "type": "Globular",
        "constellation": "Cap",
        "ra": "21:40:22.0",
        "dec": "-23:10:44",
        "mag": 7.2,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "M 31",
        "aliases": ["Andromeda Galaxy"],
        "type": "Galaxy",
        "constellation": "And",
        "ra": "00:42:44.3",
        "dec": "+41:16:09",
        "mag": 3.4,
        "size_deg": "3.167°×1.000°",
        "width_deg": 3.1666666666666665,
        "height_deg": 1.0,
        "size_src": "190'×60'",
    },
    {
        "name": "M 33",
        "aliases": ["Triangulum Galaxy"],
        "type": "Galaxy",
        "constellation": "Tri",
        "ra": "01:33:50.9",
        "dec": "+30:39:36",
        "mag": 5.7,
        "size_deg": "1.167°×0.667°",
        "width_deg": 1.1666666666666667,
        "height_deg": 0.6666666666666666,
        "size_src": "70'×40'",
    },
    {
        "name": "M 34",
        "type": "Open",
        "constellation": "Per",
        "ra": "02:42:06.0",
        "dec": "+42:45:00",
        "mag": 5.5,
        "size_deg": "0.583°",
        "width_deg": 0.5833333333333334,
        "height_deg": 0.5833333333333334,
        "size_src": "35'",
    },
    {
        "name": "M 35",
        "type": "Open",
        "constellation": "Gem",
        "ra": "06:08:54.0",
        "dec": "+24:20:00",
        "mag": 5.3,
        "size_deg": "0.467°",
        "width_deg": 0.4666666666666667,
        "height_deg": 0.4666666666666667,
        "size_src": "28'",
    },
    {
        "name": "M 36",
        "type": "Open",
        "constellation": "Aur",
        "ra": "05:36:12.0",
        "dec": "+34:08:24",
        "mag": 6.3,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "M 37",
        "type": "Open",
        "constellation": "Aur",
        "ra": "05:52:18.0",
        "dec": "+32:33:00",
        "mag": 5.6,
        "size_deg": "0.400°",
        "width_deg": 0.4,
        "height_deg": 0.4,
        "size_src": "24'",
    },
    {
        "name": "M 38",
        "type": "Open",
        "constellation": "Aur",
        "ra": "05:28:42.0",
        "dec": "+35:50:54",
        "mag": 7.0,
        "size_deg": "0.350°",
        "width_deg": 0.35,
        "height_deg": 0.35,
        "size_src": "21'",
    },
    {
        "name": "M 39",
        "type": "Open",
        "constellation": "Cyg",
        "ra": "21:31:48.0",
        "dec": "+48:26:00",
        "mag": 4.6,
        "size_deg": "0.533°",
        "width_deg": 0.5333333333333333,
        "height_deg": 0.5333333333333333,
        "size_src": "32'",
    },
    {
        "name": "M 41",
        "type": "Open",
        "constellation": "CMa",
        "ra": "06:46:00.0",
        "dec": "-20:44:00",
        "mag": 4.6,
        "size_deg": "0.633°",
        "width_deg": 0.6333333333333333,
        "height_deg": 0.6333333333333333,
        "size_src": "38'",
    },
    {
        "name": "M 42",
        "aliases": ["Orion Nebula"],
        "type": "Emission",
        "constellation": "Ori",
        "ra": "05:35:17.3",
        "dec": "-05:23:28",
        "mag": 4.0,
        "size_deg": "1.083°×1.000°",
        "width_deg": 1.0833333333333333,
        "height_deg": 1.0,
        "size_src": "65'×60'",
    },
    {
        "name": "M 44",
        "aliases": ["Beehive Cluster"],
        "type": "Open",
        "constellation": "Cnc",
        "ra": "08:40:24.0",
        "dec": "+19:41:00",
        "mag": 3.1,
        "size_deg": "1.583°",
        "width_deg": 1.5833333333333333,
        "height_deg": 1.5833333333333333,
        "size_src": "95'",
    },
    {
        "name": "M 45",
        "aliases": ["Pleiades"],
        "type": "Open",
        "constellation": "Tau",
        "ra": "03:47:00.0",
        "dec": "+24:07:00",
        "mag": 1.6,
        "size_deg": "1.833°",
        "width_deg": 1.8333333333333333,
        "height_deg": 1.8333333333333333,
        "size_src": "110'",
    },
    {
        "name": "M 46",
        "type": "Open",
        "constellation": "Pup",
        "ra": "07:41:46.0",
        "dec": "-14:49:00",
        "mag": 6.1,
        "size_deg": "0.450°",
        "width_deg": 0.45,
        "height_deg": 0.45,
        "size_src": "27'",
    },
    {
        "name": "M 47",
        "type": "Open",
        "constellation": "Pup",
        "ra": "07:36:36.0",
        "dec": "-14:30:00",
        "mag": 4.4,
        "size_deg": "0.500°",
        "width_deg": 0.5,
        "height_deg": 0.5,
        "size_src": "30'",
    },
    {
        "name": "M 48",
        "type": "Open",
        "constellation": "Hya",
        "ra": "08:13:48.0",
        "dec": "-05:45:00",
        "mag": 5.8,
        "size_deg": "0.900°",
        "width_deg": 0.9,
        "height_deg": 0.9,
        "size_src": "54'",
    },
    {
        "name": "M 49",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:29:46.8",
        "dec": "+08:00:02",
        "mag": 8.4,
        "size_deg": "0.163°×0.127°",
        "width_deg": 0.16333333333333336,
        "height_deg": 0.12666666666666665,
        "size_src": "9.8'×7.6'",
    },
    {
        "name": "M 50",
        "type": "Open",
        "constellation": "Mon",
        "ra": "07:02:42.0",
        "dec": "-08:20:00",
        "mag": 5.9,
        "size_deg": "0.267°",
        "width_deg": 0.26666666666666666,
        "height_deg": 0.26666666666666666,
        "size_src": "16'",
    },
    {
        "name": "M 51",
        "aliases": ["Whirlpool Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:29:52.7",
        "dec": "+47:11:43",
        "mag": 8.4,
        "size_deg": "0.183°×0.117°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.11666666666666667,
        "size_src": "11'×7'",
    },
    {
        "name": "M 52",
        "type": "Open",
        "constellation": "Cas",
        "ra": "23:24:48.0",
        "dec": "+61:35:36",
        "mag": 7.3,
        "size_deg": "0.217°",
        "width_deg": 0.21666666666666667,
        "height_deg": 0.21666666666666667,
        "size_src": "13'",
    },
    {
        "name": "M 53",
        "type": "Globular",
        "constellation": "Com",
        "ra": "13:12:55.0",
        "dec": "+18:10:09",
        "mag": 7.6,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "M 56",
        "type": "Globular",
        "constellation": "Lyr",
        "ra": "19:16:36.0",
        "dec": "+30:11:00",
        "mag": 8.3,
        "size_deg": "0.117°",
        "width_deg": 0.11666666666666667,
        "height_deg": 0.11666666666666667,
        "size_src": "7'",
    },
    {
        "name": "M 57",
        "aliases": ["Ring Nebula"],
        "type": "Planetary",
        "constellation": "Lyr",
        "ra": "18:53:35.1",
        "dec": "+33:01:45",
        "mag": 8.8,
        "size_deg": "0.023°×0.018°",
        "width_deg": 0.02333333333333333,
        "height_deg": 0.018333333333333333,
        "size_src": "1.4'×1.1'",
    },
    {
        "name": "M 58",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:37:44.0",
        "dec": "+11:49:00",
        "mag": 9.7,
        "size_deg": "0.098°×0.078°",
        "width_deg": 0.09833333333333334,
        "height_deg": 0.07833333333333334,
        "size_src": "5.9'×4.7'",
    },
    {
        "name": "M 59",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:42:02.0",
        "dec": "+11:39:00",
        "mag": 9.6,
        "size_deg": "0.090°×0.062°",
        "width_deg": 0.09000000000000001,
        "height_deg": 0.06166666666666667,
        "size_src": "5.4'×3.7'",
    },
    {
        "name": "M 60",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:43:40.0",
        "dec": "+11:33:00",
        "mag": 8.8,
        "size_deg": "0.127°×0.103°",
        "width_deg": 0.12666666666666665,
        "height_deg": 0.10333333333333333,
        "size_src": "7.6'×6.2'",
    },
    {
        "name": "M 61",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:21:55.0",
        "dec": "+04:28:25",
        "mag": 9.7,
        "size_deg": "0.108°×0.098°",
        "width_deg": 0.10833333333333334,
        "height_deg": 0.09833333333333334,
        "size_src": "6.5'×5.9'",
    },
    {
        "name": "M 63",
        "aliases": ["Sunflower Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:15:49.3",
        "dec": "+42:01:45",
        "mag": 8.6,
        "size_deg": "0.217°×0.117°",
        "width_deg": 0.21666666666666667,
        "height_deg": 0.11666666666666667,
        "size_src": "13'×7'",
    },
    {
        "name": "M 64",
        "aliases": ["Black Eye Galaxy"],
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:56:44.2",
        "dec": "+21:41:05",
        "mag": 8.5,
        "size_deg": "0.167°×0.083°",
        "width_deg": 0.16666666666666666,
        "height_deg": 0.08333333333333333,
        "size_src": "10'×5'",
    },
    {
        "name": "M 65",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "11:18:56.0",
        "dec": "+13:05:32",
        "mag": 9.3,
        "size_deg": "0.145°×0.042°",
        "width_deg": 0.145,
        "height_deg": 0.041666666666666664,
        "size_src": "8.7'×2.5'",
    },
    {
        "name": "M 66",
        "aliases": ["NGC 3627"],
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "11:20:15.0",
        "dec": "+12:59:30",
        "mag": 8.9,
        "size_deg": "0.152°×0.070°",
        "width_deg": 0.15166666666666667,
        "height_deg": 0.07,
        "size_src": "9.1'×4.2'",
    },
    {
        "name": "M 67",
        "type": "Open",
        "constellation": "Cnc",
        "ra": "08:50:24.0",
        "dec": "+11:49:00",
        "mag": 6.9,
        "size_deg": "0.500°",
        "width_deg": 0.5,
        "height_deg": 0.5,
        "size_src": "30'",
    },
    {
        "name": "M 68",
        "type": "Globular",
        "constellation": "Hya",
        "ra": "12:39:28.0",
        "dec": "-26:44:38",
        "mag": 7.3,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "M 71",
        "type": "Globular",
        "constellation": "Sge",
        "ra": "19:53:46.1",
        "dec": "+18:46:45",
        "mag": 8.4,
        "size_deg": "0.120°",
        "width_deg": 0.12000000000000001,
        "height_deg": 0.12000000000000001,
        "size_src": "7.2'",
    },
    {
        "name": "M 72",
        "type": "Globular",
        "constellation": "Aqr",
        "ra": "20:53:28.0",
        "dec": "-12:32:00",
        "mag": 9.3,
        "size_deg": "0.100°",
        "width_deg": 0.1,
        "height_deg": 0.1,
        "size_src": "6'",
    },
    {
        "name": "M 74",
        "type": "Galaxy",
        "constellation": "Psc",
        "ra": "01:36:41.7",
        "dec": "+15:47:01",
        "mag": 9.4,
        "size_deg": "0.170°×0.158°",
        "width_deg": 0.16999999999999998,
        "height_deg": 0.15833333333333333,
        "size_src": "10.2'×9.5'",
    },
    {
        "name": "M 75",
        "type": "Globular",
        "constellation": "Sgr",
        "ra": "20:06:05.0",
        "dec": "-21:55:00",
        "mag": 8.5,
        "size_deg": "0.113°",
        "width_deg": 0.11333333333333333,
        "height_deg": 0.11333333333333333,
        "size_src": "6.8'",
    },
    {
        "name": "M 76",
        "aliases": ["Little Dumbbell"],
        "type": "Planetary",
        "constellation": "Per",
        "ra": "01:42:19.0",
        "dec": "+51:34:00",
        "mag": 10.1,
        "size_deg": "0.045°×0.030°",
        "width_deg": 0.045000000000000005,
        "height_deg": 0.030000000000000002,
        "size_src": "2.7'×1.8'",
    },
    {
        "name": "M 77",
        "type": "Galaxy",
        "constellation": "Cet",
        "ra": "02:42:40.8",
        "dec": "-00:00:48",
        "mag": 8.9,
        "size_deg": "0.118°×0.100°",
        "width_deg": 0.11833333333333333,
        "height_deg": 0.1,
        "size_src": "7.1'×6.0'",
    },
    {
        "name": "M 78",
        "type": "Reflection",
        "constellation": "Ori",
        "ra": "05:46:46.0",
        "dec": "+00:03:00",
        "mag": 8.0,
        "size_deg": "0.133°×0.100°",
        "width_deg": 0.13333333333333333,
        "height_deg": 0.1,
        "size_src": "8'×6'",
    },
    {
        "name": "M 79",
        "type": "Globular",
        "constellation": "Lep",
        "ra": "05:24:10.0",
        "dec": "-24:33:00",
        "mag": 7.7,
        "size_deg": "0.160°",
        "width_deg": 0.16,
        "height_deg": 0.16,
        "size_src": "9.6'",
    },
    {
        "name": "M 80",
        "type": "Globular",
        "constellation": "Sco",
        "ra": "16:17:00.0",
        "dec": "-22:59:00",
        "mag": 7.3,
        "size_deg": "0.148°",
        "width_deg": 0.14833333333333334,
        "height_deg": 0.14833333333333334,
        "size_src": "8.9'",
    },
    {
        "name": "M 81",
        "aliases": ["Bode's Galaxy", "M82 Pair"],
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "09:55:33.2",
        "dec": "+69:04:00",
        "mag": 6.9,
        "size_deg": "0.450°×0.233°",
        "width_deg": 0.45,
        "height_deg": 0.23333333333333334,
        "size_src": "27'×14'",
    },
    {
        "name": "M 82",
        "aliases": ["Cigar Galaxy"],
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "09:55:52.7",
        "dec": "+69:40:46",
        "mag": 8.4,
        "size_deg": "0.183°×0.067°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.06666666666666667,
        "size_src": "11'×4'",
    },
    {
        "name": "M 83",
        "aliases": ["Southern Pinwheel Galaxy"],
        "type": "Galaxy",
        "constellation": "Hya",
        "ra": "13:37:00.0",
        "dec": "-29:51:56",
        "mag": 7.6,
        "size_deg": "0.217°×0.183°",
        "width_deg": 0.21666666666666667,
        "height_deg": 0.18333333333333332,
        "size_src": "13'×11'",
    },
    {
        "name": "M 84",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:25:03.0",
        "dec": "+12:53:13",
        "mag": 9.1,
        "size_deg": "0.108°×0.093°",
        "width_deg": 0.10833333333333334,
        "height_deg": 0.09333333333333332,
        "size_src": "6.5'×5.6'",
    },
    {
        "name": "M 85",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:25:24.0",
        "dec": "+18:11:26",
        "mag": 9.1,
        "size_deg": "0.118°×0.087°",
        "width_deg": 0.11833333333333333,
        "height_deg": 0.08666666666666667,
        "size_src": "7.1'×5.2'",
    },
    {
        "name": "M 86",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:26:12.0",
        "dec": "+12:57:00",
        "mag": 8.9,
        "size_deg": "0.148°×0.097°",
        "width_deg": 0.14833333333333334,
        "height_deg": 0.09666666666666666,
        "size_src": "8.9'×5.8'",
    },
    {
        "name": "M 87",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:30:49.4",
        "dec": "+12:23:28",
        "mag": 8.6,
        "size_deg": "0.138°×0.110°",
        "width_deg": 0.13833333333333334,
        "height_deg": 0.11,
        "size_src": "8.3'×6.6'",
    },
    {
        "name": "M 88",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:31:59.0",
        "dec": "+14:25:13",
        "mag": 9.6,
        "size_deg": "0.115°×0.062°",
        "width_deg": 0.115,
        "height_deg": 0.06166666666666667,
        "size_src": "6.9'×3.7'",
    },
    {
        "name": "M 89",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:35:39.0",
        "dec": "+12:33:23",
        "mag": 9.8,
        "size_deg": "0.085°×0.078°",
        "width_deg": 0.08499999999999999,
        "height_deg": 0.07833333333333334,
        "size_src": "5.1'×4.7'",
    },
    {
        "name": "M 90",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:36:50.0",
        "dec": "+13:09:46",
        "mag": 9.5,
        "size_deg": "0.158°×0.073°",
        "width_deg": 0.15833333333333333,
        "height_deg": 0.07333333333333333,
        "size_src": "9.5'×4.4'",
    },
    {
        "name": "M 91",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:35:27.0",
        "dec": "+14:29:46",
        "mag": 10.2,
        "size_deg": "0.090°×0.073°",
        "width_deg": 0.09000000000000001,
        "height_deg": 0.07333333333333333,
        "size_src": "5.4'×4.4'",
    },
    {
        "name": "M 92",
        "type": "Globular",
        "constellation": "Her",
        "ra": "17:17:07.4",
        "dec": "+43:08:12",
        "mag": 6.5,
        "size_deg": "0.233°",
        "width_deg": 0.23333333333333334,
        "height_deg": 0.23333333333333334,
        "size_src": "14'",
    },
    {
        "name": "M 93",
        "type": "Open",
        "constellation": "Pup",
        "ra": "07:44:30.0",
        "dec": "-23:52:00",
        "mag": 6.2,
        "size_deg": "0.367°",
        "width_deg": 0.36666666666666664,
        "height_deg": 0.36666666666666664,
        "size_src": "22'",
    },
    {
        "name": "M 94",
        "aliases": ["Croc's Eye Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:50:53.1",
        "dec": "+41:07:12",
        "mag": 8.2,
        "size_deg": "0.183°×0.150°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.15,
        "size_src": "11'×9'",
    },
    {
        "name": "M 95",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "10:43:57.7",
        "dec": "+11:42:14",
        "mag": 9.7,
        "size_deg": "0.123°×0.085°",
        "width_deg": 0.12333333333333334,
        "height_deg": 0.08499999999999999,
        "size_src": "7.4'×5.1'",
    },
    {
        "name": "M 96",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "10:46:45.7",
        "dec": "+11:49:12",
        "mag": 9.2,
        "size_deg": "0.130°×0.087°",
        "width_deg": 0.13,
        "height_deg": 0.08666666666666667,
        "size_src": "7.8'×5.2'",
    },
    {
        "name": "M 97",
        "aliases": ["Owl Nebula"],
        "type": "Planetary",
        "constellation": "UMa",
        "ra": "11:14:48.0",
        "dec": "+55:01:00",
        "mag": 9.9,
        "size_deg": "0.057°×0.055°",
        "width_deg": 0.056666666666666664,
        "height_deg": 0.055,
        "size_src": "3.4'×3.3'",
    },
    {
        "name": "M 98",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:13:48.0",
        "dec": "+14:54:01",
        "mag": 10.1,
        "size_deg": "0.158°×0.047°",
        "width_deg": 0.15833333333333333,
        "height_deg": 0.04666666666666666,
        "size_src": "9.5'×2.8'",
    },
    {
        "name": "M 99",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:18:50.0",
        "dec": "+14:25:00",
        "mag": 9.9,
        "size_deg": "0.090°×0.078°",
        "width_deg": 0.09000000000000001,
        "height_deg": 0.07833333333333334,
        "size_src": "5.4'×4.7'",
    },
    {
        "name": "M 100",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:22:54.0",
        "dec": "+15:49:21",
        "mag": 9.3,
        "size_deg": "0.123°×0.105°",
        "width_deg": 0.12333333333333334,
        "height_deg": 0.105,
        "size_src": "7.4'×6.3'",
    },
    {
        "name": "M 101",
        "aliases": ["Pinwheel Galaxy"],
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "14:03:12.6",
        "dec": "+54:20:57",
        "mag": 7.9,
        "size_deg": "0.467°×0.433°",
        "width_deg": 0.4666666666666667,
        "height_deg": 0.43333333333333335,
        "size_src": "28'×26'",
    },
    {
        "name": "M 102",
        "type": "Galaxy",
        "constellation": "Dra",
        "ra": "15:06:30.0",
        "dec": "+55:45:00",
        "mag": 9.9,
        "size_deg": "0.075°×0.017°",
        "width_deg": 0.075,
        "height_deg": 0.016666666666666666,
        "size_src": "4.5'×1.0'",
    },
    {
        "name": "M 103",
        "type": "Open",
        "constellation": "Cas",
        "ra": "01:33:23.0",
        "dec": "+60:39:00",
        "mag": 7.4,
        "size_deg": "0.100°",
        "width_deg": 0.1,
        "height_deg": 0.1,
        "size_src": "6'",
    },
    {
        "name": "M 104",
        "aliases": ["Sombrero Galaxy"],
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:39:59.4",
        "dec": "-11:37:23",
        "mag": 8.0,
        "size_deg": "0.150°×0.067°",
        "width_deg": 0.15,
        "height_deg": 0.06666666666666667,
        "size_src": "9'×4'",
    },
    {
        "name": "M 105",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "10:47:49.6",
        "dec": "+12:34:54",
        "mag": 9.3,
        "size_deg": "0.087°×0.080°",
        "width_deg": 0.08666666666666667,
        "height_deg": 0.08,
        "size_src": "5.2'×4.8'",
    },
    {
        "name": "M 106",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:18:57.5",
        "dec": "+47:18:14",
        "mag": 8.4,
        "size_deg": "0.317°×0.133°",
        "width_deg": 0.31666666666666665,
        "height_deg": 0.13333333333333333,
        "size_src": "19'×8'",
    },
    {
        "name": "M 107",
        "type": "Globular",
        "constellation": "Oph",
        "ra": "16:32:32.0",
        "dec": "-13:03:00",
        "mag": 7.9,
        "size_deg": "0.167°",
        "width_deg": 0.16666666666666666,
        "height_deg": 0.16666666666666666,
        "size_src": "10'",
    },
    {
        "name": "M 108",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "11:11:31.0",
        "dec": "+55:40:00",
        "mag": 10.0,
        "size_deg": "0.145°×0.037°",
        "width_deg": 0.145,
        "height_deg": 0.03666666666666667,
        "size_src": "8.7'×2.2'",
    },
    {
        "name": "M 109",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "11:57:36.0",
        "dec": "+53:23:00",
        "mag": 9.8,
        "size_deg": "0.127°×0.078°",
        "width_deg": 0.12666666666666665,
        "height_deg": 0.07833333333333334,
        "size_src": "7.6'×4.7'",
    },
    {
        "name": "NGC 40",
        "aliases": ["Bow-Tie Nebula"],
        "type": "Planetary",
        "constellation": "Cep",
        "ra": "00:13:01.0",
        "dec": "+72:31:19",
        "mag": 10.7,
        "size_deg": "0.010°",
        "width_deg": 0.01,
        "height_deg": 0.01,
        "size_src": "0.6'",
    },
    {
        "name": "NGC 281",
        "aliases": ["Pacman Nebula"],
        "type": "Emission",
        "constellation": "Cas",
        "ra": "00:52:59.0",
        "dec": "+56:37:19",
        "mag": 7.0,
        "size_deg": "0.583°×0.500°",
        "width_deg": 0.5833333333333334,
        "height_deg": 0.5,
        "size_src": "35'×30'",
    },
    {
        "name": "NGC 457",
        "aliases": ["Owl Cluster"],
        "type": "Open",
        "constellation": "Cas",
        "ra": "01:19:33.0",
        "dec": "+58:17:27",
        "mag": 6.4,
        "size_deg": "0.217°",
        "width_deg": 0.21666666666666667,
        "height_deg": 0.21666666666666667,
        "size_src": "13'",
    },
    {
        "name": "NGC 752",
        "type": "Open",
        "constellation": "And",
        "ra": "01:57:41.0",
        "dec": "+37:47:06",
        "mag": 5.7,
        "size_deg": "1.250°",
        "width_deg": 1.25,
        "height_deg": 1.25,
        "size_src": "75'",
    },
    {
        "name": "NGC 869",
        "aliases": ["Double Cluster"],
        "type": "Open",
        "constellation": "Per",
        "ra": "02:19:00.0",
        "dec": "+57:08:00",
        "mag": 4.3,
        "size_deg": "0.500°",
        "width_deg": 0.5,
        "height_deg": 0.5,
        "size_src": "30'",
    },
    {
        "name": "NGC 884",
        "aliases": ["Double Cluster"],
        "type": "Open",
        "constellation": "Per",
        "ra": "02:22:00.0",
        "dec": "+57:08:00",
        "mag": 4.4,
        "size_deg": "0.500°",
        "width_deg": 0.5,
        "height_deg": 0.5,
        "size_src": "30'",
    },
    {
        "name": "NGC 891",
        "type": "Galaxy",
        "constellation": "And",
        "ra": "02:22:33.4",
        "dec": "+42:20:57",
        "mag": 10.8,
        "size_deg": "0.225°×0.042°",
        "width_deg": 0.225,
        "height_deg": 0.041666666666666664,
        "size_src": "13.5'×2.5'",
    },
    {
        "name": "NGC 1333",
        "type": "Reflection",
        "constellation": "Per",
        "ra": "03:29:20.0",
        "dec": "+31:24:00",
        "mag": 5.6,
        "size_deg": "0.100°×0.050°",
        "width_deg": 0.1,
        "height_deg": 0.05,
        "size_src": "6'×3'",
    },
    {
        "name": "NGC 1491",
        "type": "Emission",
        "constellation": "Per",
        "ra": "04:03:15.0",
        "dec": "+51:18:54",
        "mag": 0,
        "size_deg": "0.250°×0.167°",
        "width_deg": 0.25,
        "height_deg": 0.16666666666666666,
        "size_src": "15'×10'",
    },
    {
        "name": "NGC 1499",
        "aliases": ["California Nebula Complex", "California Nebula"],
        "type": "Emission",
        "constellation": "Per",
        "ra": "04:03:00.0",
        "dec": "+36:25:00",
        "mag": 6.0,
        "size_deg": "2.417°×0.667°",
        "width_deg": 2.4166666666666665,
        "height_deg": 0.6666666666666666,
        "size_src": "145'×40'",
    },
    {
        "name": "NGC 1501",
        "aliases": ["Oyster Nebula"],
        "type": "Planetary",
        "constellation": "Cam",
        "ra": "04:06:59.0",
        "dec": "+60:55:15",
        "mag": 11.5,
        "size_deg": "0.013°",
        "width_deg": 0.013333333333333334,
        "height_deg": 0.013333333333333334,
        "size_src": "0.8'",
    },
    {
        "name": "NGC 1514",
        "aliases": ["Crystal Ball Nebula"],
        "type": "Planetary",
        "constellation": "Tau",
        "ra": "04:09:16.9",
        "dec": "+30:46:33",
        "mag": 10.0,
        "size_deg": "0.037°×0.033°",
        "width_deg": 0.03666666666666667,
        "height_deg": 0.03333333333333333,
        "size_src": "2.2'×2.0'",
    },
    {
        "name": "NGC 1788",
        "aliases": ["Foxface Nebula"],
        "type": "Reflection",
        "constellation": "Ori",
        "ra": "05:06:54.0",
        "dec": "-03:20:00",
        "mag": 10.0,
        "size_deg": "0.133°×0.083°",
        "width_deg": 0.13333333333333333,
        "height_deg": 0.08333333333333333,
        "size_src": "8'×5'",
    },
    {
        "name": "NGC 1977",
        "aliases": ["Running Man Nebula"],
        "type": "Reflection",
        "constellation": "Ori",
        "ra": "05:35:16.2",
        "dec": "-04:47:07",
        "mag": 7.0,
        "size_deg": "0.667°×0.417°",
        "width_deg": 0.6666666666666666,
        "height_deg": 0.4166666666666667,
        "size_src": "40'×25'",
    },
    {
        "name": "NGC 2022",
        "type": "Planetary",
        "constellation": "Ori",
        "ra": "05:42:06.2",
        "dec": "+09:05:11",
        "mag": 11.7,
        "size_deg": "0.013°",
        "width_deg": 0.013333333333333334,
        "height_deg": 0.013333333333333334,
        "size_src": "0.8'",
    },
    {
        "name": "NGC 2146",
        "type": "Galaxy",
        "constellation": "Cam",
        "ra": "06:18:37.7",
        "dec": "+78:21:25",
        "mag": 10.6,
        "size_deg": "0.100°×0.057°",
        "width_deg": 0.1,
        "height_deg": 0.056666666666666664,
        "size_src": "6.0'×3.4'",
    },
    {
        "name": "NGC 2174",
        "aliases": ["Monkey Head Nebula"],
        "type": "Emission",
        "constellation": "Ori",
        "ra": "06:09:24.0",
        "dec": "+20:39:00",
        "mag": 0,
        "size_deg": "0.667°×0.500°",
        "width_deg": 0.6666666666666666,
        "height_deg": 0.5,
        "size_src": "40'×30'",
    },
    {
        "name": "NGC 2261",
        "aliases": ["Hubble's Variable Nebula"],
        "type": "Reflection",
        "constellation": "Mon",
        "ra": "06:39:10.0",
        "dec": "+08:44:00",
        "mag": 9.0,
        "size_deg": "0.033°×0.017°",
        "width_deg": 0.03333333333333333,
        "height_deg": 0.016666666666666666,
        "size_src": "2'×1'",
    },
    {
        "name": "NGC 2392",
        "aliases": ["Eskimo Nebula"],
        "type": "Planetary",
        "constellation": "Gem",
        "ra": "07:29:10.8",
        "dec": "+20:54:42",
        "mag": 9.2,
        "size_deg": "0.013°",
        "width_deg": 0.013333333333333334,
        "height_deg": 0.013333333333333334,
        "size_src": "0.8'",
    },
    {
        "name": "NGC 2403",
        "type": "Galaxy",
        "constellation": "Cam",
        "ra": "07:36:51.0",
        "dec": "+65:36:10",
        "mag": 8.4,
        "size_deg": "0.365°×0.205°",
        "width_deg": 0.365,
        "height_deg": 0.20500000000000002,
        "size_src": "21.9'×12.3'",
    },
    {
        "name": "NGC 2440",
        "type": "Planetary",
        "constellation": "Pup",
        "ra": "07:41:55.4",
        "dec": "-18:12:31",
        "mag": 10.8,
        "size_deg": "0.018°×0.012°",
        "width_deg": 0.018333333333333333,
        "height_deg": 0.011666666666666665,
        "size_src": "1.1'×0.7'",
    },
    {
        "name": "NGC 2683",
        "aliases": ["UFO Galaxy"],
        "type": "Galaxy",
        "constellation": "Lyn",
        "ra": "08:52:41.3",
        "dec": "+33:25:19",
        "mag": 9.7,
        "size_deg": "0.155°×0.037°",
        "width_deg": 0.155,
        "height_deg": 0.03666666666666667,
        "size_src": "9.3'×2.2'",
    },
    {
        "name": "NGC 2685",
        "aliases": ["Helix Galaxy"],
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "08:55:34.7",
        "dec": "+58:44:03",
        "mag": 11.2,
        "size_deg": "0.072°×0.047°",
        "width_deg": 0.07166666666666667,
        "height_deg": 0.04666666666666666,
        "size_src": "4.3'×2.8'",
    },
    {
        "name": "NGC 2787",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "09:19:19.1",
        "dec": "+69:12:12",
        "mag": 10.6,
        "size_deg": "0.050°×0.035°",
        "width_deg": 0.05,
        "height_deg": 0.035,
        "size_src": "3.0'×2.1'",
    },
    {
        "name": "NGC 2841",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "09:22:02.6",
        "dec": "+50:58:35",
        "mag": 9.2,
        "size_deg": "0.135°×0.058°",
        "width_deg": 0.13499999999999998,
        "height_deg": 0.058333333333333334,
        "size_src": "8.1'×3.5'",
    },
    {
        "name": "NGC 2903",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "09:32:10.1",
        "dec": "+21:30:03",
        "mag": 8.9,
        "size_deg": "0.210°×0.100°",
        "width_deg": 0.21,
        "height_deg": 0.1,
        "size_src": "12.6'×6.0'",
    },
    {
        "name": "NGC 2976",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "09:47:15.4",
        "dec": "+67:55:00",
        "mag": 10.2,
        "size_deg": "0.098°×0.045°",
        "width_deg": 0.09833333333333334,
        "height_deg": 0.045000000000000005,
        "size_src": "5.9'×2.7'",
    },
    {
        "name": "NGC 3077",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "10:03:19.1",
        "dec": "+68:44:02",
        "mag": 10.6,
        "size_deg": "0.090°×0.075°",
        "width_deg": 0.09000000000000001,
        "height_deg": 0.075,
        "size_src": "5.4'×4.5'",
    },
    {
        "name": "NGC 3184",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "10:18:16.9",
        "dec": "+41:25:26",
        "mag": 9.8,
        "size_deg": "0.123°×0.115°",
        "width_deg": 0.12333333333333334,
        "height_deg": 0.115,
        "size_src": "7.4'×6.9'",
    },
    {
        "name": "NGC 3242",
        "aliases": ["Ghost of Jupiter Nebula"],
        "type": "Planetary",
        "constellation": "Hya",
        "ra": "10:24:46.1",
        "dec": "-18:38:33",
        "mag": 8.6,
        "size_deg": "0.017°×0.013°",
        "width_deg": 0.016666666666666666,
        "height_deg": 0.013333333333333334,
        "size_src": "1.0'×0.8'",
    },
    {
        "name": "NGC 3344",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "10:43:31.1",
        "dec": "+24:55:20",
        "mag": 9.9,
        "size_deg": "0.118°×0.108°",
        "width_deg": 0.11833333333333333,
        "height_deg": 0.10833333333333334,
        "size_src": "7.1'×6.5'",
    },
    {
        "name": "NGC 3432",
        "type": "Galaxy",
        "constellation": "LMi",
        "ra": "10:52:31.0",
        "dec": "+36:37:07",
        "mag": 10.5,
        "size_deg": "0.113°×0.028°",
        "width_deg": 0.11333333333333333,
        "height_deg": 0.028333333333333332,
        "size_src": "6.8'×1.7'",
    },
    {
        "name": "NGC 3521",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "11:05:48.6",
        "dec": "-00:02:09",
        "mag": 9.0,
        "size_deg": "0.183°×0.085°",
        "width_deg": 0.18333333333333332,
        "height_deg": 0.08499999999999999,
        "size_src": "11.0'×5.1'",
    },
    {
        "name": "NGC 3628",
        "type": "Galaxy",
        "constellation": "Leo",
        "ra": "11:20:17.0",
        "dec": "+13:35:23",
        "mag": 9.5,
        "size_deg": "0.233°×0.060°",
        "width_deg": 0.23333333333333334,
        "height_deg": 0.060000000000000005,
        "size_src": "14'×3.6'",
    },
    {
        "name": "NGC 3675",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "11:26:08.4",
        "dec": "+43:35:09",
        "mag": 10.3,
        "size_deg": "0.098°×0.062°",
        "width_deg": 0.09833333333333334,
        "height_deg": 0.06166666666666667,
        "size_src": "5.9'×3.7'",
    },
    {
        "name": "NGC 3718",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "11:32:34.9",
        "dec": "+53:04:04",
        "mag": 10.6,
        "size_deg": "0.143°×0.070°",
        "width_deg": 0.14333333333333334,
        "height_deg": 0.07,
        "size_src": "8.6'×4.2'",
    },
    {
        "name": "NGC 4088",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:05:34.2",
        "dec": "+50:32:21",
        "mag": 10.4,
        "size_deg": "0.097°×0.037°",
        "width_deg": 0.09666666666666666,
        "height_deg": 0.03666666666666667,
        "size_src": "5.8'×2.2'",
    },
    {
        "name": "NGC 4244",
        "aliases": ["Silver Needle Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:17:29.6",
        "dec": "+37:48:27",
        "mag": 10.4,
        "size_deg": "0.277°×0.045°",
        "width_deg": 0.27666666666666667,
        "height_deg": 0.045000000000000005,
        "size_src": "16.6'×2.7'",
    },
    {
        "name": "NGC 4449",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:28:11.0",
        "dec": "+44:05:40",
        "mag": 9.4,
        "size_deg": "0.103°×0.073°",
        "width_deg": 0.10333333333333333,
        "height_deg": 0.07333333333333333,
        "size_src": "6.2'×4.4'",
    },
    {
        "name": "NGC 4490",
        "aliases": ["Cocoon Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:30:36.0",
        "dec": "+41:38:39",
        "mag": 9.8,
        "size_deg": "0.105°×0.050°",
        "width_deg": 0.105,
        "height_deg": 0.05,
        "size_src": "6.3'×3.0'",
    },
    {
        "name": "NGC 4559",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:35:57.0",
        "dec": "+27:57:36",
        "mag": 10.0,
        "size_deg": "0.178°×0.073°",
        "width_deg": 0.17833333333333332,
        "height_deg": 0.07333333333333333,
        "size_src": "10.7'×4.4'",
    },
    {
        "name": "NGC 4565",
        "aliases": ["Needle Galaxy"],
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:36:20.8",
        "dec": "+25:59:15",
        "mag": 10.4,
        "size_deg": "0.265°×0.035°",
        "width_deg": 0.265,
        "height_deg": 0.035,
        "size_src": "15.9'×2.1'",
    },
    {
        "name": "NGC 4631",
        "aliases": ["Whale Galaxy"],
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:42:08.0",
        "dec": "+32:32:29",
        "mag": 9.8,
        "size_deg": "0.250°×0.050°",
        "width_deg": 0.25,
        "height_deg": 0.05,
        "size_src": "15'×3'",
    },
    {
        "name": "NGC 4725",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:50:26.6",
        "dec": "+25:30:03",
        "mag": 9.2,
        "size_deg": "0.178°×0.127°",
        "width_deg": 0.17833333333333332,
        "height_deg": 0.12666666666666665,
        "size_src": "10.7'×7.6'",
    },
    {
        "name": "NGC 5005",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:10:56.2",
        "dec": "+37:03:33",
        "mag": 10.6,
        "size_deg": "0.097°×0.050°",
        "width_deg": 0.09666666666666666,
        "height_deg": 0.05,
        "size_src": "5.8'×3.0'",
    },
    {
        "name": "NGC 5033",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:13:27.5",
        "dec": "+36:35:38",
        "mag": 10.0,
        "size_deg": "0.178°×0.083°",
        "width_deg": 0.17833333333333332,
        "height_deg": 0.08333333333333333,
        "size_src": "10.7'×5.0'",
    },
    {
        "name": "NGC 5371",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:55:39.8",
        "dec": "+40:27:39",
        "mag": 10.7,
        "size_deg": "0.070°×0.058°",
        "width_deg": 0.07,
        "height_deg": 0.058333333333333334,
        "size_src": "4.2'×3.5'",
    },
    {
        "name": "NGC 5907",
        "aliases": ["Splinter Galaxy"],
        "type": "Galaxy",
        "constellation": "Dra",
        "ra": "15:15:53.8",
        "dec": "+56:19:44",
        "mag": 10.4,
        "size_deg": "0.212°×0.023°",
        "width_deg": 0.21166666666666664,
        "height_deg": 0.02333333333333333,
        "size_src": "12.7'×1.4'",
    },
    {
        "name": "NGC 6015",
        "type": "Galaxy",
        "constellation": "Dra",
        "ra": "15:51:24.8",
        "dec": "+62:18:22",
        "mag": 11.2,
        "size_deg": "0.083°×0.037°",
        "width_deg": 0.08333333333333333,
        "height_deg": 0.03666666666666667,
        "size_src": "5.0'×2.2'",
    },
    {
        "name": "NGC 6210",
        "aliases": ["Turtle Nebula"],
        "type": "Planetary",
        "constellation": "Her",
        "ra": "16:44:29.5",
        "dec": "+23:47:59",
        "mag": 9.7,
        "size_deg": "0.007°",
        "width_deg": 0.006666666666666667,
        "height_deg": 0.006666666666666667,
        "size_src": "0.4'",
    },
    {
        "name": "NGC 6503",
        "type": "Galaxy",
        "constellation": "Dra",
        "ra": "17:49:26.4",
        "dec": "+70:08:40",
        "mag": 10.2,
        "size_deg": "0.118°×0.040°",
        "width_deg": 0.11833333333333333,
        "height_deg": 0.04,
        "size_src": "7.1'×2.4'",
    },
    {
        "name": "NGC 6543",
        "aliases": ["Cat's Eye Nebula"],
        "type": "Planetary",
        "constellation": "Dra",
        "ra": "17:58:32",
        "dec": "+66:38:00",
        "mag": 0,
        "size_deg": "0.009°×0.009°",
        "width_deg": 0.009166666666666667,
        "height_deg": 0.009166666666666667,
        "size_src": '33"',
    },
    {
        "name": "NGC 6781",
        "type": "Planetary",
        "constellation": "Aql",
        "ra": "19:18:28.0",
        "dec": "+06:32:20",
        "mag": 11.0,
        "size_deg": "0.030°",
        "width_deg": 0.03,
        "height_deg": 0.03,
        "size_src": "1.8'",
    },
    {
        "name": "NGC 6826",
        "aliases": ["Blinking Planetary Nebula"],
        "type": "Planetary",
        "constellation": "Cyg",
        "ra": "19:44:48",
        "dec": "+50:31:30",
        "mag": 0,
        "size_deg": "0.018°×0.017°",
        "width_deg": 0.018333333333333333,
        "height_deg": 0.016666666666666666,
        "size_src": "1.1'×1.0'",
    },
    {
        "name": "NGC 6888",
        "aliases": ["Crescent Nebula"],
        "type": "Emission",
        "constellation": "Cyg",
        "ra": "20:12:07.0",
        "dec": "+38:21:18",
        "mag": 7.4,
        "size_deg": "0.300°×0.200°",
        "width_deg": 0.3,
        "height_deg": 0.2,
        "size_src": "18'×12'",
    },
    {
        "name": "NGC 6946",
        "aliases": ["Fireworks Galaxy"],
        "type": "Galaxy",
        "constellation": "Cep",
        "ra": "20:34:52.3",
        "dec": "+60:09:14",
        "mag": 9.6,
        "size_deg": "0.192°×0.167°",
        "width_deg": 0.19166666666666668,
        "height_deg": 0.16666666666666666,
        "size_src": "11.5'×10.0'",
    },
    {
        "name": "NGC 7000",
        "aliases": ["North America Nebula"],
        "type": "Emission",
        "constellation": "Cyg",
        "ra": "20:58:54.0",
        "dec": "+44:19:00",
        "mag": 4.0,
        "size_deg": "2.000°×1.667°",
        "width_deg": 2.0,
        "height_deg": 1.6666666666666667,
        "size_src": "120'×100'",
    },
    {
        "name": "NGC 7008",
        "aliases": ["Fetus Nebula"],
        "type": "Planetary",
        "constellation": "Cyg",
        "ra": "21:00:33",
        "dec": "+54:32:29",
        "mag": 0,
        "size_deg": "0.024°×0.024°",
        "width_deg": 0.023833333333333335,
        "height_deg": 0.023833333333333335,
        "size_src": '86"',
    },
    {
        "name": "NGC 7023",
        "aliases": ["Iris Nebula"],
        "type": "Reflection",
        "constellation": "Cep",
        "ra": "21:01:36.0",
        "dec": "+68:10:10",
        "mag": 6.8,
        "size_deg": "0.300°×0.300°",
        "width_deg": 0.3,
        "height_deg": 0.3,
        "size_src": "18'×18'",
    },
    {
        "name": "NGC 7129",
        "aliases": ["Little Cocoon Nebula"],
        "type": "Reflection",
        "constellation": "Cep",
        "ra": "21:43:01.0",
        "dec": "+66:06:00",
        "mag": 10.0,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.08333333333333333,
        "height_deg": 0.06666666666666667,
        "size_src": "5'×4'",
    },
    {
        "name": "NGC 7331",
        "type": "Galaxy",
        "constellation": "Peg",
        "ra": "22:37:04.1",
        "dec": "+34:24:56",
        "mag": 9.4,
        "size_deg": "0.175°×0.062°",
        "width_deg": 0.175,
        "height_deg": 0.06166666666666667,
        "size_src": "10.5'×3.7'",
    },
    {
        "name": "NGC 7635",
        "aliases": ["Bubble Nebula"],
        "type": "Emission",
        "constellation": "Cas",
        "ra": "23:20:42.0",
        "dec": "+61:12:00",
        "mag": 8.5,
        "size_deg": "0.250°×0.250°",
        "width_deg": 0.25,
        "height_deg": 0.25,
        "size_src": "15′×15′",
    },
    {
        "name": "NGC 7662",
        "aliases": ["Blue Snowball Nebula"],
        "type": "Planetary",
        "constellation": "And",
        "ra": "23:25:54",
        "dec": "+42:32:06",
        "mag": 0,
        "size_deg": "0.037°×0.037°",
        "width_deg": 0.03666666666666667,
        "height_deg": 0.03666666666666667,
        "size_src": "2.2'",
    },
    {
        "name": "NGC 7789",
        "aliases": ["Caroline's Rose"],
        "type": "Open",
        "constellation": "Cas",
        "ra": "23:57:24.0",
        "dec": "+56:42:30",
        "mag": 6.7,
        "size_deg": "0.267°",
        "width_deg": 0.26666666666666666,
        "height_deg": 0.26666666666666666,
        "size_src": "16'",
    },
    {
        "name": "IC 10",
        "type": "Galaxy",
        "constellation": "Cas",
        "ra": "00:20:24.6",
        "dec": "+59:17:30",
        "mag": 10.4,
        "size_deg": "0.113°×0.098°",
        "width_deg": 0.11333333333333333,
        "height_deg": 0.09833333333333334,
        "size_src": "6.8'×5.9'",
    },
    {
        "name": "IC 59",
        "type": "Reflection",
        "constellation": "Cas",
        "ra": "00:56:59.0",
        "dec": "+61:06:00",
        "mag": 10.0,
        "size_deg": "0.167°×0.050°",
        "width_deg": 0.16666666666666666,
        "height_deg": 0.05,
        "size_src": "10'×3'",
    },
    {
        "name": "IC 342",
        "aliases": ["Hidden Galaxy"],
        "type": "Galaxy",
        "constellation": "Cam",
        "ra": "03:46:48.5",
        "dec": "+68:05:46",
        "mag": 8.4,
        "size_deg": "0.350°×0.317°",
        "width_deg": 0.35,
        "height_deg": 0.31666666666666665,
        "size_src": "21'×19'",
    },
    {
        "name": "IC 348",
        "type": "Reflection",
        "constellation": "Per",
        "ra": "03:44:34.0",
        "dec": "+32:09:45",
        "mag": 7.0,
        "size_deg": "0.333°",
        "width_deg": 0.3333333333333333,
        "height_deg": 0.3333333333333333,
        "size_src": "20'",
    },
    {
        "name": "IC 418",
        "aliases": ["Spirograph Nebula"],
        "type": "Planetary",
        "constellation": "Lep",
        "ra": "05:27:28.2",
        "dec": "-12:41:50",
        "mag": 9.6,
        "size_deg": "0.008°",
        "width_deg": 0.008333333333333333,
        "height_deg": 0.008333333333333333,
        "size_src": "0.5'",
    },
    {
        "name": "IC 443",
        "aliases": ["Jellyfish Nebula"],
        "type": "SNR",
        "constellation": "Gem",
        "ra": "06:17:00.0",
        "dec": "+22:45:00",
        "mag": 12.0,
        "size_deg": "0.833°×0.667°",
        "width_deg": 0.8333333333333334,
        "height_deg": 0.6666666666666666,
        "size_src": "50'×40'",
    },
    {
        "name": "IC 447",
        "type": "Reflection",
        "constellation": "Mon",
        "ra": "06:17:58.0",
        "dec": "+23:18:00",
        "mag": 8.0,
        "size_deg": "0.750°×0.333°",
        "width_deg": 0.75,
        "height_deg": 0.3333333333333333,
        "size_src": "45'×20'",
    },
    {
        "name": "IC 1396",
        "aliases": ["Elephant's Trunk Nebula"],
        "type": "Emission",
        "constellation": "Cep",
        "ra": "21:39:00.0",
        "dec": "+57:30:00",
        "mag": 0,
        "size_deg": "3.000°×3.000°",
        "width_deg": 3.0,
        "height_deg": 3.0,
        "size_src": "180'×180'",
    },
    {
        "name": "IC 1613",
        "type": "Galaxy",
        "constellation": "Cet",
        "ra": "01:04:47.8",
        "dec": "+02:07:04",
        "mag": 9.2,
        "size_deg": "0.270°×0.242°",
        "width_deg": 0.27,
        "height_deg": 0.24166666666666667,
        "size_src": "16.2'×14.5'",
    },
    {
        "name": "IC 1805",
        "aliases": ["Heart Nebula"],
        "type": "Emission",
        "constellation": "Cas",
        "ra": "02:33:22",
        "dec": "+61:26:36",
        "mag": 6.5,
        "size_deg": "2.500°×2.500°",
        "width_deg": 2.5,
        "height_deg": 2.5,
        "size_src": "150'×150'",
    },
    {
        "name": "IC 1848",
        "aliases": ["Soul Nebula"],
        "type": "Emission",
        "constellation": "Cas",
        "ra": "02:51:00.0",
        "dec": "+60:26:00",
        "mag": 6.5,
        "size_deg": "2.500°×1.250°",
        "width_deg": 2.5,
        "height_deg": 1.25,
        "size_src": "150'×75'",
    },
    {
        "name": "IC 2233",
        "type": "Galaxy",
        "constellation": "Lyn",
        "ra": "08:13:58.0",
        "dec": "+45:44:32",
        "mag": 12.0,
        "size_deg": "0.057°×0.007°",
        "width_deg": 0.056666666666666664,
        "height_deg": 0.006666666666666667,
        "size_src": "3.4'×0.4'",
    },
    {
        "name": "IC 3568",
        "aliases": ["Lemon Slice Nebula"],
        "type": "Planetary",
        "constellation": "Cam",
        "ra": "12:33:06.0",
        "dec": "+82:33:00",
        "mag": 10.6,
        "size_deg": "0.013°",
        "width_deg": 0.013333333333333334,
        "height_deg": 0.013333333333333334,
        "size_src": "0.8'",
    },
    {
        "name": "IC 4182",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "13:05:49.3",
        "dec": "+37:36:18",
        "mag": 10.8,
        "size_deg": "0.095°×0.078°",
        "width_deg": 0.095,
        "height_deg": 0.07833333333333334,
        "size_src": "5.7'×4.7'",
    },
    {
        "name": "IC 4592",
        "aliases": ["Blue Horsehead Nebula"],
        "type": "Reflection",
        "constellation": "Sco",
        "ra": "16:11:12.0",
        "dec": "-19:00:00",
        "mag": 9.0,
        "size_deg": "1.000°×0.500°",
        "width_deg": 1.0,
        "height_deg": 0.5,
        "size_src": "60'×30'",
    },
    {
        "name": "IC 4593",
        "type": "Planetary",
        "constellation": "Her",
        "ra": "16:11:44.5",
        "dec": "+12:04:17",
        "mag": 10.7,
        "size_deg": "0.028°×0.027°",
        "width_deg": 0.028333333333333332,
        "height_deg": 0.02666666666666667,
        "size_src": "1.7'×1.6'",
    },
    {
        "name": "IC 4603",
        "type": "Reflection",
        "constellation": "Oph",
        "ra": "16:25:18.0",
        "dec": "-24:23:12",
        "mag": 7.5,
        "size_deg": "0.667°×0.500°",
        "width_deg": 0.6666666666666666,
        "height_deg": 0.5,
        "size_src": "40'×30'",
    },
    {
        "name": "IC 4604",
        "aliases": ["Rho Ophiuchi"],
        "type": "Reflection",
        "constellation": "Oph",
        "ra": "16:25:36.0",
        "dec": "-23:26:48",
        "mag": 7.0,
        "size_deg": "2.000°×1.333°",
        "width_deg": 2.0,
        "height_deg": 1.3333333333333333,
        "size_src": "120'×80'",
    },
    {
        "name": "IC 4634",
        "type": "Planetary",
        "constellation": "Oph",
        "ra": "17:01:33.6",
        "dec": "-21:49:33",
        "mag": 11.1,
        "size_deg": "0.010°×0.007°",
        "width_deg": 0.01,
        "height_deg": 0.006666666666666667,
        "size_src": "0.6'×0.4'",
    },
    {
        "name": "IC 4665",
        "type": "Open",
        "constellation": "Oph",
        "ra": "17:46:18.0",
        "dec": "+05:43:00",
        "mag": 4.2,
        "size_deg": "1.167°",
        "width_deg": 1.1666666666666667,
        "height_deg": 1.1666666666666667,
        "size_src": "70'",
    },
    {
        "name": "IC 4756",
        "type": "Open",
        "constellation": "Ser",
        "ra": "18:39:00.0",
        "dec": "+05:27:00",
        "mag": 4.6,
        "size_deg": "1.333°",
        "width_deg": 1.3333333333333333,
        "height_deg": 1.3333333333333333,
        "size_src": "80'",
    },
    {
        "name": "IC 5070",
        "aliases": ["Pelican Nebula"],
        "type": "Emission",
        "constellation": "Cyg",
        "ra": "20:50:48.0",
        "dec": "+44:20:00",
        "mag": 8.0,
        "size_deg": "1.000°×0.833°",
        "width_deg": 1.0,
        "height_deg": 0.8333333333333334,
        "size_src": "60'×50'",
    },
    {
        "name": "IC 5146",
        "aliases": ["Cocoon Nebula"],
        "type": "Reflection",
        "constellation": "Cyg",
        "ra": "21:53:30.0",
        "dec": "+47:16:00",
        "mag": 7.2,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "IC 5217",
        "type": "Planetary",
        "constellation": "Lac",
        "ra": "22:23:55.0",
        "dec": "+50:58:00",
        "mag": 11.3,
        "size_deg": "0.005°",
        "width_deg": 0.005,
        "height_deg": 0.005,
        "size_src": "0.3'",
    },
    {
        "name": "Abell 21",
        "aliases": ["Medusa Nebula"],
        "type": "Planetary",
        "constellation": "Gem",
        "ra": "07:29:00.0",
        "dec": "+13:15:00",
        "mag": 10.3,
        "size_deg": "0.167°×0.133°",
        "width_deg": 0.16666666666666666,
        "height_deg": 0.13333333333333333,
        "size_src": "10'×8'",
    },
    {
        "name": "Abell 31",
        "aliases": ["Sh2-290"],
        "type": "Planetary",
        "constellation": "CMi",
        "ra": "08:54:40",
        "dec": "+08:53:00",
        "mag": 0,
        "size_deg": "0.283°×0.267°",
        "width_deg": 0.2833333333333333,
        "height_deg": 0.26666666666666666,
        "size_src": "17'×16'",
    },
    {
        "name": "Abell 33",
        "type": "Planetary",
        "constellation": "Hya",
        "ra": "09:40:00",
        "dec": "-02:53:12",
        "mag": 0,
        "size_deg": "0.075°×0.072°",
        "width_deg": 0.075,
        "height_deg": 0.07166666666666667,
        "size_src": "4.5'×4.3'",
    },
    {
        "name": "Abell 39",
        "type": "Planetary",
        "constellation": "Her",
        "ra": "16:27:33.0",
        "dec": "+27:54:33",
        "mag": 12.9,
        "size_deg": "0.048°",
        "width_deg": 0.04833333333333333,
        "height_deg": 0.04833333333333333,
        "size_src": "2.9'",
    },
    {
        "name": "Abell 426",
        "aliases": ["Perseus Cluster"],
        "type": "Galaxy Clus",
        "constellation": "Per",
        "ra": "03:19:00.0",
        "dec": "+41:30:00",
        "mag": 11.0,
        "size_deg": "1.333°×1.000°",
        "width_deg": 1.3333333333333333,
        "height_deg": 1.0,
        "size_src": "80'×60'",
    },
    {
        "name": "Abell 1367",
        "aliases": ["Leo Cluster"],
        "type": "Galaxy Clus",
        "constellation": "Leo",
        "ra": "11:44:00.0",
        "dec": "+19:45:00",
        "mag": 11.5,
        "size_deg": "1.000°×0.833°",
        "width_deg": 1.0,
        "height_deg": 0.8333333333333334,
        "size_src": "60'×50'",
    },
    {
        "name": "Abell 1656",
        "aliases": ["Coma Cluster"],
        "type": "Galaxy Clus",
        "constellation": "Com",
        "ra": "12:59:00.0",
        "dec": "+27:58:00",
        "mag": 10.5,
        "size_deg": "1.667°×1.000°",
        "width_deg": 1.6666666666666667,
        "height_deg": 1.0,
        "size_src": "100'×60'",
    },
    {
        "name": "Abell 2151",
        "aliases": ["Hercules Cluster"],
        "type": "Galaxy Clus",
        "constellation": "Her",
        "ra": "16:05:00.0",
        "dec": "+17:45:00",
        "mag": 12.0,
        "size_deg": "1.500°×1.000°",
        "width_deg": 1.5,
        "height_deg": 1.0,
        "size_src": "90'×60'",
    },
    {
        "name": "Abell 2218",
        "type": "Galaxy Clus",
        "constellation": "Dra",
        "ra": "16:35:54.0",
        "dec": "+66:12:00",
        "mag": 18.0,
        "size_deg": "0.100°",
        "width_deg": 0.1,
        "height_deg": 0.1,
        "size_src": "6'",
    },
    {
        "name": "Barnard 33",
        "type": "Dark",
        "constellation": "Ori",
        "ra": "05:40:59.0",
        "dec": "-02:27:30",
        "mag": 0,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.083,
        "height_deg": 0.0667,
        "size_src": "5'×4'",
    },
    {
        "name": "Barnard 39",
        "type": "Dark",
        "constellation": "Ori",
        "ra": "05:33:00.0",
        "dec": "-04:55:00",
        "mag": 0,
        "size_deg": "0.083°",
        "width_deg": 0.083,
        "height_deg": 0.083,
        "size_src": "5'",
    },
    {
        "name": "Barnard 59",
        "type": "Dark",
        "constellation": "Oph",
        "ra": "17:11:00.0",
        "dec": "-27:25:00",
        "mag": 0,
        "size_deg": "0.250°",
        "width_deg": 0.25,
        "height_deg": 0.25,
        "size_src": "15'",
    },
    {
        "name": "Barnard 68",
        "type": "Dark",
        "constellation": "Oph",
        "ra": "17:22:38.0",
        "dec": "-23:49:00",
        "mag": 0,
        "size_deg": "0.083°",
        "width_deg": 0.083,
        "height_deg": 0.083,
        "size_src": "5'",
    },
    {
        "name": "Barnard 72",
        "type": "Dark",
        "constellation": "Oph",
        "ra": "17:23:00.0",
        "dec": "-23:38:00",
        "mag": 0,
        "size_deg": "0.500°×0.100°",
        "width_deg": 0.5,
        "height_deg": 0.1,
        "size_src": "30'×6'",
    },
    {
        "name": "Barnard 77",
        "type": "Dark",
        "constellation": "Oph",
        "ra": "17:25:00.0",
        "dec": "-25:00:00",
        "mag": 0,
        "size_deg": "0.333°",
        "width_deg": 0.333,
        "height_deg": 0.333,
        "size_src": "20'",
    },
    {
        "name": "Barnard 78",
        "type": "Dark",
        "constellation": "Oph",
        "ra": "17:25:00.0",
        "dec": "-23:45:00",
        "mag": 0,
        "size_deg": "0.500°",
        "width_deg": 0.5,
        "height_deg": 0.5,
        "size_src": "30'",
    },
    {
        "name": "Barnard 86",
        "type": "Dark",
        "constellation": "Sgr",
        "ra": "18:03:36.0",
        "dec": "-27:16:00",
        "mag": 0,
        "size_deg": "0.083°",
        "width_deg": 0.083,
        "height_deg": 0.083,
        "size_src": "5'",
    },
    {
        "name": "Barnard 92",
        "type": "Dark",
        "constellation": "Sgr",
        "ra": "18:16:00.0",
        "dec": "-18:30:00",
        "mag": 0,
        "size_deg": "0.167°",
        "width_deg": 0.167,
        "height_deg": 0.167,
        "size_src": "10'",
    },
    {
        "name": "Barnard 93",
        "type": "Dark",
        "constellation": "Sgr",
        "ra": "18:16:30.0",
        "dec": "-18:25:00",
        "mag": 0,
        "size_deg": "0.167°",
        "width_deg": 0.167,
        "height_deg": 0.167,
        "size_src": "10'",
    },
    {
        "name": "Barnard 142",
        "type": "Dark",
        "constellation": "Aql",
        "ra": "19:40:00.0",
        "dec": "+10:20:00",
        "mag": 0,
        "size_deg": "1.000°×0.500°",
        "width_deg": 1.0,
        "height_deg": 0.5,
        "size_src": "60'×30'",
    },
    {
        "name": "Barnard 143",
        "type": "Dark",
        "constellation": "Aql",
        "ra": "19:40:30.0",
        "dec": "+10:00:00",
        "mag": 0,
        "size_deg": "0.667°×0.333°",
        "width_deg": 0.667,
        "height_deg": 0.333,
        "size_src": "40'×20'",
    },
    {
        "name": "Barnard 150",
        "aliases": ["Seahorse Nebula"],
        "type": "Dark",
        "constellation": "Cep",
        "ra": "21:30:00.0",
        "dec": "+59:00:00",
        "mag": 0,
        "size_deg": "1.000°×0.333°",
        "width_deg": 1.0,
        "height_deg": 0.3333333333333333,
        "size_src": "60'×20'",
    },
    {
        "name": "Barnard 168",
        "type": "Dark",
        "constellation": "Cyg",
        "ra": "21:00:00.0",
        "dec": "+47:00:00",
        "mag": 0,
        "size_deg": "1.000°×0.083°",
        "width_deg": 1.0,
        "height_deg": 0.083,
        "size_src": "60'×5'",
    },
    {
        "name": "Barnard 361",
        "type": "Dark",
        "constellation": "Cyg",
        "ra": "21:18:00.0",
        "dec": "+48:00:00",
        "mag": 0,
        "size_deg": "0.200°",
        "width_deg": 0.2,
        "height_deg": 0.2,
        "size_src": "12'",
    },
    {
        "name": "LDN 1089",
        "type": "Dark",
        "constellation": "Cep",
        "ra": "22:20:00.0",
        "dec": "+62:00:00",
        "mag": 0,
        "size_deg": "1.000°",
        "width_deg": 1.0,
        "height_deg": 1.0,
        "size_src": "60'",
    },
    {
        "name": "LDN 1147",
        "type": "Dark",
        "constellation": "Cep",
        "ra": "20:40:00.0",
        "dec": "+67:50:00",
        "mag": 0,
        "size_deg": "0.833°×0.667°",
        "width_deg": 0.833,
        "height_deg": 0.667,
        "size_src": "50'×40'",
    },
    {
        "name": "LDN 1158",
        "type": "Dark",
        "constellation": "Cep",
        "ra": "20:43:00.0",
        "dec": "+67:20:00",
        "mag": 0,
        "size_deg": "0.500°×0.333°",
        "width_deg": 0.5,
        "height_deg": 0.333,
        "size_src": "30'×20'",
    },
    {
        "name": "LDN 1235",
        "aliases": ["Dark Shark Nebula"],
        "type": "Dark",
        "constellation": "Cep",
        "ra": "22:13:00.0",
        "dec": "+75:15:00",
        "mag": 10.0,
        "size_deg": "2.500°×0.833°",
        "width_deg": 2.5,
        "height_deg": 0.8333333333333334,
        "size_src": "150'×50'",
    },
    {
        "name": "LDN 1622",
        "aliases": ["Boogeyman Nebula"],
        "type": "Dark",
        "constellation": "Ori",
        "ra": "05:54:20.0",
        "dec": "+01:45:00",
        "mag": 10.0,
        "size_deg": "1.000°×0.500°",
        "width_deg": 1.0,
        "height_deg": 0.5,
        "size_src": "60'×30'",
    },
    {
        "name": "Sh2-155",
        "aliases": ["Cave Nebula"],
        "type": "Emission",
        "constellation": "Cep",
        "ra": "22:35:00.0",
        "dec": "+62:30:00",
        "mag": 0,
        "size_deg": "1.000°×0.833°",
        "width_deg": 1.0,
        "height_deg": 0.8333333333333334,
        "size_src": "60'×50'",
    },
    {
        "name": "Sh2-240",
        "aliases": ["Spaghetti Nebula"],
        "type": "SNR",
        "constellation": "Tau",
        "ra": "05:40:00.0",
        "dec": "+28:00:00",
        "mag": 0,
        "size_deg": "3.000°×2.000°",
        "width_deg": 3.0,
        "height_deg": 2.0,
        "size_src": "180'×120'",
    },
    {
        "name": "vdB 141",
        "aliases": ["Ghost Nebula"],
        "type": "Reflection",
        "constellation": "Cep",
        "ra": "21:16:24.0",
        "dec": "+68:09:00",
        "mag": 0,
        "size_deg": "0.250°×0.200°",
        "width_deg": 0.25,
        "height_deg": 0.2,
        "size_src": "15'×12'",
    },
    {
        "name": "vdB 152",
        "aliases": ["Ced 201"],
        "type": "Reflection",
        "constellation": "Cep",
        "ra": "22:13:27.0",
        "dec": "+69:14:00",
        "mag": 0,
        "size_deg": "0.300°×0.100°",
        "width_deg": 0.3,
        "height_deg": 0.1,
        "size_src": "18'×6'",
    },
    {
        "name": "Hickson 44",
        "type": "GalaxyGrp",
        "constellation": "Leo",
        "ra": "10:18:00.0",
        "dec": "+21:48:00",
        "mag": 12.0,
        "size_deg": "0.267°×0.167°",
        "width_deg": 0.26666666666666666,
        "height_deg": 0.16666666666666666,
        "size_src": "16'×10'",
    },
    {
        "name": "Hickson 56",
        "type": "GalaxyGrp",
        "constellation": "UMa",
        "ra": "11:32:46.9",
        "dec": "+52:56:17",
        "mag": 14.0,
        "size_deg": "0.017°×0.013°",
        "width_deg": 0.016666666666666666,
        "height_deg": 0.013333333333333334,
        "size_src": "1.0'×0.8'",
    },
    {
        "name": "Hickson 68",
        "type": "GalaxyGrp",
        "constellation": "CVn",
        "ra": "13:53:00.0",
        "dec": "+40:20:00",
        "mag": 11.0,
        "size_deg": "0.283°×0.200°",
        "width_deg": 0.2833333333333333,
        "height_deg": 0.2,
        "size_src": "17'×12'",
    },
    {
        "name": "Jones 1",
        "type": "Planetary",
        "constellation": "Peg",
        "ra": "23:35:53.0",
        "dec": "+30:29:36",
        "mag": 12.0,
        "size_deg": "0.090°",
        "width_deg": 0.09,
        "height_deg": 0.09,
        "size_src": "5.4'",
    },
    {
        "name": "Stock 2",
        "aliases": ["Muscleman Cluster"],
        "type": "Open",
        "constellation": "Cas",
        "ra": "02:15:00.0",
        "dec": "+59:16:00",
        "mag": 4.4,
        "size_deg": "1.000°",
        "width_deg": 1.0,
        "height_deg": 1.0,
        "size_src": "60'",
    },
    {
        "name": "Copeland's Septet",
        "type": "GalaxyGrp",
        "constellation": "Leo",
        "ra": "11:49:00.0",
        "dec": "+21:50:00",
        "mag": 13.0,
        "size_deg": "0.067°×0.050°",
        "width_deg": 0.06666666666666667,
        "height_deg": 0.05,
        "size_src": "4'×3'",
    },
    {
        "name": "Deer Lick Group",
        "type": "GalaxyGrp",
        "constellation": "Peg",
        "ra": "22:37:04",
        "dec": "+34:25:00",
        "mag": 0,
        "size_deg": "1.060°×0.643°",
        "width_deg": 1.0599999999999998,
        "height_deg": 0.6433333333333333,
        "size_src": "63.6'×38.6'",
    },
    {
        "name": "IC 1396A",
        "type": "Dark",
        "constellation": "Cep",
        "ra": "21:36:35.0",
        "dec": "+57:30:00",
        "mag": 0,
        "size_deg": "0.333°×0.250°",
        "width_deg": 0.333,
        "height_deg": 0.25,
        "size_src": "20'×15'",
    },
    {
        "name": "MBM 54",
        "type": "Reflection",
        "constellation": "Dra",
        "ra": "15:00:00.0",
        "dec": "+60:00:00",
        "mag": 0,
        "size_deg": "10.000°×6.667°",
        "width_deg": 10.0,
        "height_deg": 6.666666666666667,
        "size_src": "600'×400'",
    },
    {
        "name": "Jones-Emberson 1",
        "type": "Planetary",
        "constellation": "Lyn",
        "ra": "07:57:51.0",
        "dec": "+53:25:18",
        "mag": 12.0,
        "size_deg": "0.120°",
        "width_deg": 0.12000000000000001,
        "height_deg": 0.12000000000000001,
        "size_src": "7.2'",
    },
    {
        "name": "Leo Triplet",
        "type": "GalaxyGrp",
        "constellation": "Leo",
        "ra": "11:19:55",
        "dec": "+13:25:15",
        "mag": 0,
        "size_deg": "0.677°×0.846°",
        "width_deg": 0.6768333333333333,
        "height_deg": 0.846,
        "size_src": "40.61'×50.76'",
    },
    {
        "name": "MBM 12 Polaris Flare",
        "type": "Reflection",
        "constellation": "UMi",
        "ra": "03:46:00.0",
        "dec": "+30:00:00",
        "mag": 0,
        "size_deg": "5.000°×3.333°",
        "width_deg": 5.0,
        "height_deg": 3.3333333333333335,
        "size_src": "300'×200'",
    },
    {
        "name": "Markarian's Chain",
        "type": "GalaxyGrp",
        "constellation": "Vir",
        "ra": "12:27:45.0",
        "dec": "+13:10:00",
        "mag": 9.0,
        "size_deg": "2.000°×0.333°",
        "width_deg": 2.0,
        "height_deg": 0.3333333333333333,
        "size_src": "120'×20'",
    },
    {
        "name": "NGC 2371-72",
        "type": "Planetary",
        "constellation": "Gem",
        "ra": "07:25:34.0",
        "dec": "+29:29:18",
        "mag": 11.2,
        "size_deg": "0.028°×0.023°",
        "width_deg": 0.028333333333333332,
        "height_deg": 0.02333333333333333,
        "size_src": "1.7'×1.4'",
    },
    {
        "name": "Rosette Nebula Complex",
        "type": "Emission",
        "constellation": "Mon",
        "ra": "06:33:00.0",
        "dec": "+04:59:00",
        "mag": 6.0,
        "size_deg": "1.500°×1.167°",
        "width_deg": 1.5,
        "height_deg": 1.1666666666666667,
        "size_src": "90'×70'",
    },
    {
        "name": "Sh 2-216",
        "type": "Planetary",
        "constellation": "Aur",
        "ra": "04:45:00",
        "dec": "+46:49:00",
        "mag": 0,
        "size_deg": "1.667°×1.667°",
        "width_deg": 1.6666666666666667,
        "height_deg": 1.6666666666666667,
        "size_src": "100'",
    },
    {
        "name": "Stephan's Quintet",
        "type": "GalaxyGrp",
        "constellation": "Peg",
        "ra": "22:36:03.0",
        "dec": "+33:57:57",
        "mag": 13.0,
        "size_deg": "0.067°×0.050°",
        "width_deg": 0.06666666666666667,
        "height_deg": 0.05,
        "size_src": "4'×3'",
    },
    {
        "name": "Veil Nebula Complex",
        "type": "SNR",
        "constellation": "Cyg",
        "ra": "20:45:38.0",
        "dec": "+30:42:30",
        "mag": 7.0,
        "size_deg": "3.000°",
        "width_deg": 3.0,
        "height_deg": 3.0,
        "size_src": "3°",
    },
    {
        "name": "Virgo Cluster",
        "type": "Galaxy Clus",
        "constellation": "Vir",
        "ra": "12:27:00.0",
        "dec": "+12:43:00",
        "mag": 8.4,
        "size_deg": "8.000°",
        "width_deg": 8.0,
        "height_deg": 8.0,
        "size_src": "480'",
    },
    {
        "name": "NGC 4036",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:01:26.9",
        "dec": "+61:53:44",
        "mag": 10.7,
        "size_deg": "0.050°×0.043°",
        "width_deg": 0.05,
        "height_deg": 0.043,
        "size_src": "3.0'×2.6'",
    },
    {
        "name": "NGC 4041",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:02:12.2",
        "dec": "+62:08:14",
        "mag": 11.2,
        "size_deg": "0.058°×0.042°",
        "width_deg": 0.058,
        "height_deg": 0.042,
        "size_src": "3.5'×2.5'",
    },
    {
        "name": "NGC 4051",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:03:09.6",
        "dec": "+44:31:53",
        "mag": 10.1,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.083,
        "height_deg": 0.067,
        "size_src": "5.0'×4.0'",
    },
    {
        "name": "NGC 4085",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:05:23.0",
        "dec": "+50:21:43",
        "mag": 11.2,
        "size_deg": "0.042°×0.017°",
        "width_deg": 0.042,
        "height_deg": 0.017,
        "size_src": "2.5'×1.0'",
    },
    {
        "name": "NGC 4100",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:06:01.1",
        "dec": "+49:34:57",
        "mag": 10.9,
        "size_deg": "0.067°×0.042°",
        "width_deg": 0.067,
        "height_deg": 0.042,
        "size_src": "4.0'×2.5'",
    },
    {
        "name": "NGC 4216",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:15:54.4",
        "dec": "+13:08:58",
        "mag": 10.0,
        "size_deg": "0.133°×0.033°",
        "width_deg": 0.133,
        "height_deg": 0.033,
        "size_src": "8.0'×2.0'",
    },
    {
        "name": "NGC 4217",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "12:15:50.9",
        "dec": "+47:05:30",
        "mag": 11.0,
        "size_deg": "0.083°×0.017°",
        "width_deg": 0.083,
        "height_deg": 0.017,
        "size_src": "5.0'×1.0'",
    },
    {
        "name": "NGC 4245",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:17:36.8",
        "dec": "+29:36:28",
        "mag": 11.4,
        "size_deg": "0.050°×0.033°",
        "width_deg": 0.05,
        "height_deg": 0.033,
        "size_src": "3.0'×2.0'",
    },
    {
        "name": "NGC 4274",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:19:50.6",
        "dec": "+29:36:51",
        "mag": 10.8,
        "size_deg": "0.100°×0.067°",
        "width_deg": 0.1,
        "height_deg": 0.067,
        "size_src": "6.0'×4.0'",
    },
    {
        "name": "NGC 4293",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:21:12.8",
        "dec": "+18:22:57",
        "mag": 10.9,
        "size_deg": "0.083°×0.050°",
        "width_deg": 0.083,
        "height_deg": 0.05,
        "size_src": "5.0'×3.0'",
    },
    {
        "name": "NGC 4314",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:22:31.9",
        "dec": "+29:53:43",
        "mag": 10.6,
        "size_deg": "0.067°×0.050°",
        "width_deg": 0.067,
        "height_deg": 0.05,
        "size_src": "4.0'×3.0'",
    },
    {
        "name": "NGC 4395",
        "type": "Galaxy",
        "constellation": "CVn",
        "ra": "12:25:48.9",
        "dec": "+33:32:48",
        "mag": 10.6,
        "size_deg": "0.217°×0.167°",
        "width_deg": 0.217,
        "height_deg": 0.167,
        "size_src": "13.0'×10.0'",
    },
    {
        "name": "NGC 4450",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:28:29.6",
        "dec": "+17:05:06",
        "mag": 10.9,
        "size_deg": "0.083°×0.050°",
        "width_deg": 0.083,
        "height_deg": 0.05,
        "size_src": "5.0'×3.0'",
    },
    {
        "name": "NGC 4494",
        "type": "Galaxy",
        "constellation": "Com",
        "ra": "12:31:24.0",
        "dec": "+25:46:30",
        "mag": 10.6,
        "size_deg": "0.067°×0.058°",
        "width_deg": 0.067,
        "height_deg": 0.058,
        "size_src": "4.0'×3.5'",
    },
    {
        "name": "NGC 4527",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:34:08.5",
        "dec": "+02:39:13",
        "mag": 10.4,
        "size_deg": "0.117°×0.050°",
        "width_deg": 0.117,
        "height_deg": 0.05,
        "size_src": "7.0'×3.0'",
    },
    {
        "name": "NGC 4535",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:34:20.3",
        "dec": "+08:11:52",
        "mag": 10.0,
        "size_deg": "0.117°×0.100°",
        "width_deg": 0.117,
        "height_deg": 0.1,
        "size_src": "7.0'×6.0'",
    },
    {
        "name": "NGC 4536",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:34:27.1",
        "dec": "+02:11:17",
        "mag": 10.6,
        "size_deg": "0.117°×0.083°",
        "width_deg": 0.117,
        "height_deg": 0.083,
        "size_src": "7.0'×5.0'",
    },
    {
        "name": "NGC 4548",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:35:26.4",
        "dec": "+14:29:46",
        "mag": 10.8,
        "size_deg": "0.083°×0.058°",
        "width_deg": 0.083,
        "height_deg": 0.058,
        "size_src": "5.0'×3.5'",
    },
    {
        "name": "NGC 4569",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:36:49.8",
        "dec": "+13:09:46",
        "mag": 9.8,
        "size_deg": "0.167°×0.083°",
        "width_deg": 0.167,
        "height_deg": 0.083,
        "size_src": "10.0'×5.0'",
    },
    {
        "name": "NGC 4579",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:37:43.5",
        "dec": "+11:49:05",
        "mag": 10.5,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.083,
        "height_deg": 0.067,
        "size_src": "5.0'×4.0'",
    },
    {
        "name": "NGC 4639",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:42:52.4",
        "dec": "+13:15:26",
        "mag": 11.0,
        "size_deg": "0.050°×0.033°",
        "width_deg": 0.05,
        "height_deg": 0.033,
        "size_src": "3.0'×2.0'",
    },
    {
        "name": "NGC 4698",
        "type": "Galaxy",
        "constellation": "Vir",
        "ra": "12:48:22.9",
        "dec": "+08:29:15",
        "mag": 10.5,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.083,
        "height_deg": 0.067,
        "size_src": "5.0'×4.0'",
    },
    {
        "name": "NGC 5248",
        "type": "Galaxy",
        "constellation": "Boo",
        "ra": "13:37:32.0",
        "dec": "+08:53:06",
        "mag": 10.4,
        "size_deg": "0.100°×0.083°",
        "width_deg": 0.1,
        "height_deg": 0.083,
        "size_src": "6.0'×5.0'",
    },
    {
        "name": "NGC 5585",
        "type": "Galaxy",
        "constellation": "UMa",
        "ra": "14:19:48.2",
        "dec": "+56:43:45",
        "mag": 10.9,
        "size_deg": "0.083°×0.067°",
        "width_deg": 0.083,
        "height_deg": 0.067,
        "size_src": "5.0'×4.0'",
    },
]


def _fmt(x, default="—"):
    return default if x is None else str(x)


def _fmt_mag(m):
    return "—" if m is None else f"{m:.1f}"


def _fmt_size_deg(r):
    s = r.get("size_deg")
    if s:
        return s
    w, h = r.get("width_deg"), r.get("height_deg")
    if w is None or h is None:
        return "—"
    return f"{w:.3f}°×{h:.3f}°"


def size_arcmin(r):
    w, h = r.get("width_deg"), r.get("height_deg")
    if w is None or h is None:
        return "—"
    return f"{w*60:.1f}'×{h*60:.1f}'"


def print_catalog_rows(rows):
    cols = [
        ("Name", 30),
        ("Type", 13),
        ("Const", 5),
        ("RA", 12),
        ("Dec", 12),
        ("Mag", 5),
        ("Size (deg)", 18),
        ("Size Src", 10),
        ("Wdeg", 8),
        ("Hdeg", 8),
    ]
    header = " ".join(t.ljust(w) for t, w in cols)
    line = "-" * (sum(w for _, w in cols) + len(cols) - 1)
    print(header)
    print(line)
    for r in rows:
        print(
            " ".join(
                [
                    _fmt(r.get("name")).ljust(36),
                    _fmt(r.get("type")).ljust(13),
                    _fmt(r.get("constellation")).ljust(5),
                    _fmt(r.get("ra")).ljust(12),
                    _fmt(r.get("dec")).ljust(12),
                    _fmt_mag(r.get("mag")).rjust(5),
                    _fmt_size_deg(r).ljust(18),
                    _fmt(r.get("size_src")).ljust(10),
                    _fmt(r.get("width_deg")).ljust(8),
                    _fmt(r.get("height_deg")).ljust(8),
                ]
            )
        )


def _dedupe(
    rows: Iterable[Tuple[str, str, str, str, str]],
) -> List[Tuple[str, str, str, str, str]]:
    def norm(n: str) -> str:
        return "".join(c for c in n.lower() if c.isalnum() or c.isspace()).strip()

    seen: Dict[str, Tuple[str, str, str, str, str]] = {}
    for r in rows:
        k = norm(r[0])
        if k not in seen:
            seen[k] = r
    return list(seen.values())


def _site_visible(
    rows: Iterable[Tuple[str, str, str, str, str]],
) -> List[Tuple[str, str, str, str, str]]:
    """
    Keep catalog entries that can rise above the local horizon.
    Also applies per-object coordinate fixes (without deleting rows).
    """
    PATCH: Dict[str, Tuple[str, str]] = {
        "IC 5229": ("22:34:50.0", "-61:22:53"),
    }

    out: List[Tuple[str, str, str, str, str]] = []
    for name, typ, const, ra_hms, dec_dms in rows:
        if name in PATCH:
            ra_hms, dec_dms = PATCH[name]
        try:
            dec = Angle(dec_dms + " degrees").degree
            h_max = 90.0 - abs(LAT - dec)
            if h_max > 0.0:
                out.append((name, typ, const, ra_hms, dec_dms))
        except Exception:
            out.append((name, typ, const, ra_hms, dec_dms))
    return out


def attach_meta(rows, meta):
    out = []
    for name, typ, const, ra_hms, dec_dms in rows:
        m = meta.get(name)
        if m:
            out.append(
                (
                    name,
                    typ,
                    const,
                    ra_hms,
                    dec_dms,
                    m.get("mag"),
                    m.get("size"),
                    m.get("size_src"),
                    m.get("width_deg"),
                    m.get("height_deg"),
                )
            )
        else:
            out.append((name, typ, const, ra_hms, dec_dms))
    return out


RAW_CAT = [
    (r["name"], r["type"], r["constellation"], r["ra"], r["dec"]) for r in CATALOG
]

META = {
    r["name"]: {
        "mag": r.get("mag"),
        "size": (
            r.get("size_deg")
            if r.get("size_deg")
            else (
                f"{r.get('width_deg'):.3f}°×{r.get('height_deg'):.3f}°"
                if (r.get("width_deg") is not None and r.get("height_deg") is not None)
                else None
            )
        ),
        "size_src": r.get("size_src"),
        "width_deg": r.get("width_deg"),
        "height_deg": r.get("height_deg"),
    }
    for r in CATALOG
}

CAT = attach_meta(_site_visible(_dedupe(RAW_CAT)), META)


def local_noon(dt_local: datetime) -> datetime:
    return dt_local.replace(hour=12, minute=0, second=0, microsecond=0)


def night_window(
    anchor_local_noon: datetime, tz: ZoneInfo, loc: EarthLocation, step_min: int = 2
) -> Optional[Tuple[datetime, datetime]]:
    """
    Return the SINGLE longest astronomical-darkness block for the *night that spans*
    anchor_local_noon → anchor_local_noon + 24h (i.e., evening of that calendar day to next morning).
    """
    start_local = anchor_local_noon
    end_local = start_local + timedelta(days=1)

    secs = np.arange(
        int(start_local.astimezone(timezone.utc).timestamp()),
        int(end_local.astimezone(timezone.utc).timestamp()),
        step_min * 60,
        dtype=np.int64,
    )
    if secs.size == 0:
        return None

    times = Time(secs, format="unix", scale="utc")
    alt = sun_altitudes(times, loc)
    mask = alt < -18.0
    if not np.any(mask):
        return None

    idx = np.flatnonzero(mask)
    gaps = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[0, gaps + 1]
    ends = np.r_[gaps, len(idx) - 1]
    lengths = ends - starts + 1
    j = int(np.nanargmax(lengths))
    i0 = idx[starts[j]]
    i1 = idx[ends[j]]
    return (
        datetime.fromtimestamp(int(secs[i0]), tz=tz),
        datetime.fromtimestamp(int(secs[i1]), tz=tz),
    )


def sun_altitudes(times: Time, loc: EarthLocation) -> np.ndarray:
    return (
        get_sun(times)
        .transform_to(AltAz(obstime=times, location=loc))
        .alt.to(u.deg)
        .value
    )


def astro_dark_window(
    date_local_midnight: datetime, tz: ZoneInfo, loc: EarthLocation, step_min: int = 2
) -> Optional[Tuple[datetime, datetime]]:
    start_local = date_local_midnight
    end_local = start_local + timedelta(days=1)

    secs = np.arange(
        int(start_local.astimezone(timezone.utc).timestamp()),
        int(end_local.astimezone(timezone.utc).timestamp()),
        step_min * 60,
        dtype=np.int64,
    )
    if secs.size == 0:
        return None

    times = Time(secs, format="unix", scale="utc")
    alt = sun_altitudes(times, loc)

    mask = alt < -18.0
    if not np.any(mask):
        return None

    idx = np.flatnonzero(mask)
    gaps = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[0, gaps + 1]
    ends = np.r_[gaps, len(idx) - 1]
    lengths = ends - starts + 1
    j = int(np.nanargmax(lengths))
    i0 = idx[starts[j]]
    i1 = idx[ends[j]]

    dark_start_local = datetime.fromtimestamp(int(secs[i0]), tz=tz)
    dark_end_local = datetime.fromtimestamp(int(secs[i1]), tz=tz)
    return dark_start_local, dark_end_local


def airmass_from_alt(alt_deg: np.ndarray) -> np.ndarray:
    z = np.radians(90.0 - np.clip(alt_deg, 0.001, 89.999))
    return 1.0 / (np.cos(z) + 0.50572 * (6.07995 + np.degrees(z)) ** -1.6364)


@dataclass
class Pick:
    name: str
    type: str
    const: str
    ra: str
    dec: str
    mag: str
    size: str
    size_src: str = ""
    width_deg: float = None
    height_deg: float = None
    max_alt: float = None
    best_time_local: datetime = None
    alt_at_ref: float = None
    airmass_min: float = None
    visible_minutes: int = None
    edge_distance_min: int = None
    grade: int = None


def evaluate_target(
    row: Tuple,
    t0_local: datetime,
    t1_local: datetime,
    tz: ZoneInfo,
    loc: EarthLocation,
) -> Optional[Pick]:
    name = row[0]
    typ = row[1]
    const = row[2]
    ra_hms = row[3]
    dec_dms = row[4]
    mag = None
    size = None
    size_src = ""
    width_deg = None
    height_deg = None
    if len(row) >= 7:
        mag = row[5]
        size = row[6]
    if len(row) >= 10:
        size_src = row[7]
        width_deg = row[8]
        height_deg = row[9]
    coord = SkyCoord(ra=ra_hms, dec=dec_dms, unit=(u.hourangle, u.deg), frame="icrs")
    try:
        if coord.dec.degree > DEC_MAX_N:
            return None
    except NameError:
        pass
    s0 = int(t0_local.astimezone(timezone.utc).timestamp())
    s1 = int(t1_local.astimezone(timezone.utc).timestamp())
    secs = np.arange(s0, s1 + STEP_MIN * 60, STEP_MIN * 60, dtype=np.int64)
    if secs.size < 3:
        return None
    times = Time(secs, format="unix", scale="utc")
    alt = coord.transform_to(AltAz(obstime=times, location=loc)).alt.to(u.deg).value
    am = airmass_from_alt(alt)
    try:
        if float(np.nanmax(alt) - np.nanmin(alt)) < DIURNAL_SWING_MIN:
            return None
    except NameError:
        pass
    i_max = int(np.nanargmax(alt))
    if i_max == 0 or i_max == len(alt) - 1:
        return None
    eps = 1e-6
    if not (alt[i_max] >= alt[i_max - 1] - eps and alt[i_max] >= alt[i_max + 1] - eps):
        return None
    max_alt = float(alt[i_max])
    best_local = datetime.fromtimestamp(int(secs[i_max]), tz=tz)
    visible_minutes = int(np.count_nonzero(alt >= MIN_ALT) * STEP_MIN)
    am_valid = am[(np.isfinite(am)) & (alt > 0.0)]
    if am_valid.size == 0:
        return None
    am_min = float(np.nanmin(am_valid))
    frac = REF_HOUR_LOCAL % 24.0
    H = int(frac)
    mrem = (frac - H) * 60.0
    M = int(mrem)
    S = int(round((mrem - M) * 60.0))
    if S == 60:
        S = 0
        M += 1
    if M == 60:
        M = 0
        H = (H + 1) % 24
    t_ref_local = t0_local.replace(hour=H, minute=M, second=S, microsecond=0)
    t_clamped = min(max(t_ref_local, t0_local), t1_local)
    t_ref = Time(
        [int(t_clamped.astimezone(timezone.utc).timestamp())],
        format="unix",
        scale="utc",
    )
    alt_ref = (
        coord.transform_to(AltAz(obstime=t_ref, location=loc)).alt.to(u.deg).value[0]
    )
    alt_at_ref: Optional[float] = float(alt_ref)
    edge_distance_min = int(min(i_max, len(secs) - 1 - i_max) * STEP_MIN)
    g = _compute_grade(
        am_min, visible_minutes, best_local, t0_local, t1_local, width_deg, height_deg
    )
    return Pick(
        name=name,
        type=typ,
        const=const,
        ra=ra_hms,
        dec=dec_dms,
        mag=mag,
        size=size,
        size_src=size_src,
        width_deg=width_deg,
        height_deg=height_deg,
        max_alt=max_alt,
        best_time_local=best_local,
        alt_at_ref=alt_at_ref,
        airmass_min=am_min,
        visible_minutes=visible_minutes,
        edge_distance_min=edge_distance_min,
        grade=g,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Top targets for tonight (or specified date)."
    )
    p.add_argument("--lat", type=float, default=LAT)
    p.add_argument("--lon", type=float, default=LON)
    p.add_argument("--elev", type=float, default=ELEV)
    p.add_argument(
        "--tz",
        type=str,
        default="Europe/Berlin",
        help="IANA tz name, e.g. Europe/Berlin",
    )
    p.add_argument("--limit", type=int, default=LIMIT)
    p.add_argument("--min_alt", type=float, default=MIN_ALT)
    p.add_argument("--step_min", type=int, default=STEP_MIN)
    p.add_argument(
        "--date", type=str, default=None, help="Local date YYYY-MM-DD (optional)"
    )
    return p.parse_args()


_SYNODIC = 29.53058867
_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def moon_illum_and_name(dt_utc: datetime) -> tuple[float, str]:
    """Return (illumination 0..1, phase name) using a simple synodic-cycle model."""
    days = (dt_utc - _EPOCH).total_seconds() / 86400.0
    age = (days % _SYNODIC + _SYNODIC) % _SYNODIC
    k = 2.0 * np.pi * age / _SYNODIC
    illum = 0.5 * (1 - np.cos(k))
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
    return float(illum), name


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


def _offset_str_for_date(tz: ZoneInfo, d: date) -> str:
    dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=tz)
    off = dt.utcoffset() or timedelta(0)
    sign = "+" if off >= timedelta(0) else "-"
    off = abs(off)
    hh = int(off.total_seconds() // 3600)
    mm = int((off.total_seconds() % 3600) // 60)
    return f"{sign}{hh:02d}:{mm:02d}"


def fetch_moonrise_set(
    lat: float, lon: float, tz: ZoneInfo, d: date
) -> tuple[str, str]:
    """Return (moonrise, moonset) as HH:MM local, or '--:--' if unavailable."""
    params = {
        "lat": f"{lat:.6f}",
        "lon": f"{lon:.6f}",
        "date": d.isoformat(),
        "offset": _offset_str_for_date(tz, d),
    }
    url = f"{API_BASE_SUNRISE}?{urlencode(params)}"
    req = Request(
        url, headers={"User-Agent": "astro-top-picks/1.0 (+https://fzastro.com)"}
    )
    mr, ms = None, None
    try:
        with urlopen(req, timeout=15) as r:
            data = json.load(r)
            props = (data or {}).get("properties", {})
            mr = (props.get("moonrise") or {}).get("time")
            ms = (props.get("moonset") or {}).get("time")
    except Exception:
        pass
    return _fmt_hhmm_local_or_dash(mr), _fmt_hhmm_local_or_dash(ms)


def main() -> None:
    global LAT, LON, ELEV, TZ, LIMIT, MIN_ALT, STEP_MIN

    args = _parse_args()
    LAT, LON, ELEV = float(args.lat), float(args.lon), float(args.elev)
    TZ = ZoneInfo(args.tz)
    LIMIT = 500
    MIN_ALT = float(args.min_alt)
    STEP_MIN = int(args.step_min)

    tz = TZ
    loc = EarthLocation(lat=LAT * u.deg, lon=LON * u.deg, height=ELEV * u.m)

    if args.date:
        try:
            base = datetime.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid --date format: {args.date} (expected YYYY-MM-DD)")
            return
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        anchor = local_noon(base.astimezone(tz))
    else:
        now_local = datetime.now(tz)

        anchor = local_noon(now_local)

    win = night_window(anchor, tz, loc, step_min=2)
    if win is None:

        win = night_window(anchor + timedelta(days=1), tz, loc, step_min=2)
        if win is None:
            print("No astronomical darkness for these dates at this location.")
            return
    dark_start, dark_end = win

    try:
        tz_name = tz.key
    except AttributeError:
        tz_name = str(tz)
    site_line = f"Site: lat {LAT:.2f}°, lon {LON:.2f}°, elevation {ELEV:.0f} meters"
    dur_min = int((dark_end - dark_start).total_seconds() // 60)
    h, m = divmod(dur_min, 60)
    win_line = (
        f"Astronomical darkness: "
        f"{dark_start.strftime('%A %Y-%m-%d %H:%M')} → {dark_end.strftime('%A %Y-%m-%d %H:%M')}  "
        f"({int((dark_end - dark_start).total_seconds() // 60) // 60}h {int((dark_end - dark_start).total_seconds() // 60) % 60:02d}m)"
    )
    print(f"Timezone: {tz_name}")
    print(site_line)
    print(win_line)

    midpoint_local = dark_start + (dark_end - dark_start) / 2
    midpoint_utc = midpoint_local.astimezone(timezone.utc)
    illum, phase_name = moon_illum_and_name(midpoint_utc)
    illum_pct = int(round(illum * 100))

    mr1, ms1 = fetch_moonrise_set(LAT, LON, tz, dark_start.date())
    mr2, ms2 = fetch_moonrise_set(LAT, LON, tz, dark_end.date())
    moonrise = mr1 if mr1 != "--:--" else mr2
    moonset = ms1 if ms1 != "--:--" else ms2

    moon_line = (
        f"Moon Phase: {illum_pct}% — {phase_name}  •  Rise {moonrise}  •  Set {moonset}"
    )
    print(moon_line)
    print()

    picks: List[Pick] = []
    for row in CAT:
        pk = evaluate_target(row, dark_start, dark_end, tz, loc)
        if pk is None:
            continue
        if pk.max_alt < MIN_ALT:
            continue
        if pk.visible_minutes < MIN_DURATION_MIN:
            continue
        if pk.airmass_min > MAX_AIRMASS:
            continue
        if pk.edge_distance_min < EDGE_GUARD_MIN:
            continue
        if pk.alt_at_ref is not None and pk.alt_at_ref < MIN_ALT_AT_REF:
            continue
        picks.append(pk)

    if not picks:
        print("No catalog targets meet tonight's constraints.")
        return
    picks.sort(key=lambda p: p.grade, reverse=True)
    header = (
        f"{'Grade':<6} "
        f"{'Name':<32} "
        f"{'Type':<12} "
        f"{'Const':<5} "
        f"{'Wdeg':<8} "
        f"{'Hdeg':<8} "
        f"{'MaxAlt°':<8} "
        f"{'Airmass↓':<9} "
        f"{'Vis':<6} "
        f"{'Best Local':<16}"
    )
    print(
        "Score ≥80 = Good · 50–79 = OK · <50 = Poor — Score breakdown: Airmass 0–40 · Visibility 0–35 · Best-time 0–5 · Size 0–20"
    )

    print()
    print(header)
    print("-" * len(header))

    for i, p in enumerate(picks, start=1):
        mag_s = f"{p.mag:.1f}" if p.mag is not None else ""
        size_src_s = p.size_src if p.size_src is not None else ""
        wdeg_s = f"{p.width_deg:.3f}" if p.width_deg is not None else ""
        hdeg_s = f"{p.height_deg:.3f}" if p.height_deg is not None else ""

        print(
            f"{p.grade:<6d} "
            f"{p.name:<32} "
            f"{p.type:<12} "
            f"{p.const:<5} "
            f"{wdeg_s:<8} "
            f"{hdeg_s:<8} "
            f"{p.max_alt:<8.1f} "
            f"{p.airmass_min:<9.2f} "
            f"{p.visible_minutes:<6d} "
            f"{p.best_time_local.strftime('%Y-%m-%d %H:%M'):<16}"
        )
    print("-" * len(header))

    print()
    print(DIM + "Selection filters:" + RESET)
    print(
        DIM
        + f"  • MIN_ALT = {MIN_ALT:.0f}° — Only count visibility and scoring above this altitude."
        + RESET
    )
    print(
        DIM
        + f"  • MIN_DURATION_MIN = {MIN_DURATION_MIN:d} min — Must stay ≥ MIN_ALT for at least this long."
        + RESET
    )
    print(
        DIM
        + f"  • MAX_AIRMASS = {MAX_AIRMASS:.2f} — Must reach airmass ≤ this value (lower is better; 1.0 ≈ zenith)."
        + RESET
    )
    if EDGE_GUARD_MIN <= 0:
        print(
            DIM
            + "  • EDGE_GUARD_MIN = 0 min — Edge guard disabled (best time may lie near astro-dark edges)."
            + RESET
        )
    else:
        print(
            DIM
            + f"  • EDGE_GUARD_MIN = {EDGE_GUARD_MIN:d} min — Best time must be ≥ this far from astro-dark edges."
            + RESET
        )
    print(
        DIM
        + (
            f"  • REF_HOUR_LOCAL = {int(REF_HOUR_LOCAL):02d}:{int(round((REF_HOUR_LOCAL - int(REF_HOUR_LOCAL)) * 60)):02d}; MIN_ALT_AT_REF = {MIN_ALT_AT_REF:.0f}° — "
            f"If {int(REF_HOUR_LOCAL):02d}:{int(round((REF_HOUR_LOCAL - int(REF_HOUR_LOCAL)) * 60)):02d} falls inside the window, altitude then must be ≥ {MIN_ALT_AT_REF:.0f}°."
        )
        + RESET
    )
    if DEC_MAX_N >= +90.0:
        print(
            DIM
            + "  • DEC_MAX_N = +90° — Declination cap disabled (no extra culling of far-north targets)."
            + RESET
        )
    else:
        print(
            DIM
            + f"  • DEC_MAX_N = {DEC_MAX_N:.1f}° — Exclude targets with declination > this value (far-north cull)."
            + RESET
        )
    print(
        DIM
        + (
            f"  • DIURNAL_SWING_MIN = {DIURNAL_SWING_MIN:.1f}° — Require at least this altitude swing in the window "
            "(rejects flat circumpolars)."
        )
        + RESET
    )
    print()


def _compute_grade(
    am: float,
    vis_min: int,
    best_local: datetime,
    t0_local: datetime,
    t1_local: datetime,
    wdeg: Optional[float],
    hdeg: Optional[float],
) -> int:
    if am <= 1.0:
        s_am = 100.0
    elif am <= 1.09:
        s_am = 100.0 * (1.09 - am) / 0.09
    else:
        s_am = 0.0
    v_cap = 300.0
    s_vis = 100.0 * min(max(float(vis_min) / v_cap, 0.0), 1.0)
    D = max(1.0, (t1_local - t0_local).total_seconds() / 60.0)
    dstar = min(max((best_local - t0_local).total_seconds() / 60.0, 0.0), D)
    s_time = 100.0 * (1.0 - dstar / D)
    if wdeg is None or hdeg is None or wdeg <= 0.0 or hdeg <= 0.0:
        s_arc = 50.0
    else:
        A = 60.0 * (max(wdeg, 0.0) * max(hdeg, 0.0)) ** 0.5
        A_cap = 60.0
        A0 = 1.0
        A_eff = max(0.0, min(A, A_cap) - A0)
        s_arc = 100.0 * (A_eff / (A_cap - A0))
    grade = 0.40 * s_am + 0.35 * s_vis + 0.05 * s_time + 0.20 * (s_arc * 1.75)
    g = int(round(min(max(grade, 0.0), 100.0)))
    return g


if __name__ == "__main__":
    main()

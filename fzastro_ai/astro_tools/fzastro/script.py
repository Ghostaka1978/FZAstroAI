from __future__ import annotations
import warnings

warnings.filterwarnings("ignore")
import sys, time, re, math, unicodedata, os, json, urllib.parse, requests
from typing import Optional, List, Tuple
from functools import lru_cache
from astroquery.simbad import Simbad
from astroquery.exceptions import RemoteServiceError
from requests.exceptions import RequestException, Timeout
from astroquery.ipac.ned import Ned
from astropy.coordinates import solar_system_ephemeris, get_body_barycentric_posvel
from astropy.utils.exceptions import AstropyDeprecationWarning

# Importing astroquery.gaia can print Gaia archive maintenance warnings and can
# slow desktop ASTRO startup. Keep it optional for the migrated app.
if str(os.environ.get("FZASTRO_ENABLE_GAIA", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    try:
        from astroquery.gaia import Gaia
    except Exception:
        Gaia = None
else:
    Gaia = None
from astroquery.vizier import Vizier
from astropy.coordinates import SkyCoord
from astropy.coordinates import SkyCoord
from astropy import units as u
import logging

logging.getLogger("astroquery").setLevel(logging.WARNING)

GAIA_TABLE = "gaiadr3.gaia_source"
GAIA_PROXY_INNER_ARCMIN = 12.0
GAIA_PROXY_MEDIAN_ARCMIN = 8.0


def _env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "")).strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on"}


# Desktop migration default: keep lookup responsive. Gaia is useful for some
# proxy distances, but it is not required for object lookup and can currently
# hang during Gaia archive maintenance. It can be re-enabled explicitly with
# FZASTRO_ENABLE_GAIA=1 when needed.
FZASTRO_FAST_LOOKUP = _env_bool("FZASTRO_FAST_LOOKUP", True)
FZASTRO_ENABLE_GAIA = _env_bool("FZASTRO_ENABLE_GAIA", False)
warnings.filterwarnings(
    "ignore",
    category=AstropyDeprecationWarning,
    module=r"astroquery\.jplhorizons\.core",
)
os.environ.setdefault("ASTROPY_CACHE_DIR", os.path.expanduser("~/.cache/astropy"))
RETRY_ATTEMPTS = 1 if FZASTRO_FAST_LOOKUP else 3
RETRY_BACKOFF_S = 0.5 if FZASTRO_FAST_LOOKUP else 2.0
Simbad.TIMEOUT = 15 if FZASTRO_FAST_LOOKUP else 30
try:
    Ned.TIMEOUT = 10 if FZASTRO_FAST_LOOKUP else 30
except Exception:
    pass
try:
    if Gaia is not None:
        Gaia.TIMEOUT = 10 if FZASTRO_FAST_LOOKUP else 30
except Exception:
    pass
SIMBAD_ENDPOINTS = [
    "https://simbad.cds.unistra.fr/simbad/sim-script",
    "https://simbad.u-strasbg.fr/simbad/sim-script",
]
COMET_CA_DAYS_SPAN_DEFAULT = 730
COMET_CA_STEP = "1d"
Simbad.add_votable_fields(
    "otypes",
    "ra(d)",
    "dec(d)",
    "plx",
    "z_value",
    "rvz_radvel",
    "flux(V)",
    "flux(G)",
    "flux(B)",
    "pmra",
    "pmdec",
    "diameter",
)
KEEP_PREFIXES = [
    "M ",
    "MESSIER",
    "NGC",
    "IC",
    "CALDWELL",
    "PGC",
    "LEDA",
    "UGC",
    "MCG",
    "SH",
    "SH2",
    "BARNARD",
    "LDN",
    "LBN",
    "HD",
    "HIP",
    "2MASX",
    "2MASS",
    "IRAS",
    "2XMM",
]

MC_CANONICAL = {
    "LMC": {
        "center_ra_deg": 80.89,
        "center_dec_deg": -69.76,
        "radius_deg": 7.5,
        "distance_pc": 50_000,
        "label": "literature(LMC, 50 kpc)",
    },
    "SMC": {
        "center_ra_deg": 13.186,
        "center_dec_deg": -72.828,
        "radius_deg": 4.5,
        "distance_pc": 61_000,
        "label": "literature(SMC, 61 kpc)",
    },
}


def _on_sky_sep_deg(ra1, dec1, ra2, dec2):

    import math

    r1, d1 = math.radians(ra1), math.radians(dec1)
    r2, d2 = math.radians(ra2), math.radians(dec2)
    sd = math.sin((d2 - d1) / 2.0)
    sr = math.sin((r2 - r1) / 2.0)
    a = sd * sd + math.cos(d1) * math.cos(d2) * sr * sr
    c = 2.0 * math.asin(min(1.0, math.sqrt(a)))
    return math.degrees(c)


def _magellanic_override(ra_deg, dec_deg, names_or_aliases):
    """
    If target lies inside LMC/SMC footprint OR aliases mention them,
    return canonical distance (pc) and method label.
    """
    if ra_deg is None or dec_deg is None:
        ra_deg = dec_deg = None

    alias_strs = [(_norm_spaces(n) or "").upper() for n in (names_or_aliases or [])]
    alias_hit_lmc = any("LMC" in s or "LARGE MAGELLANIC CLOUD" in s for s in alias_strs)
    alias_hit_smc = any("SMC" in s or "SMALL MAGELLANIC CLOUD" in s for s in alias_strs)

    in_lmc = in_smc = False
    if ra_deg is not None and dec_deg is not None:
        for key in ("LMC", "SMC"):
            c = MC_CANONICAL[key]
            sep = _on_sky_sep_deg(
                ra_deg, dec_deg, c["center_ra_deg"], c["center_dec_deg"]
            )
            if sep <= c["radius_deg"]:
                if key == "LMC":
                    in_lmc = True
                else:
                    in_smc = True

    if alias_hit_smc or in_smc:
        c = MC_CANONICAL["SMC"]
        return c["distance_pc"], c["label"]
    if alias_hit_lmc or in_lmc:
        c = MC_CANONICAL["LMC"]
        return c["distance_pc"], c["label"]
    return None, None


def _sgrA_override(names_or_aliases):
    """
    If aliases clearly identify Sagittarius A*, return canonical distance (pc) and label.
    """
    alias_strs = [(_norm_spaces(n) or "").upper() for n in (names_or_aliases or [])]
    hit = any(
        ("SGR A*" in s) or ("SAGITTARIUS A*" in s) or (s == "NAME SGR A*")
        for s in alias_strs
    )
    if hit:
        # Literature consensus ~8.2 kpc (e.g., GRAVITY/Keck/VLT stellar orbits)
        return 8200.0, "literature(Sgr A*, 8.2 kpc)"
    return None, None


def _norm_spaces(s: str) -> str:
    return " ".join(str(s).split())


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


SOLAR_SYSTEM_ALIASES = {
    "SUN": "sun",
    "MOON": "moon",
    "LUNA": "moon",
    "MERCURY": "mercury",
    "VENUS": "venus",
    "EARTH": "earth",
    "MARS": "mars",
    "JUPITER": "jupiter",
    "SATURN": "saturn",
    "URANUS": "uranus",
    "NEPTUNE": "neptune",
    "PLUTO": "pluto",
    "PHOBOS": "phobos",
    "DEIMOS": "deimos",
    "IO": "io",
    "EUROPA": "europa",
    "GANYMEDE": "ganymede",
    "CALLISTO": "callisto",
    "AMALTHEA": "amalthea",
    "HIMALIA": "himalia",
    "TITAN": "titan",
    "ENCELADUS": "enceladus",
    "MIMAS": "mimas",
    "TETHYS": "tethys",
    "DIONE": "dione",
    "RHEA": "rhea",
    "IAPETUS": "iapetus",
    "HYPERION": "hyperion",
    "PHOEBE": "phoebe",
    "MIRANDA": "miranda",
    "ARIEL": "ariel",
    "UMBRIEL": "umbriel",
    "TITANIA": "titania",
    "OBERON": "oberon",
    "TRITON": "triton",
    "PROTEUS": "proteus",
    "NEREID": "nereid",
    "CHARON": "charon",
}
INTERSTELLAR_ALIASES = {
    "1I/?OUMUAMUA": "A/2017 U1",
    "1I/OUMUAMUA": "A/2017 U1",
    "1I": "A/2017 U1",
    "2I/BORISOV": "C/2019 Q4",
    "2I": "C/2019 Q4",
    "3I/ATLAS": "C/2025 N1",
    "3I": "C/2025 N1",
    "C/2025 A6 (Lemmon)": "C/2025 A6",
    "Lemmon": "C/2025 A6",
    "C/2025 F2 (SWAN)": "C/2025 F2",
    "SWAN": "C/2025 F2",
}

MOON_KEYS = {
    "moon",
    "phobos",
    "deimos",
    "io",
    "europa",
    "ganymede",
    "callisto",
    "amalthea",
    "himalia",
    "titan",
    "enceladus",
    "mimas",
    "tethys",
    "dione",
    "rhea",
    "iapetus",
    "hyperion",
    "phoebe",
    "miranda",
    "ariel",
    "umbriel",
    "titania",
    "oberon",
    "triton",
    "proteus",
    "nereid",
    "charon",
}
MOON_HORIZONS_ID = {
    "moon": 301,
    "phobos": 401,
    "deimos": 402,
    "io": 501,
    "europa": 502,
    "ganymede": 503,
    "callisto": 504,
    "amalthea": 505,
    "himalia": 506,
    "mimas": 601,
    "enceladus": 602,
    "tethys": 603,
    "dione": 604,
    "rhea": 605,
    "titan": 606,
    "hyperion": 607,
    "iapetus": 608,
    "phoebe": 609,
    "ariel": 701,
    "umbriel": 702,
    "titania": 703,
    "oberon": 704,
    "miranda": 705,
    "triton": 801,
    "nereid": 802,
    "proteus": 808,
    "charon": 901,
}


def _moon_horizons_id(body_key: str):
    return MOON_HORIZONS_ID.get(body_key.lower(), body_key)


def _horizons_idtuple_for_body(body_key: str):

    k = body_key.lower()
    if k in MOON_KEYS:
        return _moon_horizons_id(k), "majorbody"
    return k.capitalize(), "majorbody"


SPACECRAFT_ALIASES = {
    "VOYAGER 1": "Voyager 1",
    "VOYAGER 2": "Voyager 2",
    "NEW HORIZONS": "New Horizons",
    "JUNO": "Juno",
    "LUCY": "Lucy",
    "PSYCHE": "Psyche",
    "CURIOSITY": "Curiosity",
    "PERSEVERANCE": "Perseverance",
    "INGENUITY": "Ingenuity",
    "PARKER SOLAR PROBE": "Parker Solar Probe",
    "SOLAR ORBITER": "Solar Orbiter",
    "HUBBLE": "Hubble",
    "JWST": "James Webb Space Telescope",
    "SOHO": "SOHO",
    "ISS": "ISS",
    "INTERNATIONAL SPACE STATION": "ISS",
    "SPACE STATION": "ISS",
    "CASSINI": "Cassini",
    "GALILEO": "Galileo",
    "KEPLER": "Kepler",
    "TESS": "TESS",
    "GAIA": "Gaia",
    "CHANDRA": "Chandra",
}

SPACECRAFT_MISSIONS = {
    # --- Earth Orbiters & Telescopes ---
    "International Space Station": {
        "Target": "Low Earth Orbit",
        "Launch": "1998-11-20",
        "Notes": "Modular, permanently crewed research station; joint NASA, Roscosmos, ESA, JAXA, CSA.",
    },
    "Hubble": {
        "Target": "Low Earth Orbit (547 km)",
        "Launch": "1990-04-24",
        "Notes": "Optical/UV space telescope; famous for Deep Field images, expansion rate studies, and exoplanet atmospheres.",
    },
    "James Webb Space Telescope": {
        "Target": "Sun–Earth L2 point (infrared astronomy)",
        "Launch": "2021-12-25",
        "Notes": "Infrared flagship observatory; studying first galaxies, star formation, and exoplanet atmospheres.",
    },
    "SOHO": {
        "Target": "Sun (L1 point)",
        "Launch": "1995-12-02",
        "Notes": "Solar and Heliospheric Observatory; monitors solar activity, space weather, and discovered >4,000 comets.",
    },
    "Kepler": {
        "Target": "Exoplanets (Earth-trailing orbit)",
        "Launch": "2009-03-07",
        "Notes": "Transit photometry survey; discovered 2,600+ confirmed exoplanets, revolutionizing planetary science.",
    },
    "TESS": {
        "Target": "Exoplanets (High Earth Orbit, 13.7-day orbit)",
        "Launch": "2018-04-18",
        "Notes": "All-sky exoplanet survey; focusing on bright, nearby stars suitable for atmospheric follow-up.",
    },
    "Gaia": {
        "Target": "Milky Way (astrometry, Sun–Earth L2)",
        "Launch": "2013-12-19",
        "Notes": "ESA mission mapping 1.8+ billion stars in 3D; measuring parallax, motion, and structure of the Galaxy.",
    },
    "Chandra": {
        "Target": "X-ray astronomy (High Earth Orbit, ~133,000 km apogee)",
        "Launch": "1999-07-23",
        "Notes": "NASA’s flagship X-ray telescope; studies black holes, galaxy clusters, and supernova remnants.",
    },
    # --- Planetary Missions ---
    "Curiosity": {
        "Target": "Mars (Gale Crater)",
        "Launch": "2011-11-26",
        "Notes": "Mars Science Laboratory rover; analyzing rocks, climate, radiation environment; active since 2012.",
    },
    "Perseverance": {
        "Target": "Mars (Jezero Crater)",
        "Launch": "2020-07-30",
        "Notes": "Mars 2020 rover; searching for past biosignatures, caching samples for Mars Sample Return.",
    },
    "Ingenuity": {
        "Target": "Mars (Jezero Crater, with Perseverance)",
        "Launch": "2020-07-30",
        "Notes": "Technology demonstrator helicopter; achieved first powered flight on another planet (2021).",
    },
    "Juno": {
        "Target": "Jupiter (polar orbit)",
        "Launch": "2011-08-05",
        "Notes": "Studying Jupiter’s atmosphere, gravity, magnetic field, and auroras; extended mission includes flybys of moons.",
    },
    "Cassini": {
        "Target": "Saturn (orbiter)",
        "Launch": "1997-10-15",
        "Notes": "Orbited Saturn for 13 years; Huygens probe landed on Titan in 2005; grand finale plunge in 2017.",
    },
    # --- Solar & Deep Space Missions ---
    "Parker Solar Probe": {
        "Target": "Sun (perihelia ~9.86 solar radii)",
        "Launch": "2018-08-12",
        "Notes": "Closest spacecraft to the Sun; sampling corona and solar wind; record speed ~586,000 km/h.",
    },
    "Solar Orbiter": {
        "Target": "Sun (heliospheric mission)",
        "Launch": "2020-02-10",
        "Notes": "ESA/NASA mission studying solar poles, wind, and heliosphere; imaging polar regions for first time.",
    },
    "Voyager 1": {
        "Target": "Jupiter, Saturn; now interstellar space",
        "Launch": "1977-09-05",
        "Notes": "First spacecraft in interstellar space (>160 AU); carrying the Golden Record of humanity.",
    },
    "Voyager 2": {
        "Target": "Jupiter, Saturn, Uranus, Neptune; now interstellar space",
        "Launch": "1977-08-20",
        "Notes": "Only spacecraft to fly by Uranus and Neptune; crossed into interstellar space in 2018.",
    },
    "New Horizons": {
        "Target": "Pluto & Kuiper Belt",
        "Launch": "2006-01-19",
        "Notes": "First Pluto flyby (2015); studied Arrokoth in 2019; continuing Kuiper Belt exploration.",
    },
    "NH": {
        "Target": "Pluto & Kuiper Belt",
        "Launch": "2006-01-19",
        "Notes": "First Pluto flyby (2015); studied Arrokoth in 2019; continuing Kuiper Belt exploration.",
    },
    "Lucy": {
        "Target": "Jupiter Trojan asteroids",
        "Launch": "2021-10-16",
        "Notes": "Will visit at least 8 Trojan asteroids over 12 years; first mission to study Trojans up close.",
    },
    "Psyche": {
        "Target": "Asteroid 16 Psyche (metal-rich)",
        "Launch": "2023-10-13",
        "Notes": "NASA mission to a unique metallic asteroid; aims to reveal building blocks of planetary cores.",
    },
}


def is_spacecraft_target(name: str) -> Optional[str]:
    return SPACECRAFT_ALIASES.get(_norm_spaces(name).upper())


def is_solar_system_target(name: str) -> Optional[str]:
    key = _norm_spaces(name).upper()
    return SOLAR_SYSTEM_ALIASES.get(key)


EPHEMERIS_ORDER = ("de440s", "de432s", "builtin")


def solar_system_distance_now(body_key: str) -> Tuple[float, float]:
    t = Time.now()

    if body_key in MOON_KEYS:
        obj_id, obj_id_type = _horizons_idtuple_for_body(body_key)
        eph = Horizons(
            id=obj_id, id_type=obj_id_type, location="500@399", epochs=t.jd
        ).ephemerides()
        dist_au = float(eph["delta"][0])
        dist_km = (dist_au * u.au).to(u.km).value
        return dist_au, dist_km
    for eph_name in EPHEMERIS_ORDER:
        try:
            with solar_system_ephemeris.set(eph_name):
                earth_pos, _ = get_body_barycentric_posvel("earth", t)
                body_pos, _ = get_body_barycentric_posvel(body_key, t)
                rel = body_pos - earth_pos
                dist_au = rel.norm().to(u.AU).value
                dist_km = rel.norm().to(u.km).value
                return dist_au, dist_km
        except Exception as e:
            continue

    obj_id, obj_id_type = _horizons_idtuple_for_body(body_key)
    eph = Horizons(
        id=obj_id, id_type=obj_id_type, location="500@399", epochs=t.jd
    ).ephemerides()
    dist_au = float(eph["delta"][0])
    dist_km = (dist_au * u.au).to(u.km).value
    return dist_au, dist_km


def solar_system_apparent_mag(body_id, id_type=None) -> Optional[float]:
    try:
        t = Time.now()
        kw = {} if id_type is None else {"id_type": id_type}
        obj = Horizons(id=body_id, location="500@399", epochs=t.jd, **kw)
        eph = obj.ephemerides()
        for col in ("V", "APmag"):
            if col in eph.colnames and eph[col][0] is not None:
                return float(eph[col][0])
    except Exception:
        pass
    return None


def _finite_geo_range_rate_kms(
    body_id, id_type=None, dt_seconds: float = 60.0
) -> Optional[float]:
    t = Time.now()
    try:
        kw = {} if id_type is None else {"id_type": id_type}
        eph = Horizons(
            id=body_id,
            location="500@399",
            epochs=[(t - dt_seconds * u.s).jd, (t + dt_seconds * u.s).jd],
            **kw,
        ).ephemerides()
        if "delta" in eph.colnames and len(eph) == 2:
            d1_km = (float(eph["delta"][0]) * u.au).to(u.km).value
            d2_km = (float(eph["delta"][1]) * u.au).to(u.km).value
            return (d2_km - d1_km) / (2.0 * dt_seconds)
    except Exception:
        pass
    return None


def _finite_helio_speed_kms(
    body_id, id_type=None, dt_seconds: float = 60.0
) -> Optional[float]:
    t = Time.now()
    try:
        kw = {} if id_type is None else {"id_type": id_type}
        vec = Horizons(
            id=body_id,
            id_type=id_type,
            location="@10",
            epochs=[(t - dt_seconds * u.s).jd, (t + dt_seconds * u.s).jd],
            **kw,
        ).vectors()
        have_xyz = all(c in vec.colnames for c in ("X", "Y", "Z")) and (len(vec) == 2)
        if have_xyz:
            AU_KM = 149_597_870.7
            x1, y1, z1 = float(vec["X"][0]), float(vec["Y"][0]), float(vec["Z"][0])
            x2, y2, z2 = float(vec["X"][1]), float(vec["Y"][1]), float(vec["Z"][1])
            dx_km, dy_km, dz_km = (
                (x2 - x1) * AU_KM,
                (y2 - y1) * AU_KM,
                (z2 - z1) * AU_KM,
            )
            return ((dx_km**2 + dy_km**2 + dz_km**2) ** 0.5) / (2.0 * dt_seconds)
    except Exception:
        pass
    return None


def solar_system_speeds(
    body_name_for_horizons: str,
) -> Tuple[Optional[float], Optional[float]]:
    from astropy import units as u
    import numpy as np

    body_key = str(body_name_for_horizons).lower()
    t = Time.now()
    last_err = None

    def _pos_xyz(rep):
        return rep.x.to(u.km), rep.y.to(u.km), rep.z.to(u.km)

    def _vel_xyz(rep):
        if hasattr(rep, "d_x") and hasattr(rep, "d_y") and hasattr(rep, "d_z"):
            vx, vy, vz = rep.d_x, rep.d_y, rep.d_z
        else:
            vx, vy, vz = rep.x, rep.y, rep.z
        return vx.to(u.km / u.s), vy.to(u.km / u.s), vz.to(u.km / u.s)

    for eph in EPHEMERIS_ORDER:
        try:
            with solar_system_ephemeris.set(eph):
                earth_pos, earth_vel = get_body_barycentric_posvel("earth", t)
                body_pos, body_vel = get_body_barycentric_posvel(body_key, t)
                sun_pos, sun_vel = get_body_barycentric_posvel("sun", t)
                r_rep = body_pos - earth_pos
                v_rep = body_vel - earth_vel
                rx, ry, rz = _pos_xyz(r_rep)
                vx, vy, vz = _vel_xyz(v_rep)
                num = rx * vx + ry * vy + rz * vz
                den = np.sqrt(rx * rx + ry * ry + rz * rz)
                geo_rr = None if den.value == 0 else (num / den).to_value(u.km / u.s)
                vhel_rep = body_vel - sun_vel
                vhx, vhy, vhz = _vel_xyz(vhel_rep)
                helio_speed = np.sqrt(vhx * vhx + vhy * vhy + vhz * vhz).to_value(
                    u.km / u.s
                )
                return float(geo_rr), float(helio_speed)
        except Exception as e:
            last_err = e
            continue
    sys.stderr.write(
        f"[Ephemeris] Failed to compute speeds for {body_name_for_horizons}: {last_err}\n"
    )
    return None, None


COMET_PATTERN = re.compile(r"^\s*(?:[CPDXAI]\s*/|\d+\s*[PI]\s*/)", re.IGNORECASE)


def looks_like_comet(name: str) -> bool:
    n = _strip_diacritics(name).replace("–", "-").replace("—", "-").strip()
    if re.match(r"^\s*(?:[CPDXAI]\s*/|\d+\s*[PI]\s*/)", n, re.IGNORECASE):
        return True
    if re.fullmatch(r"\d+\s*[PI]", n, flags=re.IGNORECASE):
        return True
    return False


_SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"


def _sbdb_primary_designation(query: str) -> Optional[str]:
    try:
        r = requests.get(
            _SBDB_URL, params={"sstr": query, "des": 1, "full-prec": 0}, timeout=15
        )
        if r.status_code != 200:
            return None
        data = r.json()
        obj = data.get("object") or {}
        for key in ("pdes", "des", "full_name"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        return None
    return None


def _normalize_comet_id(name: str) -> List[str]:
    raw = name.strip()
    n0 = _norm_spaces(raw)
    n0_clean = _strip_diacritics(n0).replace("–", "-").replace("—", "-")

    n1 = re.sub(r"\s*\(.*?\)\s*", "", n0_clean).strip()

    cands: List[str] = []
    seen = set()

    def add(x: str):
        if x and x not in seen:
            seen.add(x)
            cands.append(x)

    add(n0)
    add(n0_clean)
    add(n1)

    mapped = INTERSTELLAR_ALIASES.get(n1.upper())
    if mapped:
        add(mapped)
        if mapped.startswith("C/"):
            add(mapped.replace(" ", ""))
            add(mapped.replace("/", " "))

    mP = re.match(
        r"^\s*(\d+)\s*P(?:\s*/\s*([A-Za-z][A-Za-z\-]+)(?:[\s-]*(\d+))?)?\s*$",
        n1,
        re.IGNORECASE,
    )
    if mP:
        num = mP.group(1)
        disc = (mP.group(2) or "").strip()
        idx = (mP.group(3) or "").strip()
        baseP = f"{int(num)}P"
        padP = f"{int(num):04d}P"

        add(baseP)
        add(baseP.upper())
        add(padP)

        if disc:

            add(f"{baseP}/{disc}")
            add(f"{baseP}-{disc}")
            add(f"{baseP}/{disc}".replace(" ", ""))
            add(f"{baseP}/{disc}".replace("/", " "))

            if idx:

                add(f"{baseP}/{disc} {idx}")
                add(f"{baseP}/{disc}{idx}")
                add(f"{baseP}-{disc}-{idx}")
                add(f"{disc} {idx}")
                add(f"{disc}{idx}")
                add(f"{disc}-{idx}")
        return cands

    mC = re.match(r"^([CPDXAI])\s*/\s*(\d{4})\s+([A-Z])\s*(\d+)$", n1, re.IGNORECASE)
    if mC:
        typ = mC.group(1).upper()
        yr = mC.group(2)
        let = mC.group(3).upper()
        num = mC.group(4)
        add(f"{typ}/{yr} {let}{num}")
        add(f"{typ}/{yr}{let}{num}")
        add(f"{typ} {yr} {let}{num}")
        return cands

    mI = re.match(r"^\s*(\d+)\s*I(?:\s*/.*)?\s*$", n1, re.IGNORECASE)
    if mI:
        bareI = f"{int(mI.group(1))}I"
        add(bareI)
        add(bareI.upper())
        return cands

    return cands


def _fetch_iras_nvss_fluxes(ra_deg, dec_deg, radius_arcsec=300):
    v = Vizier(columns=["**"], row_limit=5)
    pos = SkyCoord(ra_deg * u.deg, dec_deg * u.deg, frame="icrs")
    out = {}
    try:
        cat_iras = v.query_region(
            pos, radius=radius_arcsec * u.arcsec, catalog="II/125/main"
        )
        if len(cat_iras) > 0 and len(cat_iras[0]) > 0:
            r = cat_iras[0][0]

            def _as_jy(x):
                try:
                    return float(x)
                except (TypeError, ValueError, KeyError):
                    return None

            out["flux_IRAS_12um_Jy"] = _as_jy(r["Fnu_12"])
            out["flux_IRAS_25um_Jy"] = _as_jy(r["Fnu_25"])
            out["flux_IRAS_60um_Jy"] = _as_jy(r["Fnu_60"])
            out["flux_IRAS_100um_Jy"] = _as_jy(r["Fnu_100"])
    except Exception:
        pass
    try:
        cat_nvss = v.query_region(
            pos, radius=radius_arcsec * u.arcsec, catalog="VIII/65/nvss"
        )
        if len(cat_nvss) > 0 and len(cat_nvss[0]) > 0:
            r = cat_nvss[0][0]
            s_mjy = float(r["S1.4"])
            out["flux_1p4GHz_Jy"] = s_mjy / 1000.0
    except Exception:
        pass
    return out


def _horizons_ephemerides_any(id_str: str, location: str, epochs):
    id_types = ("designation", "name", "smallbody", None)
    locations = [location] + (["500"] if location != "500" else [])
    base_cands = _normalize_comet_id(id_str)
    extra = []
    for c in base_cands:
        extra.extend(
            [c.upper(), c.lower(), c.title(), c.replace(" ", ""), c.replace("/", " ")]
        )
        extra.append(c.replace(" / ", "/").replace("/", "-"))

        mP = re.match(r"^\s*(\d+)\s*P\b", c, re.IGNORECASE)
        if mP:
            n = int(mP.group(1))
            padP = f"{n:04d}P"
            extra.extend([padP, f"DES={n}P", f"DES={padP}"])

    pdes = _sbdb_primary_designation(id_str)
    if pdes:
        extra.extend([pdes, pdes.replace(" ", ""), f"DES={pdes}"])

    seen, cands = set(), []
    for c in base_cands + extra:
        if c and c not in seen:
            seen.add(c)
            cands.append(c)

    for cand in cands:
        for loc in locations:
            for id_type in id_types:
                try:
                    kwargs = {} if id_type is None else {"id_type": id_type}
                    obj = Horizons(id=cand, location=loc, epochs=epochs, **kwargs)
                    try:
                        eph = obj.ephemerides(quantities="1,9,20,23,24")
                    except Exception:
                        eph = obj.ephemerides()
                    if eph is not None and len(eph):
                        return eph, (cand, id_type)
                except Exception as e:
                    continue

    mP = re.match(r"^\s*(\d+)\s*P\b", id_str, re.IGNORECASE)
    if mP:
        bare = f"{int(mP.group(1))}P"
        for id_type in id_types:
            try:
                kwargs = {} if id_type is None else {"id_type": id_type}
                obj = Horizons(id=bare, location=location, epochs=epochs, **kwargs)
                eph = obj.ephemerides()
                if eph is not None and len(eph):
                    return eph, (bare, id_type)
            except Exception as e:
                continue

    raise RuntimeError(f"Unknown target ({id_str}).")


SPECIAL_SPACECRAFT_CANDIDATES = {
    "NEW HORIZONS": [
        "New Horizons (spacecraft)",
        "New Horizons",
        "NH",
        "New_Horizons",
        "-98",
        "2006-001A",
        "DES=2006-001A",
    ],
    "TGO": [
        "ExoMars16 TGO",
        "-143",
        "2016-017A",
        "DES=2016-017A",
        "Trace Gas Orbiter",
    ],
    "PERSEVERANCE": [
        "Mars2020 (spacecraft)",
        "Mars 2020",
        "-168",
        "2020-052A",
        "DES=2020-052A",
    ],
    "HAYABUSA2": [
        "Hayabusa 2 (spacecraft)",
        "Hayabusa 2",
        "-37",
        "2014-076K",
        "DES=2014-076K",
    ],
    "OSIRIS-APEX": [
        "OSIRIS-APX",
        "OSIRIS-REx (spacecraft)",
        "-64",
        "2016-055A",
        "DES=2016-055A",
    ],
    "STEREO A": [
        "STEREO-A",
        "AHEAD",
        "-234",
        "2006-047A",
        "DES=2006-047A",
    ],
    "LRO": [
        "LRO (spacecraft)",
        "Lunar Reconnaissance Orbiter",
        "-85",
        "2009-031A",
        "DES=2009-031A",
    ],
    "CHANDRAYAAN-2": [
        "Chandrayaan-2 (ORBITER) (spacecraft)",
        "-152",
        "2019-042A",
        "DES=2019-042A",
    ],
    "ACE": [
        "ACE (spacecraft)",
        "Advanced Composition Explorer",
        "-92",
        "1997-045A",
        "DES=1997-045A",
    ],
    "LANDSAT 8": [
        "Landsat 8 (spacecraft)",
        "2013-008A",
        "DES=2013-008A",
    ],
    "LANDSAT 9": [
        "Landsat 9 (spacecraft)",
        "2021-088A",
        "DES=2021-088A",
    ],
    "AKATSUKI": [
        "Planet-C (spacecraft)",
        "Akatsuki",
        "2010-020D",
        "DES=2010-020D",
    ],
    "TIANGONG": [
        "Tiangong-1 (spacecraft)",
        "Tiangong-2 (spacecraft)",
    ],
    "FERMI": [
        "Fermi (spacecraft)",
        "Fermi Gamma-ray Space Telescope",
        "2008-029A",
        "DES=2008-029A",
    ],
}


def _horizons_spacecraft_ephemerides_any(query: str, location: str, epochs):
    """
    Resolve spacecraft in Horizons with strong fallbacks and emit a detailed failure log.
    Returns: (eph_table, resolved_string, resolved_id_type)
    """
    base = _norm_spaces(is_spacecraft_target(query) or query)
    id_types = (None, "id", "designation", "name", "smallbody", "majorbody")
    locations = [location] + (["500"] if location != "500" else [])
    tries_log = []

    cands, seen = [], set()

    def add(x: str):
        x = _norm_spaces(x)
        if x and x not in seen:
            seen.add(x)
            cands.append(x)

    for v in (base, base.upper(), base.title()):
        add(v)

    if base.upper() in {"ISS", "INTERNATIONAL SPACE STATION", "SPACE STATION"}:
        for v in (
            "International Space Station",
            "1998-067A",
            "-125544",
            "DES=1998-067A",
            "ISS",
        ):
            add(v)

    specials = SPECIAL_SPACECRAFT_CANDIDATES.get(base.upper())
    if specials:
        for v in specials:
            add(v)

    last_err = None
    for cand in cands:
        for loc in locations:
            for idt in id_types:
                try:
                    kw = {} if idt is None else {"id_type": idt}
                    obj = Horizons(id=cand, location=loc, epochs=epochs, **kw)
                    try:
                        eph = obj.ephemerides(quantities="1,9,20,23,24")
                    except Exception:
                        eph = obj.ephemerides()
                    if eph is not None and len(eph):
                        tries_log.append((cand, idt, loc, True, "ok"))

                        if os.environ.get("HORIZONS_DEBUG"):
                            sys.stderr.write(
                                "[Horizons] success with cand=%r id_type=%r loc=%r\n"
                                % (cand, idt, loc)
                            )
                        return eph, cand, idt
                    else:
                        tries_log.append((cand, idt, loc, False, "empty ephemeris"))
                except Exception as e:
                    last_err = e

                    msg = str(e).strip()[:500]
                    tries_log.append((cand, idt, loc, False, msg))

    lines = [
        "Horizons spacecraft resolve failed for %r" % query,
        "Tried candidates (cand | id_type | loc | ok | note):",
    ]
    for cand, idt, loc, ok, msg in tries_log:
        lines.append(
            " - %s | %s | %s | %s | %s"
            % (cand, idt or "None", loc, "OK" if ok else "FAIL", msg)
        )
    if last_err:
        lines.append("Last exception: %s" % (str(last_err).strip()[:1000],))
    full_log = "\n".join(lines)
    raise RuntimeError(full_log)


def comet_state_now(name: str):
    t = Time.now()
    eph, (resolved, resolved_id_type) = _horizons_ephemerides_any(
        name, location="500@399", epochs=t.jd
    )
    delta_au = float(eph["delta"][0])
    delta_km = (delta_au * u.au).to(u.km).value
    Vmag = None
    for col in ("V", "APmag"):
        if col in eph.colnames:
            try:
                Vmag = float(eph[col][0])
                break
            except Exception:
                pass
    geo_speed_kms = None
    for col in ("deldot", "delta_rate", "DRADVEL"):
        if col in eph.colnames:
            try:
                geo_speed_kms = float(eph[col][0])
                break
            except Exception:
                pass
    AU_KM = 149_597_870.7
    DAY_S = 86400.0
    AUperD_to_kmps = AU_KM / DAY_S
    kwargs = {} if resolved_id_type is None else {"id_type": resolved_id_type}
    helio_speed_kms = None

    def _is_ok(x):
        try:
            import numpy as np

            if hasattr(x, "mask") and getattr(x, "mask", False) is True:
                return False
            if isinstance(x, np.ma.MaskedArray) and np.ma.is_masked(x):
                return False
            x = float(x)
            return math.isfinite(x)
        except Exception:
            return False

    last_exc = None
    for center in ("@10", "@sun", "@0"):
        try:
            vec = Horizons(
                id=resolved, location=center, epochs=t.jd, **kwargs
            ).vectors()
            if helio_speed_kms is None:
                for cand in ("V", "VEL", "VMAG", "SPEED"):
                    if cand in vec.colnames and _is_ok(vec[cand][0]):
                        helio_speed_kms = float(vec[cand][0])
                        break
            if helio_speed_kms is None:
                comps = None
                unit_hint = None
                if all(c in vec.colnames for c in ("VX", "VY", "VZ")):
                    comps = (vec["VX"][0], vec["VY"][0], vec["VZ"][0])
                    unit_hint = getattr(vec["VX"], "unit", None)
                elif all(c in vec.colnames for c in ("XDOT", "YDOT", "ZDOT")):
                    comps = (vec["XDOT"][0], vec["YDOT"][0], vec["ZDOT"][0])
                    unit_hint = getattr(vec["XDOT"], "unit", None)
                elif all(c in vec.colnames for c in ("vx", "vy", "vz")):
                    comps = (vec["vx"][0], vec["vy"][0], vec["vz"][0])
                    unit_hint = getattr(vec["vx"], "unit", None)
                if comps is not None and all(_is_ok(c) for c in comps):
                    vx, vy, vz = (float(c) for c in comps)
                    to_kmps = AUperD_to_kmps
                    if unit_hint is not None:
                        try:
                            ustr = str(unit_hint).lower()
                            if "km" in ustr and "/s" in ustr:
                                to_kmps = 1.0
                            elif "au" in ustr and ("/d" in ustr or "day" in ustr):
                                to_kmps = AUperD_to_kmps
                        except Exception:
                            pass
                    helio_speed_kms = math.sqrt(vx * vx + vy * vy + vz * vz) * to_kmps
            if helio_speed_kms is not None:
                break
        except Exception as e:
            last_exc = e
            continue
    if helio_speed_kms is None and last_exc:
        pass
    if helio_speed_kms is None:
        helio_speed_kms = _finite_helio_speed_kms(resolved)
    if geo_speed_kms is None:
        geo_speed_kms = _finite_geo_range_rate_kms(resolved)
    geom = _horizons_geom_phot(resolved)
    if geom and geom.get("pred_vmag"):
        Vmag = geom.get("pred_vmag")
    return (
        resolved,
        delta_au,
        delta_km,
        geo_speed_kms,
        helio_speed_kms,
        Vmag,
        (geom or {}),
    )


def comet_closest_approach(
    name: str, days_span: int = COMET_CA_DAYS_SPAN_DEFAULT, step: str = COMET_CA_STEP
):
    t0 = Time.now()
    t1 = t0 + days_span * u.day
    eph, _ = _horizons_ephemerides_any(
        name, location="500@399", epochs={"start": t0.iso, "stop": t1.iso, "step": step}
    )
    if len(eph) == 0:
        raise RuntimeError("No ephemerides returned for closest approach search.")
    delta = eph["delta"]
    try:
        import numpy as np

        i_min = int(np.nanargmin(delta))
    except Exception:
        i_min, dmin = 0, float(delta[0])
        for i in range(1, len(delta)):
            di = float(delta[i])
            if di < dmin:
                dmin, i_min = di, i
    dt_col = (
        "datetime_str"
        if "datetime_str" in eph.colnames
        else ("datetime" if "datetime" in eph.colnames else None)
    )
    closest_dt = str(eph[dt_col][i_min]) if dt_col else "unknown-UTC"
    closest_au = float(delta[i_min])
    closest_km = (closest_au * u.au).to(u.km).value
    Vmag = None
    for col in ("V", "APmag"):
        if col in eph.colnames:
            try:
                Vmag = float(eph[col][i_min])
                break
            except Exception:
                pass
    return closest_dt, closest_au, closest_km, Vmag


NEB_CODES = {"PN", "HII", "SNR", "C+N", "RNE", "EMN", "BNE", "DNE", "NEB"}
GAL_CODES = {"AGN", "SY1", "SY2", "BLLAC", "QSO"}
CLU_CODES = {"CL*", "OPC", "GLC", "AS*", "OC", "GC"}
STAR_HINTS = {"V*", "PM*"}
GAL_BASE = {"G"}


def _tok_like(token: str, codes: set) -> bool:
    t = token.upper()
    for c in codes:
        if t == c or t.startswith(c) or (c in t):
            return True
    return False


def map_type(raw: str) -> str:
    if not raw:
        return "Unknown"
    tokens = [s.strip() for s in str(raw).split("|") if s.strip()]
    up = {t.upper() for t in tokens}
    if any(_tok_like(t, NEB_CODES) for t in up):
        return "Nebula"
    if any(_tok_like(t, CLU_CODES) for t in up):
        return "Cluster"
    if (up & GAL_BASE) or any(_tok_like(t, GAL_CODES) for t in up):
        return "Galaxy"
    if any(t.startswith("*") or _tok_like(t, STAR_HINTS) for t in up):
        return "Star"
    return "Other"


SH_PAT = re.compile(r"^S?H\s*2[\s-]", re.IGNORECASE)
M_PAT = re.compile(r"^(M|MESSIER)\s*\d{1,3}$", re.IGNORECASE)
CAT_PAT = re.compile(r"^(NGC|IC|UGC|PGC)\s*\d{1,5}$", re.IGNORECASE)


def is_useful(name: str) -> bool:
    n = name.strip()
    N = n.upper().replace(" ", "")
    if SH_PAT.match(n):
        return True
    if M_PAT.match(n):
        return True
    if CAT_PAT.match(n):
        return True
    if N.startswith("NAME"):
        bad = ("HD", "HIP", "BD", "CD", "CPD", "TYC", "GSC", "2MASS", "UCAC", "PPM")
        if any(N.startswith("NAME" + b) for b in bad):
            return False
        return True
    return any(N.startswith(pref.replace(" ", "")) for pref in KEEP_PREFIXES)


def _get(info_table, colname):
    if info_table is None or colname not in info_table.colnames:
        return None
    val = info_table[colname][0]
    try:
        import numpy as np
        from astropy import units as u

        if hasattr(val, "mask") and getattr(val, "mask", False) is True:
            return None
        if isinstance(val, np.ma.MaskedArray) and np.ma.is_masked(val):
            return None
        if hasattr(val, "to"):
            try:
                return float(val.to(u.km / u.s).value)
            except Exception:
                try:
                    return float(val.to(u.one).value)
                except Exception:
                    return float(val.value)
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", errors="ignore")
        if isinstance(val, str):
            s = val.strip().replace("−", "-")
            if not s or s.lower() in {"nan", "none", "null", "inf", "-inf", "--"}:
                return None
            s = s.split()[0]
            x = float(s)
            return x if math.isfinite(x) else None
        x = float(val)
        return x if math.isfinite(x) else None
    except Exception:
        try:
            x = float(val)
            return x if math.isfinite(x) else None
        except Exception:
            return None


def _get_mag(info_table, colname) -> Optional[float]:
    v = _get(info_table, colname)
    return v if v is not None else None


# Astroquery/SIMBAD has changed several column names across releases.
# Keep all table access defensive so a schema change cannot crash lookup.
def _find_table_column(table, candidates):
    if table is None:
        return None
    colnames = list(getattr(table, "colnames", []) or [])
    if not colnames:
        return None

    for name in candidates:
        if name in colnames:
            return name

    lowered = {str(name).casefold(): name for name in colnames}
    for name in candidates:
        match = lowered.get(str(name).casefold())
        if match is not None:
            return match

    return None


def _is_missing_table_value(value) -> bool:
    try:
        if hasattr(value, "mask") and bool(getattr(value, "mask", False)):
            return True
    except Exception:
        pass

    try:
        import numpy as np

        if np.ma.is_masked(value):
            return True
    except Exception:
        pass

    if value is None:
        return True

    text = str(value).strip()
    return not text or text.lower() in {"nan", "none", "null", "--", "masked"}


def _get_table_cell(table, column_name, row_index=0):
    try:
        return table[column_name][row_index]
    except Exception:
        return None


def _get_text_any(
    table, candidates, default=None, fallback_first_col=False
) -> Optional[str]:
    column = _find_table_column(table, candidates)

    if column is None and fallback_first_col:
        colnames = list(getattr(table, "colnames", []) or [])
        if colnames:
            column = colnames[0]

    if column is None:
        return default

    value = _get_table_cell(table, column)
    if _is_missing_table_value(value):
        return default

    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")

    return _norm_spaces(str(value).strip())


def _get_numeric_any(table, candidates) -> Optional[float]:
    column = _find_table_column(table, candidates)
    if column is None:
        return None
    return _get(table, column)


def _get_coordinates_deg(info_table) -> tuple[Optional[float], Optional[float]]:
    ra_deg = _get_numeric_any(
        info_table,
        ("RA_d", "ra_d", "RA_DEG", "ra_deg", "RAdeg"),
    )
    dec_deg = _get_numeric_any(
        info_table,
        ("DEC_d", "dec_d", "DEC_DEG", "dec_deg", "DEdeg"),
    )

    if ra_deg is not None and dec_deg is not None:
        return ra_deg, dec_deg

    ra_text = _get_text_any(
        info_table, ("RA", "ra", "RA_ICRS", "ra_icrs", "RAJ2000", "raj2000")
    )
    dec_text = _get_text_any(
        info_table, ("DEC", "dec", "DEC_ICRS", "dec_icrs", "DEJ2000", "dej2000")
    )

    if not ra_text or not dec_text:
        return ra_deg, dec_deg

    try:
        coord = SkyCoord(ra_text, dec_text, unit=(u.hourangle, u.deg), frame="icrs")
        return float(coord.ra.deg), float(coord.dec.deg)
    except Exception:
        pass

    try:
        coord = SkyCoord(
            float(ra_text), float(dec_text), unit=(u.deg, u.deg), frame="icrs"
        )
        return float(coord.ra.deg), float(coord.dec.deg)
    except Exception:
        return ra_deg, dec_deg


def _with_retries(callable_fn, *args, **kwargs):
    last_err = None
    for endpoint in SIMBAD_ENDPOINTS:
        Simbad.SIMBAD_URL = endpoint
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return callable_fn(*args, **kwargs)
            except (RemoteServiceError, RequestException, Timeout) as e:
                last_err = e
                delay = min(8.0, RETRY_BACKOFF_S * (2 ** (attempt - 1)))
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(delay)
                else:
                    break
    if last_err:
        sys.stderr.write(f"[SIMBAD] Network error after retries: {last_err}\n")
    return None


def _ned_pick_distance_column(tbl) -> Optional[str]:
    for cand in (
        "Mean Distance (Mpc)",
        "Mean Distance [Mpc]",
        "Distance (Mpc)",
        "Distance",
        "Dist (Mpc)",
    ):
        if cand in tbl.colnames:
            return cand
    for cn in tbl.colnames:
        try:
            unit = getattr(tbl[cn], "unit", None)
            if unit is not None and str(unit).lower() == "mpc":
                return cn
        except Exception:
            pass
    for cn in tbl.colnames:
        if "mpc" in cn.lower():
            return cn
    return None


def _ned_extract_redshift_independent_values_mpc(tbl) -> List[float]:
    if tbl is None or len(tbl) == 0:
        return []
    dcol = _ned_pick_distance_column(tbl)
    if dcol is None:
        return []
    method_col = None
    for cand in ("Method", "Type", "Indicator"):
        if cand in tbl.colnames:
            method_col = cand
            break
    vals = []
    for i in range(len(tbl)):
        if method_col is not None:
            try:
                m = str(tbl[method_col][i]).lower()
                if any(key in m for key in ("redshift", "cz", "hubble")):
                    continue
            except Exception:
                pass
        try:
            token = str(tbl[dcol][i]).split()[0]
            x = float(token)
            if math.isfinite(x) and x > 0:
                vals.append(x)
        except Exception:
            pass
    return vals


def _is_big_nearby(nm: str) -> bool:
    nm = _norm_spaces(nm).upper()
    if nm.startswith("M ") or nm.startswith("MESSIER "):
        return True
    if nm in ("LMC", "LARGE MAGELLANIC CLOUD", "SMC", "SMALL MAGELLANIC CLOUD"):
        return True
    return False


def _ned_try_by_name_then_pos(
    name: str,
    ra_deg: Optional[float],
    dec_deg: Optional[float],
    radius_arcsec: float = 120.0,
):
    base_radii = [30.0, 120.0, 300.0]
    if radius_arcsec not in base_radii:
        base_radii.append(radius_arcsec)
    big_radii = [900.0, 1800.0, 3600.0]
    allow_big = _is_big_nearby(name)

    def _try_positional(ra: float, dec: float, radii: List[float]):
        sc = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
        for rad in radii:
            try:
                tbl = Ned.get_table(sc, table="Distances", radius=rad * u.arcsec)
                if tbl is not None and len(tbl) > 0:
                    return tbl
            except Exception:
                pass
        return None

    if ra_deg is not None and dec_deg is not None:
        tbl = _try_positional(ra_deg, dec_deg, base_radii)
        if tbl is not None:
            return tbl
        if allow_big:
            tbl = _try_positional(ra_deg, dec_deg, big_radii)
            if tbl is not None:
                return tbl
    nm = _norm_spaces(name)
    if nm:
        try:
            tbl = Ned.get_table(nm, table="Distances")
            if tbl is not None and len(tbl) > 0:
                return tbl
        except Exception:
            tbl = None
        try:
            obj = Ned.query_object(nm)
            if obj is not None and len(obj) > 0:
                ra = float(obj["RA"][0])
                dec = float(obj["DEC"][0])
                tbl = _try_positional(ra, dec, base_radii)
                if tbl is not None:
                    return tbl
                if allow_big:
                    tbl = _try_positional(ra, dec, big_radii)
                    if tbl is not None:
                        return tbl
        except Exception:
            pass
    if ra_deg is not None and dec_deg is not None:
        try:
            sc = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
            return Ned.get_table(sc, table="Distances", radius=20.0 * u.arcsec)
        except Exception:
            pass
    return None


def _name_variants(n: str) -> List[str]:
    import re as _re

    n = _norm_spaces(n)
    out = {n}
    m1 = _re.match(r"^(NGC|IC|UGC|PGC)\s*0*([0-9]+)$", n, flags=_re.IGNORECASE)
    m2 = _re.match(r"^(M|MESSIER)\s*0*([0-9]+)$", n, flags=_re.IGNORECASE)
    if m1:
        cat = m1.group(1).upper()
        num = int(m1.group(2))
        pad = 4 if cat in ("NGC", "IC", "UGC", "PGC") else 0
        out.update(
            [
                f"{cat} {num:0{pad}d}",
                f"{cat}{num:0{pad}d}",
                f"{cat} {num}",
                f"{cat}{num}",
            ]
        )
    elif m2:
        num = int(m2.group(2))
        out.update(
            [
                f"MESSIER {num:03d}",
                f"MESSIER {num}",
                f"MESSIER{num:03d}",
                f"MESSIER{num}",
                f"M {num:03d}",
                f"M{num:03d}",
                f"M {num}",
                f"M{num}",
            ]
        )
    return list(out)


@lru_cache(maxsize=512)
def _ned_try_by_name_then_pos_cached(
    nm: str, ra: Optional[float], dec: Optional[float], radius_arcsec: float = 120.0
):
    return _ned_try_by_name_then_pos(nm, ra, dec, radius_arcsec)


def ned_redshift_independent_distance_mpc(
    names_or_aliases: List[str], ra_deg: Optional[float], dec_deg: Optional[float]
) -> Optional[float]:
    tried = set()
    expanded = []
    for nm in names_or_aliases:
        for v in _name_variants(nm):
            if v not in tried:
                tried.add(v)
                expanded.append(v)
    for nm in expanded:
        tbl = None
        for attempt in range(3):
            try:
                tbl = _ned_try_by_name_then_pos_cached(nm, ra_deg, dec_deg, 120.0)
                break
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        if tbl is None or len(tbl) == 0:
            continue
        vals = _ned_extract_redshift_independent_values_mpc(tbl)
        if vals:
            vals.sort()
            n = len(vals)
            return vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    tbl = _ned_try_by_name_then_pos_cached("", ra_deg, dec_deg, 120.0)
    if tbl is not None and len(tbl) > 0:
        vals = _ned_extract_redshift_independent_values_mpc(tbl)
        if vals:
            vals.sort()
            n = len(vals)
            return vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    return None


LIT_DISTANCES_MPC = {
    "LMC": 0.050,
    "LARGE MAGELLANIC CLOUD": 0.050,
    "SMC": 0.061,
    "SMALL MAGELLANIC CLOUD": 0.061,
    "SGR A*": 0.0082,  # 8.2 kpc
    # Fast desktop fallbacks for very common nearby galaxies. These avoid
    # long NED/Gaia proxy lookups when external services are slow.
    "M31": 0.778,
    "M 31": 0.778,
    "MESSIER 31": 0.778,
    "MESSIER 031": 0.778,
    "NGC 224": 0.778,
    "NGC0224": 0.778,
    "ANDROMEDA GALAXY": 0.778,
    "ANDROMEDA": 0.778,
    "M32": 0.785,
    "M 32": 0.785,
    "MESSIER 32": 0.785,
    "NGC 221": 0.785,
    "M110": 0.824,
    "M 110": 0.824,
    "MESSIER 110": 0.824,
    "NGC 205": 0.824,
    "M33": 0.859,
    "M 33": 0.859,
    "MESSIER 33": 0.859,
    "NGC 598": 0.859,
}


def _normalize_id(s: str) -> str:
    return " ".join(s.upper().split())


def _literature_distance_pc(main_id: str, aliases: Optional[List[str]]):
    candidates = [main_id] + list(aliases or [])
    expanded = []
    for name in candidates:
        expanded.append(name)
        try:
            expanded.extend(_name_variants(str(name)))
        except Exception:
            pass
    for name in expanded:
        key = _normalize_id(name)
        if key in LIT_DISTANCES_MPC:
            return LIT_DISTANCES_MPC[key] * 1.0e6
    return None


@lru_cache(maxsize=512)
def _ned_fetch_mean_distance_via_html_cached(variants_key: str) -> Optional[float]:
    variants = json.loads(variants_key)
    base = "https://ned.ipac.caltech.edu/byname"
    params_fixed = {
        "hconst": "67.8",
        "omegam": "0.308",
        "omegav": "0.692",
        "wmap": "4",
        "corr_z": "1",
    }
    pat_mpc = re.compile(
        r"Mean\s*Distance\s*\[Mpc\][^0-9]*([0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE | re.DOTALL,
    )
    pat_mu = re.compile(
        r"Distance\s*Modulus\s*\(m-M\)\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    headers = {"User-Agent": "astro_lookup/1.0"}
    for nm in variants:
        try:
            q = dict(params_fixed)
            q["objname"] = nm
            url = f"{base}?{urllib.parse.urlencode(q)}"
            r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            if r.status_code != 200 or not r.text:
                continue
            m = pat_mpc.search(r.text)
            if m:
                val = float(m.group(1))
                if math.isfinite(val) and val > 0:
                    return val
            m2 = pat_mu.search(r.text)
            if m2:
                mu = float(m2.group(1))
                D_pc = 10 ** ((mu + 5.0) / 5.0)
                D_mpc = D_pc / 1.0e6
                if math.isfinite(D_mpc) and D_mpc > 0:
                    return D_mpc
        except Exception:
            continue
    return None


def _ned_fetch_mean_distance_via_html(names_or_aliases: List[str]) -> Optional[float]:
    variants = []
    seen = set()
    for nm in names_or_aliases:
        for v in _name_variants(nm):
            v = _norm_spaces(v)
            if v not in seen:
                seen.add(v)
                variants.append(v)
    extra = []
    for v in list(variants):
        m = re.match(r"^(M|MESSIER)\s*0*([0-9]+)$", v, flags=re.IGNORECASE)
        if m:
            num = int(m.group(2))
            extra.extend(
                [
                    f"MESSIER {num:03d}",
                    f"MESSIER {num}",
                    f"M {num:03d}",
                    f"M{num:03d}",
                    f"M{num}",
                ]
            )
        m2 = re.match(r"^(NGC|IC|UGC|PGC)\s*0*([0-9]+)$", v, flags=re.IGNORECASE)
        if m2:
            cat = m2.group(1).upper()
            num = int(m2.group(2))
            pad = 4 if cat in ("NGC", "IC", "UGC", "PGC") else 0
            extra.extend(
                [
                    f"{cat} {num:0{pad}d}",
                    f"{cat}{num:0{pad}d}",
                    f"{cat} {num}",
                    f"{cat}{num}",
                ]
            )
    for v in extra:
        if v not in seen:
            seen.add(v)
            variants.append(v)
    return _ned_fetch_mean_distance_via_html_cached(json.dumps(variants))


def _ned_ndistance_median_mpc(names_or_aliases: List[str]) -> Optional[float]:
    import requests as _req, urllib.parse as _up, re as _re, html as _html, time as _t, random as _rand

    url = "https://ned.ipac.caltech.edu/cgi-bin/nDistance"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://ned.ipac.caltech.edu/",
        "Connection": "keep-alive",
    }

    def _variants(nms: List[str]) -> List[str]:
        prio, seen = [], set()
        for nm in nms:
            for v in _name_variants(nm):
                v = _norm_spaces(v)
                if v in seen:
                    continue
                seen.add(v)
                m1 = _re.match(
                    r"^(NGC|IC|UGC|PGC)\s*0*([0-9]+)$", v, flags=_re.IGNORECASE
                )
                m2 = _re.match(r"^(M|MESSIER)\s*0*([0-9]+)$", v, flags=_re.IGNORECASE)
                if m1:
                    cat = m1.group(1).upper()
                    num = int(m1.group(2))
                    pad = 4 if cat in ("NGC", "IC", "UGC", "PGC") else 0
                    prio.extend(
                        [
                            f"{cat} {num:0{pad}d}",
                            f"{cat}{num:0{pad}d}",
                            f"{cat} {num}",
                            f"{cat}{num}",
                        ]
                    )
                elif m2:
                    num = int(m2.group(2))
                    prio.extend(
                        [
                            f"MESSIER {num:03d}",
                            f"MESSIER {num}",
                            f"M {num:03d}",
                            f"M{num:03d}",
                            f"M {num}",
                            f"M{num}",
                        ]
                    )
                else:
                    prio.append(v)
        out, seen2 = [], set()
        for v in prio:
            if v not in seen2:
                seen2.add(v)
                out.append(v)
        return out

    variants = _variants(names_or_aliases)
    pats = [
        _re.compile(
            r"Median\s*</td>\s*<td>\s*[0-9.]+\s*</td>\s*<td>\s*([0-9.]+)\s*</td>",
            _re.IGNORECASE,
        ),
        _re.compile(r"Median\s*(?:=|:)\s*([0-9]+(?:\.[0-9]+)?)\s*Mpc", _re.IGNORECASE),
        _re.compile(
            r">\s*Median\s*<.*?>\s*([0-9]+(?:\.[0-9]+)?)\s*Mpc",
            _re.IGNORECASE | _re.DOTALL,
        ),
        _re.compile(
            r"Summary\s*Statistics.*?Median.*?([0-9]+(?:\.[0-9]+)?)\s*Mpc",
            _re.IGNORECASE | _re.DOTALL,
        ),
        _re.compile(
            r"Preferred\s*Value.*?([0-9]+(?:\.[0-9]+)?)\s*Mpc",
            _re.IGNORECASE | _re.DOTALL,
        ),
    ]

    def _extract(txt: str) -> Optional[float]:
        for pat in pats:
            m = pat.search(txt)
            if m:
                try:
                    val = float(m.group(1))
                    if math.isfinite(val) and val > 0:
                        return val
                except Exception:
                    pass
        return None

    last_html = None
    for v in variants:
        query = f"{url}?{_up.urlencode({'name':v})}"
        for attempt in range(4):
            try:
                r = _req.get(query, headers=headers, timeout=30)
                if r.status_code != 200 or not r.text:
                    _t.sleep(0.5 * (attempt + 1))
                    continue
                txt = _html.unescape(r.text)
                last_html = txt
                val = _extract(txt)
                if val is not None:
                    return val
                if (
                    "Distance Results for" not in txt
                    and "Summary Statistics" not in txt
                ):
                    _t.sleep(0.6 * (attempt + 1))
                    continue
                _t.sleep(0.4 + _rand.random() * 0.4)
            except Exception:
                _t.sleep(0.6 * (attempt + 1))
        _t.sleep(0.4 + _rand.random() * 0.6)


PC_TO_LY = 3.26156


def format_ly_units(distance_pc: float) -> str:
    ly = distance_pc * PC_TO_LY
    if ly >= 1_000_000:
        return f"{ly/1_000_000:.2f} Mly"
    elif ly >= 1_000:
        return f"{ly/1_000:.2f} kly"
    else:
        return f"{ly:.2f} ly"


def _ned_morphology_d25(
    name_or_pos: Tuple[List[str], Optional[float], Optional[float]],
):
    names, ra_deg, dec_deg = name_or_pos
    try:
        cl = None
        for nm in names:
            try:
                cl = Ned.get_table(nm, table="Classifications")
                if cl is not None and len(cl) > 0:
                    break
            except Exception:
                cl = None
        morph = None
        if cl is not None and len(cl) > 0:
            for cand in ("Type", "Class", "Morphology", "MORPH_TYPE"):
                if cand in cl.colnames and str(cl[cand][0]).strip():
                    morph = str(cl[cand][0]).strip()
                    break
        diam = None
        if ra_deg is not None and dec_deg is not None:
            sc = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
            for rad in [30, 120, 300]:
                try:
                    d = Ned.get_table(sc, table="Diameters", radius=rad * u.arcsec)
                    if d is not None and len(d) > 0:
                        diam = d
                        break
                except Exception:
                    pass
        if diam is None:
            for nm in names:
                try:
                    d = Ned.get_table(nm, table="Diameters")
                    if d is not None and len(d) > 0:
                        diam = d
                        break
                except Exception:
                    pass
        d25_maj_arcmin = d25_min_arcmin = pa_deg = None
        if diam is not None and len(diam) > 0:
            maj_cols = [
                c
                for c in diam.colnames
                if "Major Axis" in c or "NED Major" in c or "D25" in c
            ]
            min_cols = [
                c for c in diam.colnames if "Minor Axis" in c or "NED Minor" in c
            ]
            pa_cols = [
                c
                for c in diam.colnames
                if c.lower().startswith("pa") or "Posang" in c or "Position Angle" in c
            ]

            def _first_num(cols):
                for c in cols:
                    try:
                        x = float(str(diam[c][0]).split()[0])
                        if math.isfinite(x):
                            return x
                    except Exception:
                        pass
                return None

            d25_maj_arcmin = _first_num(maj_cols)
            d25_min_arcmin = _first_num(min_cols)
            pa_deg = _first_num(pa_cols)
        if morph or d25_maj_arcmin or d25_min_arcmin or pa_deg:
            return {
                "morphology": morph,
                "d25_maj_arcmin": d25_maj_arcmin,
                "d25_min_arcmin": d25_min_arcmin,
                "d25_pa_deg": pa_deg,
            }
    except Exception:
        pass
    return None


def _horizons_geom_phot(name: str):
    try:
        t = Time.now()
        eph = Horizons(id=name, location="500@399", epochs=t.jd).ephemerides(
            quantities="8,9,19,20,23,29"
        )
        if eph is None or len(eph) == 0:
            return None
        out = {}

        def getf(col):
            try:
                return float(eph[col][0]) if col in eph.colnames else None
            except Exception:
                return None

        out["phase_angle_deg"] = (
            getf("alpha") if "alpha" in eph.colnames else getf("phang")
        )
        out["solar_elong_deg"] = getf("elong") if "elong" in eph.colnames else None
        out["illum_frac"] = (
            getf("illuminated") if "illuminated" in eph.colnames else getf("ill_frac")
        )
        out["heliocentric_au"] = getf("r")
        out["geocentric_au"] = getf("delta")
        out["pred_vmag"] = getf("V") if "V" in eph.colnames else getf("APmag")
        return out
    except Exception:
        return None


@lru_cache(maxsize=512)
def _simbad_query_object_cached(q: str):
    return _with_retries(Simbad.query_object, q)


@lru_cache(maxsize=512)
def _simbad_query_objectids_cached(q: str):
    return _with_retries(Simbad.query_objectids, q)


def _extract_simbad_aliases(ids_table) -> list[str]:
    """Return aliases from astroquery/SIMBAD object ID tables robustly.

    Different astroquery/SIMBAD versions may expose the single identifier
    column as ID, IDS, id, or another name. Older FZASTRO assumed row["ID"],
    which crashes when the table column name changes. A SIMBAD object-id
    result is normally a one-column table, so falling back to the first column
    is the safest behavior.
    """
    aliases: list[str] = []

    if ids_table is None:
        return aliases

    try:
        if len(ids_table) == 0:
            return aliases
    except Exception:
        return aliases

    colnames = list(getattr(ids_table, "colnames", []) or [])
    preferred = ("ID", "IDS", "id", "ids", "identifier", "Identifier", "MAIN_ID")
    column_name = next((name for name in preferred if name in colnames), None)
    if column_name is None and colnames:
        column_name = colnames[0]

    for row in ids_table:
        value = None

        if column_name is not None:
            try:
                value = row[column_name]
            except Exception:
                value = None

        if value is None:
            try:
                value = row[0]
            except Exception:
                value = None

        if value is None:
            continue

        alias = _norm_spaces(str(value).strip())
        if alias:
            aliases.append(alias)

    return sorted(set(aliases))


def _norm_alias(s: str) -> str:
    return " ".join(str(s).upper().split())


_ALIAS_PREF_ORDER = (
    "M ",
    "MESSIER ",
    "NGC",
    "IC",
    "SH 2-",
    "SH2-",
    "LBN",
    "LDN",
    "BARNARD",
    "UGC",
    "PGC",
    "MCG",
    "2MASX",
    "IRAS",
    "HD",
    "HIP",
)


def _choose_canonical_name(main_id: str, aliases: list[str]) -> str:
    cands = [_norm_alias(main_id)] + [_norm_alias(a) for a in aliases if a]
    for pref in _ALIAS_PREF_ORDER:
        for c in cands:
            if c.startswith(pref):
                return c
    return cands[0] if cands else _norm_alias(main_id)


def _alias_set(aliases: list[str]) -> set[str]:
    return {_norm_alias(a) for a in aliases if a}


def _dedupe_by_alias(results: list[dict]) -> list[dict]:
    out = []
    seen_sets = []
    for r in results:
        aliases = r.get("aliases") or r.get("names_or_aliases") or []
        aset = _alias_set(aliases + [r.get("main_id") or r.get("name") or ""])
        merged = False
        for i, s in enumerate(seen_sets):
            if aset & s:
                s |= aset
                o = out[i]
                o_aliases = set(o.get("aliases") or o.get("names_or_aliases") or [])
                o_aliases |= aliases
                if r.get("main_id") and r.get("main_id") not in o_aliases:
                    o_aliases.add(r["main_id"])
                o["aliases"] = sorted(o_aliases)
                o["display_name"] = _choose_canonical_name(
                    o.get("main_id") or o.get("name") or "", list(o_aliases)
                )
                merged = True
                break
        if not merged:
            seen_sets.append(set(aset))
            rr = dict(r)
            rr_aliases = set(aliases)
            if r.get("main_id"):
                rr_aliases.add(r["main_id"])
            rr["aliases"] = sorted(rr_aliases)
            rr["display_name"] = _choose_canonical_name(
                r.get("main_id") or r.get("name") or "", list(rr_aliases)
            )
            out.append(rr)
    return out


NAIF_ID_MAP = {
    # Star/planets
    "sun": 10,
    "mercury": 199,
    "venus": 299,
    "earth": 399,
    "mars": 499,
    "jupiter": 599,
    "saturn": 699,
    "uranus": 799,
    "neptune": 899,
    "pluto": 999,
    # Earth system
    "moon": 301,
    "luna": 301,
    "the moon": 301,
    "earth's moon": 301,
    # Mars
    "phobos": 401,
    "deimos": 402,
    # Jupiter (Galileans)
    "io": 501,
    "europa": 502,
    "ganymede": 503,
    "callisto": 504,
    # Saturn (classics)
    "mimas": 601,
    "enceladus": 602,
    "tethys": 603,
    "dione": 604,
    "rhea": 605,
    "titan": 606,
    "hyperion": 607,
    "iapetus": 608,
    "phoebe": 609,
    # Uranus
    "ariel": 701,
    "umbriel": 702,
    "titania": 703,
    "oberon": 704,
    "miranda": 705,
    # Neptune
    "triton": 801,
    "nereid": 802,
    # Pluto system
    "charon": 901,
    "nix": 902,
    "hydra": 903,
    "kerberos": 904,
    "styx": 905,
}


PLANET_CONSTANTS = {
    "mercury": dict(
        mass_kg=3.3011e23,
        GM_km3_s2=2.2032e4,
        equatorial_radius_km=2439.7,
        surface_gravity_m_s2=3.70,
        escape_velocity_km_s=4.25,
        orbital_period_days=87.9691,
    ),
    "venus": dict(
        mass_kg=4.8675e24,
        GM_km3_s2=3.24859e5,
        equatorial_radius_km=6051.8,
        surface_gravity_m_s2=8.87,
        escape_velocity_km_s=10.36,
        orbital_period_days=224.701,
    ),
    "earth": dict(
        mass_kg=5.97237e24,
        GM_km3_s2=3.986004354e5,
        equatorial_radius_km=6378.137,
        surface_gravity_m_s2=9.80665,
        escape_velocity_km_s=11.186,
        orbital_period_days=365.256,
    ),  # sidereal
    "mars": dict(
        mass_kg=6.4171e23,
        GM_km3_s2=4.282837e4,
        equatorial_radius_km=3396.19,
        surface_gravity_m_s2=3.71,
        escape_velocity_km_s=5.03,
        orbital_period_days=686.980,
    ),
    "jupiter": dict(
        mass_kg=1.89813e27,
        GM_km3_s2=1.26686534e8,
        equatorial_radius_km=71492.0,
        surface_gravity_m_s2=24.79,
        escape_velocity_km_s=59.5,
        orbital_period_days=4332.59,
    ),
    "saturn": dict(
        mass_kg=5.6834e26,
        GM_km3_s2=3.7931187e7,
        equatorial_radius_km=60268.0,
        surface_gravity_m_s2=10.44,
        escape_velocity_km_s=35.5,
        orbital_period_days=10759.22,
    ),
    "uranus": dict(
        mass_kg=8.6810e25,
        GM_km3_s2=5.793939e6,
        equatorial_radius_km=25559.0,
        surface_gravity_m_s2=8.69,
        escape_velocity_km_s=21.3,
        orbital_period_days=30685.4,
    ),
    "neptune": dict(
        mass_kg=1.02413e26,
        GM_km3_s2=6.836529e6,
        equatorial_radius_km=24764.0,
        surface_gravity_m_s2=11.15,
        escape_velocity_km_s=23.5,
        orbital_period_days=60189.0,
    ),
    "pluto": dict(
        mass_kg=1.303e22,
        GM_km3_s2=8.71e2,
        equatorial_radius_km=1188.3,
        surface_gravity_m_s2=0.62,
        escape_velocity_km_s=1.21,
        orbital_period_days=90560.0,
    ),
    "sun": dict(
        mass_kg=1.98847e30,
        GM_km3_s2=1.32712440018e11,
        equatorial_radius_km=695700.0,
        surface_gravity_m_s2=274.0,
        escape_velocity_km_s=617.7,
        orbital_period_days=None,
    ),
    "moon": dict(
        mass_kg=7.34767309e22,
        GM_km3_s2=4902.800066,  # km^3/s^2
        equatorial_radius_km=1737.4,
        surface_gravity_m_s2=1.62,
        escape_velocity_km_s=2.38,
        orbital_period_days=27.321661,  # sidereal month
    ),
    "phobos": dict(
        mass_kg=1.0659e16,
        GM_km3_s2=0.0007112,
        equatorial_radius_km=11.2667,
        surface_gravity_m_s2=0.0057,
        escape_velocity_km_s=0.011,
        orbital_period_days=0.31891,
    ),
    "deimos": dict(
        mass_kg=1.4762e15,
        GM_km3_s2=9.615e-05,
        equatorial_radius_km=6.2,
        surface_gravity_m_s2=0.003,
        escape_velocity_km_s=0.0056,
        orbital_period_days=1.263,
    ),
    "io": dict(
        mass_kg=8.9319e22,
        GM_km3_s2=5959.916,
        equatorial_radius_km=1821.6,
        surface_gravity_m_s2=1.796,
        escape_velocity_km_s=2.56,
        orbital_period_days=1.769,
    ),
    "europa": dict(
        mass_kg=4.7998e22,
        GM_km3_s2=3202.719,
        equatorial_radius_km=1560.8,
        surface_gravity_m_s2=1.314,
        escape_velocity_km_s=2.025,
        orbital_period_days=3.551,
    ),
    "ganymede": dict(
        mass_kg=1.4819e23,
        GM_km3_s2=9887.834,
        equatorial_radius_km=2634.1,
        surface_gravity_m_s2=1.428,
        escape_velocity_km_s=2.741,
        orbital_period_days=7.155,
    ),
    "callisto": dict(
        mass_kg=1.0759e23,
        GM_km3_s2=7179.289,
        equatorial_radius_km=2410.3,
        surface_gravity_m_s2=1.236,
        escape_velocity_km_s=2.44,
        orbital_period_days=16.689,
    ),
    "mimas": dict(
        mass_kg=3.7493e19,
        GM_km3_s2=2.502,
        equatorial_radius_km=198.2,
        surface_gravity_m_s2=0.064,
        escape_velocity_km_s=0.159,
        orbital_period_days=0.942,
    ),
    "enceladus": dict(
        mass_kg=1.0802e20,
        GM_km3_s2=7.210,
        equatorial_radius_km=252.1,
        surface_gravity_m_s2=0.113,
        escape_velocity_km_s=0.239,
        orbital_period_days=1.370,
    ),
    "tethys": dict(
        mass_kg=6.1745e20,
        GM_km3_s2=41.210,
        equatorial_radius_km=531.1,
        surface_gravity_m_s2=0.145,
        escape_velocity_km_s=0.394,
        orbital_period_days=1.888,
    ),
    "dione": dict(
        mass_kg=1.0955e21,
        GM_km3_s2=73.114,
        equatorial_radius_km=561.4,
        surface_gravity_m_s2=0.232,
        escape_velocity_km_s=0.510,
        orbital_period_days=2.737,
    ),
    "rhea": dict(
        mass_kg=2.3065e21,
        GM_km3_s2=153.94,
        equatorial_radius_km=763.8,
        surface_gravity_m_s2=0.264,
        escape_velocity_km_s=0.635,
        orbital_period_days=4.518,
    ),
    "titan": dict(
        mass_kg=1.3452e23,
        GM_km3_s2=8978.14,
        equatorial_radius_km=2574.7,
        surface_gravity_m_s2=1.352,
        escape_velocity_km_s=2.639,
        orbital_period_days=15.945,
    ),
    "hyperion": dict(
        mass_kg=5.62e18,
        GM_km3_s2=0.373,
        equatorial_radius_km=135.0,
        surface_gravity_m_s2=0.02,
        escape_velocity_km_s=0.1,
        orbital_period_days=21.277,
    ),
    "iapetus": dict(
        mass_kg=1.8056e21,
        GM_km3_s2=120.503,
        equatorial_radius_km=734.5,
        surface_gravity_m_s2=0.223,
        escape_velocity_km_s=0.573,
        orbital_period_days=79.321,
    ),
    "phoebe": dict(
        mass_kg=8.3e18,
        GM_km3_s2=0.553,
        equatorial_radius_km=106.5,
        surface_gravity_m_s2=0.038,
        escape_velocity_km_s=0.1,
        orbital_period_days=550.3,
    ),
    "ariel": dict(
        mass_kg=1.353e21,
        GM_km3_s2=90.0,
        equatorial_radius_km=578.9,
        surface_gravity_m_s2=0.269,
        escape_velocity_km_s=0.559,
        orbital_period_days=2.520,
    ),
    "umbriel": dict(
        mass_kg=1.275e21,
        GM_km3_s2=85.0,
        equatorial_radius_km=584.7,
        surface_gravity_m_s2=0.200,
        escape_velocity_km_s=0.478,
        orbital_period_days=4.144,
    ),
    "titania": dict(
        mass_kg=3.527e21,
        GM_km3_s2=240.0,
        equatorial_radius_km=788.9,
        surface_gravity_m_s2=0.379,
        escape_velocity_km_s=0.789,
        orbital_period_days=8.706,
    ),
    "oberon": dict(
        mass_kg=3.014e21,
        GM_km3_s2=200.0,
        equatorial_radius_km=761.4,
        surface_gravity_m_s2=0.354,
        escape_velocity_km_s=0.717,
        orbital_period_days=13.463,
    ),
    "miranda": dict(
        mass_kg=6.59e19,
        GM_km3_s2=4.4,
        equatorial_radius_km=235.8,
        surface_gravity_m_s2=0.079,
        escape_velocity_km_s=0.194,
        orbital_period_days=1.413,
    ),
    "triton": dict(
        mass_kg=2.14e22,
        GM_km3_s2=1427.6,
        equatorial_radius_km=1353.4,
        surface_gravity_m_s2=0.779,
        escape_velocity_km_s=1.455,
        orbital_period_days=5.877,
    ),
    "nereid": dict(
        mass_kg=3.1e19,
        GM_km3_s2=None,
        equatorial_radius_km=170.0,
        surface_gravity_m_s2=None,
        escape_velocity_km_s=None,
        orbital_period_days=360.136,
    ),
    "charon": dict(
        mass_kg=1.586e21,
        GM_km3_s2=101.4,
        equatorial_radius_km=606.0,
        surface_gravity_m_s2=0.288,
        escape_velocity_km_s=0.59,
        orbital_period_days=6.387,
    ),
    "nix": dict(
        mass_kg=4.5e16,
        GM_km3_s2=None,
        equatorial_radius_km=24.8,
        surface_gravity_m_s2=None,
        escape_velocity_km_s=None,
        orbital_period_days=24.854,
    ),
    "hydra": dict(
        mass_kg=4.8e16,
        GM_km3_s2=None,
        equatorial_radius_km=30.9,
        surface_gravity_m_s2=None,
        escape_velocity_km_s=None,
        orbital_period_days=38.206,
    ),
    "kerberos": dict(
        mass_kg=1.65e16,
        GM_km3_s2=None,
        equatorial_radius_km=19.0,
        surface_gravity_m_s2=None,
        escape_velocity_km_s=None,
        orbital_period_days=32.167,
    ),
    "styx": dict(
        mass_kg=7.5e15,
        GM_km3_s2=None,
        equatorial_radius_km=16.0,
        surface_gravity_m_s2=None,
        escape_velocity_km_s=None,
        orbital_period_days=20.161,
    ),
}


def _unique_body_for_horizons(body_key: str):
    k = _norm_spaces(body_key).lower()
    if k in NAIF_ID_MAP:
        return NAIF_ID_MAP[k], None  # numeric id, id_type=None
    return k.capitalize(), None  # fallback


def _h_ephem(id_val, id_type, location, epochs, quantities=None):
    from astroquery.jplhorizons import Horizons

    try:
        obj = Horizons(id=id_val, id_type=id_type, location=location, epochs=epochs)
        return (
            obj.ephemerides(quantities=quantities) if quantities else obj.ephemerides()
        )
    except Exception as e:
        msg = str(e)
        if "Ambiguous target name" in msg:
            key = str(id_val).lower()
            if key in NAIF_ID_MAP:
                obj = Horizons(
                    id=NAIF_ID_MAP[key], id_type=None, location=location, epochs=epochs
                )
                return (
                    obj.ephemerides(quantities=quantities)
                    if quantities
                    else obj.ephemerides()
                )
        raise


def _h_vectors(id_val, id_type, location, epochs):
    from astroquery.jplhorizons import Horizons

    try:
        return Horizons(
            id=id_val, id_type=id_type, location=location, epochs=epochs
        ).vectors()
    except Exception as e:
        msg = str(e)
        if "Ambiguous target name" in msg:
            key = str(id_val).lower()
            if key in NAIF_ID_MAP:
                return Horizons(
                    id=NAIF_ID_MAP[key], id_type=None, location=location, epochs=epochs
                ).vectors()
        raise


from astroquery.jplhorizons import Horizons
from astropy.time import Time
from astropy import units as u


def iss_snapshot():
    t = Time.now().jd
    for cand in (
        "ISS",
        "International Space Station",
        "1998-067A",
        "-125544",
        "DES=1998-067A",
    ):
        try:
            obj = Horizons(id=cand, location="500@399", epochs=t)
            vec = obj.vectors()
            if len(vec):
                if "range" in vec.colnames:
                    range_km = (float(vec["range"][0]) * u.au).to_value(u.km)
                else:
                    eph = obj.ephemerides()
                    range_km = (float(eph["delta"][0]) * u.au).to_value(u.km)
                altitude_km = range_km - 6378.137
                return {"earth_distance_km": range_km, "altitude_km": altitude_km}
        except Exception:
            continue
    raise RuntimeError("ISS not resolved in Horizons")


def _synodic_days(
    planet_days: float,
    earth_days: float = PLANET_CONSTANTS["earth"]["orbital_period_days"],
) -> float | None:
    if not planet_days or not earth_days:
        return None
    # synodic period (days); sign not important for reporting
    return abs(1.0 / (1.0 / planet_days - 1.0 / earth_days))


def planet_horizons_snapshot(body_key: str) -> dict:
    t = Time.now()
    hid, hid_type = _unique_body_for_horizons(body_key)
    loc = "500@399" if body_key.lower() != "earth" else "@10"
    eph = _h_ephem(
        hid, hid_type, loc, Time.now().jd, quantities="1,2,3,4,8,9,19,20,23,24,29"
    )
    ra_deg = float(eph["RA"][0]) if "RA" in eph.colnames else None
    dec_deg = float(eph["DEC"][0]) if "DEC" in eph.colnames else None
    r_helio = float(eph["r"][0]) if "r" in eph.colnames else None
    delta = float(eph["delta"][0]) if "delta" in eph.colnames else None
    Vmag = None
    for col in ("V", "APmag"):
        if col in eph.colnames and eph[col][0] is not None:
            Vmag = float(eph[col][0])
            break
    phase = float(eph["alpha"][0]) if "alpha" in eph.colnames else None
    elong = float(eph["elong"][0]) if "elong" in eph.colnames else None
    vec_geo = _h_vectors(hid, hid_type, loc, Time.now().jd)
    range_au = float(vec_geo["range"][0]) if "range" in vec_geo.colnames else None
    range_rate_au_d = (
        float(vec_geo["range_rate"][0]) if "range_rate" in vec_geo.colnames else None
    )
    range_km = (range_au * u.au).to_value(u.km) if range_au is not None else None
    range_rate_km_s = (
        (range_rate_au_d * (u.au / u.d)).to_value(u.km / u.s)
        if range_rate_au_d is not None
        else None
    )
    vec_hel = _h_vectors(hid, hid_type, "@10", Time.now().jd)
    helio_speed_km_s = None
    if all(c in vec_hel.colnames for c in ("VX", "VY", "VZ")):
        AU_KM = 149_597_870.7
        vx = float(vec_hel["VX"][0]) * AU_KM / 86400.0
        vy = float(vec_hel["VY"][0]) * AU_KM / 86400.0
        vz = float(vec_hel["VZ"][0]) * AU_KM / 86400.0
        helio_speed_km_s = (vx * vx + vy * vy + vz * vz) ** 0.5
    elements = None
    try:
        els_tab = Horizons(
            id=hid, id_type=hid_type, location="@10", epochs=t.jd
        ).elements(refsystem="J2000", refplane="ecliptic")
        if len(els_tab):
            elements = {cn: els_tab[cn][0] for cn in els_tab.colnames}
    except Exception:
        elements = None

    def _get_el(name):
        try:
            return (
                float(elements[name])
                if (elements and elements.get(name) is not None)
                else None
            )
        except Exception:
            return None

    a_au = _get_el("a")
    e = _get_el("e")
    inc = _get_el("incl")
    node = _get_el("Omega")
    argp = _get_el("w")
    M = _get_el("M")
    n_deg_d = _get_el("n")
    period_days = (
        (360.0 / n_deg_d)
        if (n_deg_d and n_deg_d != 0.0)
        else PLANET_CONSTANTS.get(body_key, {}).get("orbital_period_days")
    )
    q_au = a_au * (1.0 - e) if (a_au is not None and e is not None) else None
    Q_au = a_au * (1.0 + e) if (a_au is not None and e is not None) else None
    phys = PLANET_CONSTANTS.get(body_key.lower(), {})
    syn_days = _synodic_days(period_days) if period_days else None
    is_iss = _norm_spaces(body_key).upper() in {
        "ISS",
        "INTERNATIONAL SPACE STATION",
        "SPACE STATION",
    }
    altitude_km = (range_km - 6378.137) if (is_iss and range_km is not None) else None
    return {
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "heliocentric_au": r_helio,
        "distance_au": delta,
        "distance_km": (delta * u.au).to_value(u.km) if delta is not None else None,
        "mag_V_apparent": Vmag,
        "phase_angle_deg": phase,
        "solar_elong_deg": elong,
        "altitude_km": altitude_km,
        "ephemerides": {
            "columns": list(eph.colnames),
            "row0": {
                cn: (eph[cn][0].item() if hasattr(eph[cn][0], "item") else eph[cn][0])
                for cn in eph.colnames
            },
        },
        "vectors": {
            "geocentric": {
                "columns": list(vec_geo.colnames),
                "row0": {
                    cn: (
                        vec_geo[cn][0].item()
                        if hasattr(vec_geo[cn][0], "item")
                        else vec_geo[cn][0]
                    )
                    for cn in vec_geo.colnames
                },
                "range_au": range_au,
                "range_km": range_km,
                "range_rate_km_s": range_rate_km_s,
            },
            "heliocentric": {
                "columns": list(vec_hel.colnames),
                "row0": {
                    cn: (
                        vec_hel[cn][0].item()
                        if hasattr(vec_hel[cn][0], "item")
                        else vec_hel[cn][0]
                    )
                    for cn in vec_hel.colnames
                },
                "speed_km_s": helio_speed_km_s,
            },
        },
        "elements": elements,
        "semi_major_axis_au": a_au,
        "eccentricity": e,
        "inclination_deg": inc,
        "ascending_node_deg": node,
        "arg_perihelion_deg": argp,
        "mean_anomaly_deg": M,
        "mean_motion_deg_per_day": n_deg_d,
        "orbital_period_days": period_days,
        "perihelion_distance_au": q_au,
        "aphelion_distance_au": Q_au,
        "mass_kg": phys.get("mass_kg"),
        "equatorial_radius_km": phys.get("equatorial_radius_km"),
        "GM_km3_s2": phys.get("GM_km3_s2"),
        "surface_gravity_m_s2": phys.get("surface_gravity_m_s2"),
        "escape_velocity_km_s": phys.get("escape_velocity_km_s"),
        "synodic_period_days_vs_earth": syn_days,
    }


def fetch_aliases(query: str):
    body_key = is_solar_system_target(query)
    if body_key:
        try:
            snap = planet_horizons_snapshot(body_key)
            obj_kind = (
                "Star"
                if body_key == "sun"
                else ("Moon" if body_key in MOON_KEYS else "Planet")
            )
            return {
                "main_id": _norm_spaces(query),
                "object_type_raw": "SolarSystem",
                "object_type": obj_kind,
                "ra_deg": snap.get("ra_deg"),
                "dec_deg": snap.get("dec_deg"),
                "parallax_mas": None,
                "redshift": None,
                "radial_velocity_kms": None,
                "distance_pc": (
                    (snap.get("distance_au") * u.au).to(u.pc).value
                    if snap.get("distance_au") is not None
                    else None
                ),
                "distance_method": "horizons(geocentric, now)",
                "aliases": [_norm_spaces(query)],
                "distance_au": snap.get("distance_au"),
                "distance_km": snap.get("distance_km"),
                "mag_V_apparent": snap.get("mag_V_apparent"),
                "speed_geo_kms": (snap.get("vectors") or {})
                .get("geocentric", {})
                .get("range_rate_km_s"),
                "speed_helio_kms": (snap.get("vectors") or {})
                .get("heliocentric", {})
                .get("speed_km_s"),
                "phase_angle_deg": snap.get("phase_angle_deg"),
                "solar_elong_deg": snap.get("solar_elong_deg"),
                "illum_frac": None,  # Horizons provides illuminated % for some bodies via other quantities if needed
                "heliocentric_au": snap.get("heliocentric_au"),
                "ephemerides": snap.get("ephemerides"),
                "vectors": snap.get("vectors"),
                "elements": snap.get("elements"),
                "semi_major_axis_au": snap.get("semi_major_axis_au"),
                "eccentricity": snap.get("eccentricity"),
                "inclination_deg": snap.get("inclination_deg"),
                "ascending_node_deg": snap.get("ascending_node_deg"),
                "arg_perihelion_deg": snap.get("arg_perihelion_deg"),
                "mean_anomaly_deg": snap.get("mean_anomaly_deg"),
                "mean_motion_deg_per_day": snap.get("mean_motion_deg_per_day"),
                "orbital_period_days": snap.get("orbital_period_days"),
                "perihelion_distance_au": snap.get("perihelion_distance_au"),
                "aphelion_distance_au": snap.get("aphelion_distance_au"),
                "mass_kg": snap.get("mass_kg"),
                "equatorial_radius_km": snap.get("equatorial_radius_km"),
                "GM_km3_s2": snap.get("GM_km3_s2"),
                "surface_gravity_m_s2": snap.get("surface_gravity_m_s2"),
                "escape_velocity_km_s": snap.get("escape_velocity_km_s"),
                "synodic_period_days_vs_earth": snap.get(
                    "synodic_period_days_vs_earth"
                ),
            }
        except Exception as e:
            sys.stderr.write(f"[Ephemeris] Failed for {query}: {e}\n")
            return None

    sc_id = is_spacecraft_target(query)
    if sc_id:
        try:
            t = Time.now()
            eph, resolved_sc, resolved_id_type = _horizons_spacecraft_ephemerides_any(
                sc_id, location="500@399", epochs=t.jd
            )
            dist_au = float(eph["delta"][0])
            dist_km = (dist_au * u.au).to(u.km).value

            geo_speed_kms = None
            for col in ("deldot", "delta_rate", "DRADVEL"):
                if col in eph.colnames and eph[col][0] is not None:
                    geo_speed_kms = float(eph[col][0])
                    break

            helio_speed_kms = _finite_helio_speed_kms(resolved_sc)
            geom = _horizons_geom_phot(resolved_sc)
            altitude_km = (
                dist_km - 6378.137
            )  # geocentric delta minus Earth's equatorial radius

            return {
                "main_id": resolved_sc,
                "object_type_raw": "Spacecraft",
                "object_type": "Spacecraft",
                "ra_deg": None,
                "dec_deg": None,
                "parallax_mas": None,
                "redshift": None,
                "radial_velocity_kms": None,
                "distance_pc": (dist_au * u.au).to(u.pc).value,
                "distance_method": "horizons(geocentric, now)",
                "aliases": [resolved_sc, _norm_spaces(query)],
                "distance_au": dist_au,
                "distance_km": dist_km,
                "altitude_km": altitude_km,  # ? add this
                "speed_geo_kms": geo_speed_kms,
                "speed_helio_kms": helio_speed_kms,
                "mag_V_apparent": None,
                "phase_angle_deg": None if not geom else geom.get("phase_angle_deg"),
                "solar_elong_deg": None if not geom else geom.get("solar_elong_deg"),
                "illum_frac": None if not geom else geom.get("illum_frac"),
                "heliocentric_au": None if not geom else geom.get("heliocentric_au"),
            }
        except Exception as e:
            sys.stderr.write(
                f"[Horizons] Spacecraft handling failed for {query}: {e}\n"
            )
            return None

    if looks_like_comet(query):
        try:
            resolved, dist_au, dist_km, geo_v_kms, helio_v_kms, Vmag, geom = (
                comet_state_now(query)
            )
            ca_dt, ca_au, ca_km, ca_v = comet_closest_approach(
                query, COMET_CA_DAYS_SPAN_DEFAULT, COMET_CA_STEP
            )
            if geom and geom.get("pred_vmag") is not None:
                Vmag = geom.get("pred_vmag")
            return {
                "main_id": resolved,
                "object_type_raw": "Comet",
                "object_type": "Comet",
                "ra_deg": None,
                "dec_deg": None,
                "parallax_mas": None,
                "redshift": None,
                "radial_velocity_kms": None,
                "distance_pc": (dist_au * u.au).to(u.pc).value,
                "distance_method": "horizons(geocentric, now)",
                "aliases": [resolved, query],
                "distance_au": dist_au,
                "distance_km": dist_km,
                "speed_geo_kms": geo_v_kms,
                "speed_helio_kms": helio_v_kms,
                "mag_V_apparent": Vmag,
                "ca_datetime_utc": ca_dt,
                "ca_distance_au": ca_au,
                "ca_distance_km": ca_km,
                "ca_mag_V": ca_v,
                "ca_span_days": COMET_CA_DAYS_SPAN_DEFAULT,
                "ca_step": COMET_CA_STEP,
                "phase_angle_deg": None if not geom else geom.get("phase_angle_deg"),
                "solar_elong_deg": None if not geom else geom.get("solar_elong_deg"),
                "illum_frac": None if not geom else geom.get("illum_frac"),
                "heliocentric_au": None if not geom else geom.get("heliocentric_au"),
            }
        except Exception as e:
            sys.stderr.write(f"[Horizons] Comet handling failed for {query}: {e}\n")
            return None

    info = None
    resolved_query = None
    for cand in _name_variants(query) + [_norm_spaces(query)]:
        i = _simbad_query_object_cached(cand)
        if i is not None and len(i) > 0:
            info = i
            resolved_query = cand
            break
    if info is None or len(info) == 0:
        return None
    query = resolved_query or query

    ids_table = _simbad_query_objectids_cached(query)
    aliases = _extract_simbad_aliases(ids_table)
    filtered = [a for a in aliases if is_useful(a)]

    main_id = _get_text_any(
        info,
        ("MAIN_ID", "main_id", "MAINID", "mainid", "ID", "id"),
        default=_norm_spaces(query),
        fallback_first_col=True,
    ) or _norm_spaces(query)
    object_type_raw = (
        _get_text_any(
            info,
            (
                "OTYPES",
                "otypes",
                "OTYPE",
                "otype",
                "MAIN_TYPE",
                "main_type",
                "OBJECT_TYPE",
                "object_type",
            ),
            default="",
        )
        or ""
    )

    ra_deg, dec_deg = _get_coordinates_deg(info)
    pmra_masyr = _get_numeric_any(info, ("PMRA", "pmra", "PM_RA", "pm_ra"))
    pmdec_masyr = _get_numeric_any(info, ("PMDEC", "pmdec", "PM_DEC", "pm_dec"))
    parallax_mas = _get_numeric_any(
        info, ("PLX_VALUE", "plx_value", "PLX", "plx", "parallax", "PARALLAX")
    )
    z = _get_numeric_any(info, ("Z_VALUE", "z_value", "Z", "z", "redshift", "REDSHIFT"))
    vr_kms = _get_numeric_any(
        info,
        (
            "RVZ_RADVEL",
            "rvz_radvel",
            "RV_VALUE",
            "rv_value",
            "radial_velocity",
            "RADIAL_VELOCITY",
        ),
    )

    mag_V = _get_numeric_any(info, ("FLUX_V", "flux_v", "V", "v"))
    mag_G = _get_numeric_any(info, ("FLUX_G", "flux_g", "G", "g"))
    mag_B = _get_numeric_any(info, ("FLUX_B", "flux_b", "B", "b"))

    name_candidates = [main_id] + [_norm_spaces(a) for a in filtered]
    obj_kind = map_type(object_type_raw)

    # --- Distance determination (preserve ladder, avoid unnecessary NED calls) ---
    distance_pc = None
    distance_method = None

    # 1) Magellanic override (by footprint or aliases)
    mc_pc, mc_label = _magellanic_override(ra_deg, dec_deg, name_candidates)
    sgr_pc, sgr_label = _sgrA_override(name_candidates)
    if sgr_pc is not None:
        distance_pc = sgr_pc
        distance_method = sgr_label
    if mc_pc is not None:
        distance_pc = mc_pc
        distance_method = mc_label

    lit_pc = _literature_distance_pc(main_id, name_candidates)
    if distance_pc is None and lit_pc is not None:
        distance_pc = lit_pc
        distance_method = "literature override"

    # 2) Direct parallax — only for stars
    if (
        distance_pc is None
        and obj_kind == "Star"
        and parallax_mas is not None
        and parallax_mas > 0
    ):
        distance_pc = 1000.0 / parallax_mas
        distance_method = "parallax"

    # 3) Hubble-law regime: use redshift for extragalactic objects with decent z
    if distance_pc is None:
        kind_norm = (obj_kind or "").strip().lower()
        is_extragal = kind_norm in ("galaxy", "quasar", "qso", "agn")
        if (
            is_extragal
            and (z is not None)
            and (z >= 0.005)
            and (obj_kind not in ("Nebula", "Cluster", "HII Region", "Open cluster"))
        ):
            H0 = 70.0
            c_kms = 299_792.458
            distance_pc = (c_kms * z / H0) * 1.0e6
            distance_method = "hubble(z)"

    # 4) NED redshift-independent ladder — only when still needed (very nearby or no z)
    need_ned = (
        distance_pc is None
        and ((obj_kind or "").strip().lower() == "galaxy")
        and ((z is None) or (z < 0.005))
    )

    if need_ned and not FZASTRO_FAST_LOOKUP:
        # (a) trimmed-mean
        try:

            def _ned_distances_trimmed_mean_mpc(names_or_aliases, ra_d, dec_d):
                collected, tried, expanded = [], set(), []
                for nm in names_or_aliases:
                    for v in _name_variants(nm):
                        if v not in tried:
                            tried.add(v)
                            expanded.append(v)
                for nm in expanded + [""]:
                    try:
                        tbl = _ned_try_by_name_then_pos_cached(nm, ra_d, dec_d, 120.0)
                        if tbl is not None and len(tbl) > 0:
                            collected.extend(
                                _ned_extract_redshift_independent_values_mpc(tbl)
                            )
                    except Exception:
                        pass
                collected = sorted(
                    x for x in collected if x and math.isfinite(x) and x > 0.0
                )
                if not collected:
                    return None
                n = len(collected)
                lo = int(0.10 * n)
                hi = max(lo + 1, int(0.90 * n))
                trimmed = collected[lo:hi] if hi > lo else collected
                return sum(trimmed) / float(len(trimmed))

            ned_mean_mpc = _ned_distances_trimmed_mean_mpc(
                name_candidates, ra_deg, dec_deg
            )
        except Exception:
            ned_mean_mpc = None

        if ned_mean_mpc is not None:
            distance_pc = ned_mean_mpc * 1.0e6
            distance_method = "NED-D (mean)"
        else:
            # (b) median via API
            try:
                ned_mpc = ned_redshift_independent_distance_mpc(
                    name_candidates, ra_deg, dec_deg
                )
            except Exception:
                ned_mpc = None
            if ned_mpc is not None:
                distance_pc = ned_mpc * 1.0e6
                distance_method = "NED-D (median)"
            else:
                # (c) HTML mean
                try:
                    ned_html_mean = _ned_fetch_mean_distance_via_html(name_candidates)
                except Exception:
                    ned_html_mean = None
                if ned_html_mean is not None:
                    distance_pc = ned_html_mean * 1.0e6
                    distance_method = "NED-D (mean)"
                else:
                    # (d) nDistance median (robust Mpc parser)
                    try:
                        ned_ndist_mpc = _ned_ndistance_median_mpc(
                            name_candidates, ra_deg, dec_deg
                        )
                    except Exception:
                        ned_ndist_mpc = None
                    if ned_ndist_mpc is not None:
                        distance_pc = ned_ndist_mpc * 1.0e6
                        distance_method = "NED-D (median)"

    # 5) Final Hubble fallback if still nothing (use z if present, else radial velocity)
    if distance_pc is None and (
        obj_kind not in ("Nebula", "Cluster", "HII Region", "Open cluster")
    ):
        H0 = 70.0
        c_kms = 299_792.458
        v = None
        if (z is not None) and (z > 0):
            v = c_kms * z
            distance_method = "hubble(z)"
        elif (vr_kms is not None) and (vr_kms > 0):
            v = vr_kms
            distance_method = "hubble(rv)"
        if v is not None and H0 > 0:
            distance_pc = (v / H0) * 1.0e6

        def _ned_distances_trimmed_mean_mpc(names_or_aliases, ra_d, dec_d):
            collected = []
            tried = set()
            expanded = []
            for nm in names_or_aliases:
                for v in _name_variants(nm):
                    if v not in tried:
                        tried.add(v)
                        expanded.append(v)
            for nm in expanded + [""]:
                try:
                    tbl = _ned_try_by_name_then_pos_cached(nm, ra_d, dec_d, 120.0)
                    if tbl is not None and len(tbl) > 0:
                        collected.extend(
                            _ned_extract_redshift_independent_values_mpc(tbl)
                        )
                except Exception:
                    pass
            if not collected:
                return None
            collected = sorted(x for x in collected if math.isfinite(x) and x > 0.0)
            if not collected:
                return None
            n = len(collected)
            lo = int(0.10 * n)
            hi = max(lo + 1, int(0.90 * n))
            trimmed = collected[lo:hi] if hi > lo else collected
            return sum(trimmed) / float(len(trimmed))

        ned_mean_mpc = None
        if not FZASTRO_FAST_LOOKUP:
            try:
                ned_mean_mpc = _ned_distances_trimmed_mean_mpc(
                    name_candidates, ra_deg, dec_deg
                )
            except Exception:
                ned_mean_mpc = None

        if ned_mean_mpc is not None:
            distance_pc = ned_mean_mpc * 1.0e6
            distance_method = "NED-D (mean)"
        else:
            try:
                ned_mpc = ned_redshift_independent_distance_mpc(
                    name_candidates, ra_deg, dec_deg
                )
            except Exception:
                ned_mpc = None
            if ned_mpc is not None:
                distance_pc = ned_mpc * 1.0e6
                distance_method = "NED-D (median)"
            else:
                try:
                    ned_html_mean = _ned_fetch_mean_distance_via_html(name_candidates)
                except Exception:
                    ned_html_mean = None
                if ned_html_mean is not None:
                    distance_pc = ned_html_mean * 1.0e6
                    distance_method = "NED-D (mean)"
                else:
                    if (obj_kind or "").strip().lower() == "galaxy":
                        try:
                            ned_ndist_mpc = _ned_ndistance_median_mpc(name_candidates)
                        except Exception:
                            ned_ndist_mpc = None
                        if ned_ndist_mpc is not None:
                            distance_pc = ned_ndist_mpc * 1.0e6
                            distance_method = "NED-D (median)"
                    if distance_pc is None and (
                        obj_kind
                        not in ("Nebula", "Cluster", "HII Region", "Open cluster")
                    ):
                        H0 = 70.0
                        c_kms = 299_792.458
                        v = None
                        if z is not None and z > 0:
                            v = c_kms * z
                            distance_method = "hubble(z)"
                        elif vr_kms is not None and vr_kms > 0:
                            v = vr_kms
                            distance_method = "hubble(rv)"
                        if v is not None and H0 > 0:
                            d_mpc = v / H0
                            distance_pc = d_mpc * 1.0e6

    def _safe_float(x):
        try:
            import numpy as np

            if isinstance(x, np.ma.MaskedArray) and np.ma.is_masked(x):
                return None
            v = float(x)
            return v if math.isfinite(v) else None
        except Exception:
            return None

    def _gaia_query_cone_adql(ra_d, dec_d, radius_arcmin, columns, where=""):
        r_deg = radius_arcmin / 60.0
        where_sql = f"WHERE {where}" if where.strip() else ""
        adql = f"""
        SELECT {columns}
        FROM {GAIA_TABLE}
        {where_sql}
        AND 1=CONTAINS(POINT('ICRS', ra, dec),
                       CIRCLE('ICRS', {ra_d}, {dec_d}, {r_deg}))
        """
        adql = adql.replace("WHERE AND", "WHERE")
        try:
            job = Gaia.launch_job_async(adql, dump_to_file=False)
            return job.get_results()
        except (RemoteServiceError, Timeout, RequestException) as e:
            return None

    def _gaia_hot_star_distance_pc(ra_d, dec_d):
        if ra_d is None or dec_d is None:
            return None, None, {}
        cols = "source_id AS sid, ra, dec, phot_g_mean_mag AS G, bp_rp, parallax, parallax_error"
        where = "(phot_g_mean_mag < 9) AND (bp_rp IS NOT NULL) AND (parallax IS NOT NULL) AND (bp_rp < 0.6)"
        tab = _gaia_query_cone_adql(ra_d, dec_d, GAIA_PROXY_INNER_ARCMIN, cols, where)
        if tab is None or len(tab) == 0:
            return None, None, {}
        try:
            tab.sort("G")
        except Exception:
            try:
                tab.sort("phot_g_mean_mag")
            except Exception:
                pass
        row = tab[0]

        def _rget(r, *keys):
            for k in keys:
                try:
                    return r[k]
                except KeyError:
                    continue
            return None

        plx = _safe_float(_rget(row, "parallax", "PARALLAX"))
        if plx is None or plx <= 0:
            return None, None, {}
        d_pc = 1000.0 / plx
        sid_val = _rget(row, "sid", "source_id", "SOURCE_ID")
        G_val = _safe_float(_rget(row, "G", "phot_g_mean_mag", "PHOT_G_MEAN_MAG"))
        bprp = _safe_float(_rget(row, "bp_rp", "BP_RP"))
        plxerr = _safe_float(_rget(row, "parallax_error", "PARALLAX_ERROR"))
        meta = dict(
            method="Gaia proxy (hot-star parallax)",
            gaia_source_id=str(sid_val) if sid_val is not None else None,
            G=G_val,
            bp_rp=bprp,
            parallax_mas=plx,
            parallax_err_mas=plxerr,
        )
        return d_pc, "Gaia proxy (hot-star parallax)", meta

    def _gaia_median_bright_distance_pc(ra_d, dec_d):
        if ra_d is None or dec_d is None:
            return None, None, {}
        cols = "parallax"
        where = "(phot_g_mean_mag BETWEEN 6 AND 13) AND (parallax IS NOT NULL) AND (parallax > 0)"
        tab = _gaia_query_cone_adql(ra_d, dec_d, GAIA_PROXY_MEDIAN_ARCMIN, cols, where)
        if tab is None or len(tab) == 0:
            return None, None, {}
        plx_vals = [_safe_float(p) for p in tab["parallax"]]
        plx_vals = [p for p in plx_vals if p is not None and p > 0]
        if not plx_vals:
            return None, None, {}
        plx_vals.sort()
        n = len(plx_vals)
        med_plx = (
            plx_vals[n // 2]
            if n % 2
            else 0.5 * (plx_vals[n // 2 - 1] + plx_vals[n // 2])
        )
        d_pc = 1000.0 / med_plx
        meta = dict(
            method="Gaia proxy (median bright-star parallax)",
            n=n,
            median_parallax_mas=med_plx,
            radius_arcmin=GAIA_PROXY_MEDIAN_ARCMIN,
        )
        return d_pc, "Gaia proxy (median bright-star parallax)", meta

    _gaia_meta = None
    if (
        FZASTRO_ENABLE_GAIA
        and distance_pc is None
        and ra_deg is not None
        and dec_deg is not None
        and ((obj_kind or "").strip().lower() != "galaxy")
    ):
        d_pc, gaia_label, gaia_meta = _gaia_hot_star_distance_pc(ra_deg, dec_deg)
        if d_pc is None:
            d_pc, gaia_label, gaia_meta = _gaia_median_bright_distance_pc(
                ra_deg, dec_deg
            )
        if d_pc is not None:
            distance_pc = d_pc
            distance_method = gaia_label
            _gaia_meta = gaia_meta

    morph_d25 = None
    if (not FZASTRO_FAST_LOOKUP) and (obj_kind or "").strip().lower() == "galaxy":
        morph_d25 = _ned_morphology_d25((name_candidates, ra_deg, dec_deg))

    ids_tbl = _simbad_query_objectids_cached(main_id or query)
    aliases_raw = _extract_simbad_aliases(ids_tbl)
    if main_id:
        aliases_raw.append(str(main_id))
    filtered = [a for a in aliases_raw if is_useful(a)]

    normed = [_norm_spaces(a) for a in filtered]
    aliases_sorted = sorted(set(normed))

    pretty = []
    _seenp = set()
    for A in aliases_sorted:
        if A.upper().startswith("NAME "):
            p = A[5:].strip()
            if p and p not in _seenp:
                _seenp.add(p)
                pretty.append(p)

    import re as _re

    def _looks_pretty(s: str) -> bool:
        up = s.upper()
        if up.startswith("NAME "):
            return False
        if any(up.startswith(p) for p in KEEP_PREFIXES):
            return False
        t = s.lstrip("*").strip()
        if any(ch.isdigit() for ch in t):
            return False
        if any(ch in t for ch in "+/-_"):
            return False
        return bool(_re.search(r"\s", t))

    for A in aliases_sorted:
        if _looks_pretty(A) and A not in _seenp:
            _seenp.add(A)
            pretty.append(A)

    aliases_no_raw = [a for a in aliases_sorted if not a.upper().startswith("NAME ")]
    aliases_combined = pretty + [a for a in aliases_no_raw if a not in pretty]

    # Build a pretty list for NAME- style aliases (e.g., "Iris Nebula")
    pretty = []
    seen_pretty = set()
    for a in filtered:
        A = _norm_spaces(a)
        if A.upper().startswith("NAME "):
            p = A[5:].strip()
            if p and p not in seen_pretty:
                seen_pretty.add(p)
                pretty.append(p)
    # Dedup & sort canonical aliases
    base = {
        "main_id": _norm_spaces(main_id),
        "object_type_raw": object_type_raw,
        "object_type": obj_kind,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "pmra_masyr": pmra_masyr,
        "pmdec_masyr": pmdec_masyr,
        "parallax_mas": parallax_mas,
        "redshift": z,
        "radial_velocity_kms": vr_kms,
        "distance_pc": distance_pc,
        "distance_method": distance_method,
        "aliases": aliases_combined,
        "mag_V": mag_V,
        "mag_G": mag_G,
        "mag_B": mag_B,
        "_gaia_meta": _gaia_meta,
    }
    base["display_name"] = _choose_canonical_name(
        base["main_id"], base.get("aliases", [])
    )

    if morph_d25:
        base.update(morph_d25)
    return base


def _print_section(title: str, lines: List[str]):
    if not lines:
        return
    print(f"[ {title} ]")
    for ln in lines:
        print("  " + ln)
    print()


def _fmt_list(items, wrap=100):
    s = ", ".join(items)
    if len(s) <= wrap:
        return s

    out, line = [], []
    ln = 0
    for t in items:
        sep = ", " if line else ""
        if ln + len(sep) + len(t) > wrap:
            out.append(", ".join(line))
            line = [t]
            ln = len(t)
        else:
            line.append(t)
            ln += len(sep) + len(t)
    if line:
        out.append(", ".join(line))
    return "\n      ".join(out)


def print_help():

    solar_all = sorted(set(SOLAR_SYSTEM_ALIASES.keys()))
    moon_all = sorted(set(m.upper() for m in MOON_KEYS))
    craft_all = sorted(set(SPACECRAFT_ALIASES.keys()))
    inter_keys = sorted(set(INTERSTELLAR_ALIASES.keys()))
    keep_prefixes = sorted(KEEP_PREFIXES)

    examples = [
        "astro_lookup M31",
        "astro_lookup Saturn",
        "astro_lookup Europa",
        "astro_lookup C/2023 A3",
        "astro_lookup 42P/Neujmin 3",
        "astro_lookup 1I/?Oumuamua",
        "astro_lookup ISS",
        "astro_lookup New Horizons",
        "astro_lookup PGC 69457",
    ]

    print("astro_lookup – Astronomy object & comet/spacecraft info fetcher")
    print()
    print("Usage:")
    print("  astro_lookup <object name or designation>")
    print()
    print("Examples:")
    for ex in examples:
        print(f"  {ex}")
    print()
    print("What you can query (aliases recognized):")
    print()
    print("  • Solar-system bodies (planets, Sun, major moons):")
    print("      " + _fmt_list(solar_all))
    print()
    print("  • Moons handled via Horizons (subset shown explicitly):")
    print("      " + _fmt_list(moon_all))
    print()
    print("  • Spacecraft / stations (Horizons):")
    print("      " + _fmt_list(craft_all))
    print()
    print("  • Interstellar object aliases (mapped to primary designations):")
    print("      " + _fmt_list(inter_keys))
    print()
    print("  • Deep-sky/stars by name or catalog IDs with these prefixes:")
    print("      " + _fmt_list(keep_prefixes))
    print()
    print("Data sources & methods:")
    print("  - Deep-sky/stars: SIMBAD for identity/photometry; distances via NED-D")
    print("    cascade (trimmed-mean ? median ? byname HTML mean ? nDistance median),")
    print("    then Hubble-law fallback from redshift or radial velocity when needed.")
    print("  - Planets/Sun: local JPL ephemerides (de440s ? de432s ? builtin),")
    print("    photometry/geometry via JPL Horizons.")
    print(
        "  - Moons/comets/spacecraft: JPL Horizons (robust resolution with fallbacks)."
    )
    print()
    print("Notes:")
    print("  • Distances are reported in parsec with human-readable ly/kly/Mly.")
    print("  • Comets include closest-approach search over a configurable span.")
    print("  • Spacecraft resolver tries names, COSPAR IDs (DES=), SPK-IDs, etc.")
    print('  • Use quotes if your target contains spaces (e.g., "New Horizons").')
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        sys.exit(0)

    target = " ".join(sys.argv[1:]).strip()
    result = fetch_aliases(target)
    if result is None:
        print("No result found.")
        sys.exit(1)

    obj_type = result.get("object_type")
    morph = result.get("morphology")
    type_line = (
        obj_type if not (obj_type == "Galaxy" and morph) else f"{obj_type} ({morph})"
    )
    sec_object = [
        f'Main ID:  {result.get("display_name", result.get("main_id"))}',
        f"Type:     {type_line}",
    ]
    ra = result.get("ra_deg")
    dec = result.get("dec_deg")
    if (not FZASTRO_FAST_LOOKUP) and ra is not None and dec is not None:
        extra = _fetch_iras_nvss_fluxes(ra, dec)
        result.update({k: v for k, v in extra.items() if v is not None})

    def _as_float(x):
        try:
            return float(str(x).strip().split()[0].replace("−", "-"))
        except Exception:
            return None

    z_fix = _as_float(result.get("redshift"))
    rv_fix = _as_float(result.get("radial_velocity_kms"))
    if z_fix is not None and (
        rv_fix is None or abs(rv_fix - z_fix) < 1e-6 or rv_fix < 10.0
    ):
        result["radial_velocity_kms"] = z_fix * 299792.458

    _print_section("OBJECT", sec_object)

    sec_position = []
    ra, dec = result.get("ra_deg"), result.get("dec_deg")
    if ra is not None and dec is not None:
        sec_position.append(f"RA:  {ra:.6f}°")
        sec_position.append(f"Dec: {dec:+.6f}°")

    if result.get("parallax_mas") is not None:
        sec_position.append(f'Parallax: {result["parallax_mas"]:.3f} mas')

    pmra, pmdec = result.get("pmra_masyr"), result.get("pmdec_masyr")
    if pmra is not None or pmdec is not None:
        sra = f"{pmra:.2f}" if pmra is not None else "n/a"
        sdc = f"{pmdec:.2f}" if pmdec is not None else "n/a"
        sec_position.append(f"Proper motion: pmRA={sra} mas/yr, pmDEC={sdc} mas/yr")

    z = _as_float(result.get("redshift"))
    rv = None
    if z is not None:
        rv = z * 299792.458
        result["radial_velocity_kms"] = rv
    else:
        rv = _as_float(result.get("radial_velocity_kms"))

    if z is not None:
        sec_position.append(f"Redshift: {z:.6f}")
    if rv is not None:
        sec_position.append(f"Radial velocity: {rv:.1f} km/s")

    if result.get("distance_au") is not None and result.get("distance_km") is not None:
        sec_position.append(
            f'Δ (Earth distance): {result["distance_au"]:.6f} AU ({result["distance_km"]:,.0f} km)'
        )

    alt = result.get("altitude_km")
    if alt is not None:
        sec_position.append(f"Altitude:           {alt:,.0f} km")

    if result.get("heliocentric_au") is not None:
        sec_position.append(f'r (Heliocentric):   {result["heliocentric_au"]:.6f} AU')

    _print_section("POSITION", sec_position)

    # ==========================================
    # ADD THIS SECTION: Distance Information
    # ==========================================
    sec_distance = []
    dist_pc = result.get("distance_pc")
    if dist_pc is not None:
        ly_str = format_ly_units(dist_pc)
        sec_distance.append(f"Distance (pc): {dist_pc:.4g}")
        sec_distance.append(f"             ({ly_str})")

    method = result.get("distance_method")
    if method:
        sec_distance.append(f"Method:        {method}")

    _print_section("DISTANCE", sec_distance)

    # ==========================================
    # ADD THIS SECTION: Aliases
    # ==========================================
    aliases = result.get("aliases", [])
    if aliases:
        print("[ ALIASES ]")
        # Print first 10, then truncate
        for a in aliases[:10]:
            print(f"  {a}")
        if len(aliases) > 10:
            print(f"  ... and {len(aliases) - 10} more")
        print()

    # ==========================================
    # ADD THIS SECTION: Photometry (Magnitudes)
    # ==========================================
    sec_phot = []

    # Standard magnitudes
    for col in ("mag_V", "mag_G", "mag_B"):
        val = result.get(col)
        if val is not None:
            sec_phot.append(f"{col}: {val:.3f}")

    # IRAS/NVSS fluxes (computed earlier in fetch_aliases but hidden above)
    for col in ("flux_IRAS_12um_Jy", "flux_IRAS_25um_Jy", "flux_1p4GHz_Jy"):
        val = result.get(col)
        if val is not None:
            sec_phot.append(f"{col}: {val:.3f}")

    _print_section("PHOTOMETRY", sec_phot)

    # ==========================================
    # ADD THIS SECTION: Morphology (Galaxies/Nebulae)
    # ==========================================
    morph = result.get("morphology")
    d25 = result.get("d25_maj_arcmin")

    sec_morph = []
    if morph:
        sec_morph.append(f"Morphology: {morph}")
    if d25:
        sec_morph.append(f"D(25) Major: {d25:.3f} arcmin")

    # Only print section if we found data
    if sec_morph:
        _print_section("MORPHOLOGY", sec_morph)

    # ==========================================
    # ADD THIS SECTION: Ephemera (Planets/Spacecraft)
    # ==========================================
    # If result contains raw ephemeris columns, we can show key bits
    if "ephemerides" in result:
        print("[ EPHEMERIS DATA ]")
        for col in ["RA", "DEC", "r", "delta", "V"]:
            if col in result["ephemerides"]["row0"]:
                val = result["ephemerides"]["row0"][col]
                print(f"  {col}: {val}")

    # ==========================================
    # Optional: Debugging JSON (Uncomment if needed)
    # ==========================================
    # import json
    # print("\n[ FULL RESULT JSON ]")
    # print(json.dumps(result, indent=2))

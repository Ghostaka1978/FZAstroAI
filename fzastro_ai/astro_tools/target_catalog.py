from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..config import APP_DIR


TARGET_CATALOG_DB = APP_DIR / "target_catalog.sqlite3"
OPENNGC_SOURCE = "OpenNGC"
BUILTIN_SOURCE = "Curated"


OPENNGC_TYPE_LABELS = {
    "G": "Galaxy",
    "GPair": "Galaxy Pair",
    "GTrpl": "Galaxy Triplet",
    "GGroup": "Galaxy Group",
    "OCl": "Open",
    "GCl": "Globular",
    "Cl+N": "Cluster+Nebula",
    "Neb": "Nebula",
    "PN": "Planetary",
    "DN": "Dark Nebula",
    "EN": "Emission",
    "HII": "Emission",
    "RfN": "Reflection",
    "SNR": "Supernova Remnant",
    "Ast": "Asterism",
    "Dup": "Duplicate",
    "NonEx": "Nonexistent",
    "Other": "Other",
}

_TARGET_GROUPS = {
    "all": (),
    "galaxies": ("galaxy",),
    "nebulae": ("nebula", "emission", "reflection", "dark", "planetary", "supernova"),
    "clusters": ("cluster", "open", "globular"),
    "open clusters": ("open",),
    "globulars": ("globular",),
    "planetary nebulae": ("planetary",),
}


def default_catalog_db_path() -> Path:
    return TARGET_CATALOG_DB


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or TARGET_CATALOG_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS objects (
            name TEXT PRIMARY KEY,
            object_type TEXT NOT NULL DEFAULT '',
            constellation TEXT NOT NULL DEFAULT '',
            ra TEXT NOT NULL DEFAULT '',
            dec TEXT NOT NULL DEFAULT '',
            mag REAL,
            size_deg TEXT,
            width_deg REAL,
            height_deg REAL,
            size_src TEXT,
            source TEXT NOT NULL DEFAULT 'Curated',
            aliases TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_target_objects_source ON objects(source);
        CREATE INDEX IF NOT EXISTS idx_target_objects_type ON objects(object_type);
        CREATE TABLE IF NOT EXISTS catalog_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.commit()


def _legacy_catalog() -> list[dict[str, Any]]:
    from .fzastro import target as legacy_target

    return [dict(row) for row in getattr(legacy_target, "CATALOG", [])]


def _normalise_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "--", "---"}:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalise_text(value: Any) -> str:
    return str(value or "").strip()


def _size_text(
    width_deg: float | None, height_deg: float | None, fallback: Any = ""
) -> str:
    clean = _normalise_text(fallback)
    if clean:
        return clean
    if width_deg is None or height_deg is None:
        return ""
    if abs(width_deg - height_deg) <= 0.0005:
        return f"{width_deg:.3f}°"
    return f"{width_deg:.3f}°×{height_deg:.3f}°"


def _insert_object(conn: sqlite3.Connection, row: dict[str, Any], source: str) -> None:
    name = _normalise_text(row.get("name") or row.get("Name"))
    if not name:
        return
    width_deg = _normalise_float(row.get("width_deg"))
    height_deg = _normalise_float(row.get("height_deg"))
    aliases = row.get("aliases") or row.get("alias") or ""
    if isinstance(aliases, (list, tuple, set)):
        aliases = "; ".join(str(part).strip() for part in aliases if str(part).strip())

    conn.execute(
        """
        INSERT OR REPLACE INTO objects (
            name, object_type, constellation, ra, dec, mag, size_deg,
            width_deg, height_deg, size_src, source, aliases
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            _normalise_text(row.get("type") or row.get("object_type")),
            _normalise_text(row.get("constellation") or row.get("const")),
            _normalise_text(row.get("ra")),
            _normalise_text(row.get("dec")),
            _normalise_float(row.get("mag")),
            _size_text(width_deg, height_deg, row.get("size_deg") or row.get("size")),
            width_deg,
            height_deg,
            _normalise_text(row.get("size_src")),
            source,
            _normalise_text(aliases),
        ),
    )


def seed_builtin_catalog(
    db_path: str | Path | None = None, *, reset: bool = False
) -> int:
    """Create/update the local TARGETS catalog with the curated built-in objects."""
    with _connect(db_path) as conn:
        if reset:
            conn.execute("DELETE FROM objects WHERE source = ?", (BUILTIN_SOURCE,))
        count = 0
        for row in _legacy_catalog():
            _insert_object(conn, row, BUILTIN_SOURCE)
            count += 1
        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES (?, ?)",
            ("builtin_seeded", "1"),
        )
        conn.commit()
        return count


def ensure_catalog(db_path: str | Path | None = None) -> Path:
    path = Path(db_path or TARGET_CATALOG_DB)
    with _connect(path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM objects").fetchone()
        needs_seed = not row or int(row["count"] or 0) == 0
    if needs_seed:
        seed_builtin_catalog(path)
    return path


def catalog_stats(db_path: str | Path | None = None) -> dict[str, Any]:
    path = ensure_catalog(db_path)
    with _connect(path) as conn:
        total = int(
            conn.execute("SELECT COUNT(*) AS count FROM objects").fetchone()["count"]
        )
        sources = {
            str(row["source"]): int(row["count"])
            for row in conn.execute(
                "SELECT source, COUNT(*) AS count FROM objects GROUP BY source ORDER BY source"
            )
        }
        types = {
            str(row["object_type"]): int(row["count"])
            for row in conn.execute(
                "SELECT object_type, COUNT(*) AS count FROM objects "
                "GROUP BY object_type ORDER BY object_type"
            )
        }
    return {"path": str(path), "total": total, "sources": sources, "types": types}


def _matches_type(row_type: str, group: str) -> bool:
    key = str(group or "all").strip().casefold()
    needles = _TARGET_GROUPS.get(key, ())
    if not needles:
        return True
    haystack = str(row_type or "").casefold()
    return any(needle in haystack for needle in needles)


def _passes_source(row_source: str, source_mode: str) -> bool:
    mode = str(source_mode or "auto").strip().casefold()
    src = str(row_source or "").strip().casefold()
    if mode in {"auto", "local", "sqlite", "all"}:
        return True
    if mode in {"builtin", "curated"}:
        return src == BUILTIN_SOURCE.casefold()
    if mode in {"openngc", "opengc"}:
        return src == OPENNGC_SOURCE.casefold()
    return True


def load_catalog_rows(
    *,
    db_path: str | Path | None = None,
    source: str = "auto",
    object_type: str = "All",
    min_size_arcmin: float = 0.0,
    max_mag: float | None = None,
) -> list[tuple[Any, ...]]:
    """Return rows compatible with the legacy TARGETS evaluator."""
    path = ensure_catalog(db_path)
    min_size_deg = max(0.0, float(min_size_arcmin or 0.0) / 60.0)
    rows: list[tuple[Any, ...]] = []
    with _connect(path) as conn:
        for row in conn.execute(
            """
            SELECT name, object_type, constellation, ra, dec, mag, size_deg,
                   size_src, width_deg, height_deg, source
            FROM objects
            WHERE ra <> '' AND dec <> ''
            ORDER BY name COLLATE NOCASE
            """
        ):
            if not _passes_source(row["source"], source):
                continue
            if not _matches_type(row["object_type"], object_type):
                continue
            mag = row["mag"]
            if max_mag is not None and mag is not None and float(mag) > float(max_mag):
                continue
            width = row["width_deg"]
            height = row["height_deg"]
            if min_size_deg > 0:
                largest = max(float(width or 0.0), float(height or 0.0))
                if largest < min_size_deg:
                    continue
            rows.append(
                (
                    str(row["name"]),
                    str(row["object_type"] or ""),
                    str(row["constellation"] or ""),
                    str(row["ra"] or ""),
                    str(row["dec"] or ""),
                    mag,
                    str(row["size_deg"] or ""),
                    str(row["size_src"] or ""),
                    width,
                    height,
                )
            )
    return rows


def _column(row: dict[str, Any], *names: str) -> str:
    lowered = {str(k).casefold(): v for k, v in row.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _deg_from_arcmin(value: Any) -> float | None:
    number = _normalise_float(value)
    if number is None or number <= 0.0:
        return None
    return number / 60.0


def _openngc_type(value: str) -> str:
    clean = str(value or "").strip()
    return OPENNGC_TYPE_LABELS.get(clean, clean or "Other")


def _openngc_name(row: dict[str, Any]) -> str:
    name = _column(row, "Name")
    if name:
        return (
            name.replace("NGC", "NGC ").replace("IC", "IC ").replace("  ", " ").strip()
        )
    ngc = _column(row, "NGC")
    if ngc:
        return f"NGC {ngc}"
    ic = _column(row, "IC")
    if ic:
        return f"IC {ic}"
    messier = _column(row, "M")
    if messier:
        return f"M {messier}"
    return ""


def import_openngc_csv(
    csv_path: str | Path,
    db_path: str | Path | None = None,
    *,
    replace_existing: bool = True,
) -> int:
    """Import an OpenNGC-style semicolon CSV into the local TARGETS catalog.

    Expected columns include Name, Type, RA, Dec, Const, MajAx, MinAx, V-Mag,
    Identifiers, and Common names. Rows without usable coordinates are skipped.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    imported = 0
    with _connect(db_path) as conn:
        if replace_existing:
            conn.execute("DELETE FROM objects WHERE source = ?", (OPENNGC_SOURCE,))

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
            reader = csv.DictReader(handle, delimiter=delimiter)
            for raw in reader:
                name = _openngc_name(raw)
                ra = _column(raw, "RA")
                dec = _column(raw, "Dec", "DEC")
                if not name or not ra or not dec:
                    continue

                width = _deg_from_arcmin(_column(raw, "MajAx", "MajAx_arcmin"))
                height = (
                    _deg_from_arcmin(_column(raw, "MinAx", "MinAx_arcmin")) or width
                )
                mag = _normalise_float(
                    _column(raw, "V-Mag", "B-Mag", "J-Mag", "H-Mag", "K-Mag")
                )
                aliases = "; ".join(
                    part
                    for part in (
                        _column(raw, "Common names", "Common Names"),
                        _column(raw, "Identifiers"),
                    )
                    if part
                )
                size_src = ""
                if width is not None:
                    if height is not None and abs(width - height) > 0.0005:
                        size_src = f"{width * 60.0:.1f}'×{height * 60.0:.1f}'"
                    else:
                        size_src = f"{width * 60.0:.1f}'"

                _insert_object(
                    conn,
                    {
                        "name": name,
                        "type": _openngc_type(_column(raw, "Type")),
                        "constellation": _column(raw, "Const", "Constellation"),
                        "ra": ra,
                        "dec": dec,
                        "mag": mag,
                        "width_deg": width,
                        "height_deg": height,
                        "size_src": size_src,
                        "aliases": aliases,
                    },
                    OPENNGC_SOURCE,
                )
                imported += 1

        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES (?, ?)",
            ("openngc_imported", "1"),
        )
        conn.commit()
    return imported


def object_type_choices() -> list[str]:
    return [
        "All",
        "Galaxies",
        "Nebulae",
        "Clusters",
        "Open clusters",
        "Globulars",
        "Planetary nebulae",
    ]

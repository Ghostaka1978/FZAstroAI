#!/usr/bin/env python3
import io, sys, math, argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from pathlib import Path
from skyfield.api import Loader
from skyfield.framelib import ecliptic_frame


class _NullTextStream:
    def write(self, _text):
        return 0

    def flush(self):
        return None

    def isatty(self):
        return False


def _protect_null_stdio():
    if sys.stdout is None:
        sys.stdout = _NullTextStream()
    if sys.stderr is None:
        sys.stderr = _NullTextStream()


def parse_args():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--dt", default="", type=str)
    p.add_argument("--size", default=2000, type=int)
    p.add_argument("--orbits", default="yes", choices=["yes", "no"])
    p.add_argument("--dist", default="no", choices=["yes", "no"])
    return p.parse_args()


def get_time(ts, dt_str):
    if dt_str:
        try:
            if dt_str.endswith("Z"):
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(dt_str)
        except Exception:
            dt = datetime.now(ZoneInfo("Europe/Berlin"))
    else:
        dt = datetime.now(ZoneInfo("Europe/Berlin"))
    return ts.from_datetime(dt)


def main():
    _protect_null_stdio()
    args = parse_args()

    import os

    DATA_DIR = Path(
        os.environ.get("FZASTRO_SKYFIELD_DIR") or (Path(__file__).parent / ".skyfield")
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(DATA_DIR), verbose=False)

    ts = loader.timescale()
    t = get_time(ts, args.dt)
    eph = loader("de440s.bsp")
    sun = eph["sun"]

    keys = {
        "Mercury": "mercury barycenter",
        "Venus": "venus barycenter",
        "Earth": "earth barycenter",
        "Mars": "mars barycenter",
        "Jupiter": "jupiter barycenter",
        "Saturn": "saturn barycenter",
        "Uranus": "uranus barycenter",
        "Neptune": "neptune barycenter",
    }
    names = list(keys.keys())
    sun = eph["sun"]
    earth = eph["earth barycenter"]

    # Heliocentric positions for plotting
    xyz = []
    for name in names:
        v = (eph[keys[name]] - sun).at(t)
        x, y, z = v.frame_xyz(ecliptic_frame).au
        xyz.append((float(x), float(y), float(z)))

    xs = np.array([p[0] for p in xyz])
    ys = np.array([p[1] for p in xyz])

    # Earth-relative distances
    rs = []
    for name in names:
        v = (eph[keys[name]] - earth).at(t)
        x, y, z = v.frame_xyz(ecliptic_frame).au
        rs.append(math.sqrt(x * x + y * y + z * z))
    rs = np.array(rs)

    dpi = 200
    size_px = int(args.size)
    size_in = size_px / dpi
    fig = plt.figure(figsize=(size_in, size_in), dpi=dpi)
    ax = fig.add_subplot(111)
    ax.set_facecolor((0, 0, 0, 0))
    fig.patch.set_alpha(1)
    fig.patch.set_facecolor((0, 0, 0))

    if args.orbits == "yes":
        a = {
            "Mercury": (0.387098, 0.2056),
            "Venus": (0.723332, 0.0068),
            "Earth": (1.000000, 0.0167),
            "Mars": (1.523679, 0.0934),
            "Jupiter": (5.20260, 0.0489),
            "Saturn": (9.5549, 0.0565),
            "Uranus": (19.2184, 0.0463),
            "Neptune": (30.1104, 0.0097),
        }
        th = np.linspace(0, 2 * np.pi, 1024)

        for n in names:
            sma, e = a[n]
            r = (
                sma * (1 - e * e) / (1 + e * np.cos(th))
            )  # ellipse in polar coords (focus at origin)

            # rotate ellipse so it passes through the current heliocentric position
            i = names.index(n)
            r0 = float(np.hypot(xs[i], ys[i]))  # current distance from Sun
            phi0 = float(np.arctan2(ys[i], xs[i]))  # current angle
            if e > 1e-6:
                cf = (sma * (1 - e * e) / max(r0, 1e-9) - 1) / e
                cf = np.clip(cf, -1.0, 1.0)
                f0 = float(np.arccos(cf))  # true anomaly (principal)
                # choose sign that matches current quadrant
                if np.sign(np.sin(phi0)) != np.sign(np.sin(f0)):
                    f0 = -f0
                delta = phi0 - f0
            else:
                delta = phi0

            X = r * np.cos(th + delta)
            Y = r * np.sin(th + delta)
            ax.plot(X, Y, linewidth=0.9, color=(1, 1, 1, 0.30), zorder=1)

    ax.scatter(
        [0], [0], s=35.3, color="#ffd34d", edgecolors="white", linewidths=0.6, zorder=4
    )

    colors = {
        "Mercury": "#c9c9c9",  # light gray
        "Venus": "#eac14d",  # warm golden yellow
        "Earth": "#0094ff",  # saturated blue
        "Mars": "#e74c3c",  # true red
        "Jupiter": "#d2a679",  # beige brown
        "Saturn": "#f5a6d0",  # pink
        "Uranus": "#bfcad7",  # pale blue-gray
        "Neptune": "#dce233",  # yellow-green
    }
    sizes = {
        "Mercury": 3.5,
        "Venus": 9.7,
        "Earth": 10,
        "Mars": 5.3,
        "Jupiter": 25.9,
        "Saturn": 22.8,
        "Uranus": 17.3,
        "Neptune": 17.1,
    }
    offs = {
        "Mercury": (0.22, 0.18),
        "Venus": (0.22, 0.30),
        "Earth": (0.22, -0.10),
        "Mars": (0.22, -0.28),
        "Jupiter": (0.28, 0.20),
        "Saturn": (0.28, -0.22),
        "Uranus": (0.32, 0.22),
        "Neptune": (0.32, -0.22),
    }

    for i, n in enumerate(names):
        ax.scatter(
            xs[i],
            ys[i],
            s=sizes[n],
            facecolors=colors[n],
            edgecolors="white",
            linewidths=0.6,
            alpha=1.0,
            zorder=3,
            rasterized=False,
        )
        if n not in {"Mercury", "Venus", "Earth", "Mars"}:
            label = f"{n} ({rs[i]:.2f} AU)"
            dx, dy = offs[n]
            ax.text(
                xs[i] + dx,
                ys[i] + dy,
                label,
                fontsize=12,
                ha="left",
                va="bottom",
                color="#ffffff",
                zorder=5,
            )

    handles = []
    for n in ["Mercury", "Venus", "Earth", "Mars"]:
        label = f"{n} ({rs[names.index(n)]:.2f} AU)"
        handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                markersize=8,
                markerfacecolor=colors[n],
                markeredgecolor="white",
                markeredgewidth=0.6,
                label=label,
            )
        )
    ax.legend(
        handles=handles,
        loc="upper left",
        frameon=False,
        fontsize=11,
        labelcolor="#e6e6e6",
    )

    lim = 33.0
    pad = 3.5
    ax.set_xlim(-lim - pad, lim + pad)
    ax.set_ylim(-lim - pad, lim + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.margins(0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", transparent=True)

    plt.close(fig)
    data = buf.getvalue()
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()

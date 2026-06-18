# FZAstro AI Astro Tools Suite

The Astro Tools Suite is the main astronomy and astrophotography workflow area in FZAstro AI v2.3.0. Open it from the main workspace **Apps** menu or the Astro controls. Tools open as tabs in the main app so LOOKUP, SEEING, TARGETS, SUN NOW, N.I.N.A., and chat can stay available together.

## Suite overview

| Tool | Production purpose |
|---|---|
| SITE | Store observing coordinates, elevation, timezone, SQM, Bortle, and source notes. |
| IMAGING | Configure camera preset, focal length, field of view, image size, and rotation. |
| LOOKUP | Search objects such as M31, NGC objects, IC objects, planets, comets, stars, spacecraft, nebulae, and galaxies. |
| SUN NOW | View current NASA/SDO solar imagery with metadata, channel/size controls, and cached fallback. |
| SEEING | Plan observing nights with seeing/transparency, cloud, Moon, astronomical darkness, Bortle context, and nightly scoring. |
| TARGETS | Rank targets for the selected site/date with altitude, type, size, catalog-source, CSV export, and OpenNGC import. |
| SOLAR MAP | Inspect a native 2D solar-system map with zoom/pan, orbit/label/grid toggles, and planet data. |

## SEEING / Astro Night Planner production behavior

SEEING is tuned for practical imaging decisions:

- The top bar shows the current local day/time and the relevant current/tonight night window.
- Forecast points prioritize night and imaging-relevant rows over daytime rows.
- Astronomical-dark rows receive priority; twilight/daylight rows are capped low.
- Cloud cover strongly caps score, so different cloudy nights no longer collapse to identical scores.
- Cards show **BEST SCORE** when astronomical darkness exists, and **NO DARK** when no astronomical-dark forecast points exist.
- Moon periods and astronomical-dark periods remain visible without noisy helper text.
- Bortle tint applies to the SEEING sky-quality bar: 8–9 white/urban, 6–7 yellow, 4–5 green, 2–3 blue, and 1 violet.

## Runtime expectations

- Astro tools should not post their primary UI output to main chat.
- Opening LOOKUP, SUN NOW, SEEING, TARGETS, or SOLAR MAP should not force the main chat to scroll to the bottom.
- Astro tools should use the shared dark palette and open cleanly as workspace tabs when launched from the main app.
- Standalone dialogs should still use shared centered desktop-window defaults with minimize/maximize/close controls.
- Astropy/IERS failures and external provider timeouts should be logged without crashing the app.

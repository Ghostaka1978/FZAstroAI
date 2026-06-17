# FZAstro AI v1.0.0 RC 3 Final Production Notes

RC 3 is the final production release-candidate baseline for Version 1. It packages the Windows desktop app as a clean `fzastro_ai/` application package with root-level launch/build/validation files only.

## Main production focus

The main RC 3 production focus is the **Astro Tools Suite**. The suite is now documented as a first-class workstation area for astrophotography and astronomy planning.

Included Astro tools:

- **SITE** — observing site, elevation, timezone, SQM, and Bortle context.
- **IMAGING** — camera/FOV/framing setup for lookup previews.
- **LOOKUP** — object lookup with result details, sky preview, catalog dropdowns, and distance-ladder transparency.
- **SUN NOW** — NASA/SDO solar image viewer with channel/size selection, metadata, and cached fallback.
- **SEEING** — Astro Night Planner with current/tonight context, 7Timer ASTRO seeing/transparency, Moon periods, astronomical-dark windows, cloud-aware scoring, night-first forecast points, and Bortle-aware top-bar tint.
- **TARGETS** — native target planner with filters, CSV export, and optional local OpenNGC CSV import.
- **SOLAR MAP** — native 2D solar-system map with zoom, pan, orbit/label/grid toggles, Full/Inner/Outer modes, and planet data.

## RC 3 stability notes

- Astropy/IERS live downloads are disabled/hardened so malformed upstream IERS tables do not crash astronomy workflows.
- DDGS/Yandex web-search provider timeouts are handled as warnings instead of fatal app errors.
- Standalone Astro windows should open centered and with normal minimize/maximize/close controls.
- SEEING should avoid noisy helper text, keep useful urban/Bortle context, and score nights differently when cloud cover differs.

## Release label

The About window and docs should show:

```text
FZAstro AI v1.0.0 (Version 1 RC 3 Final Production)
```

## Web Companion addition

RC 3 now includes the Web Companion foundation and polished LAN/mobile workflow:

* LAN / iPad access through the host PC IP
* Token-protected browser interface
* Daily News Brief in the web UI
* Astro Tools toolbar in the web UI
* LOOKUP image rendering
* Site Planner map picker with automatic timezone resolution
* Hidden settings drawer for a cleaner mobile layout

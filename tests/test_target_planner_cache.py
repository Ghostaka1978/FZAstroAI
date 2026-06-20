from fzastro_ai.astro_tools import target_planner


def test_targets_planner_uses_twilight_fallback_when_no_astro_dark():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import numpy as np

    class FakeLegacyTarget:
        @staticmethod
        def Time(values, format=None, scale=None):
            return values

        @staticmethod
        def night_window(anchor, tz, loc, step_min=2):
            return None

        @staticmethod
        def sun_altitudes(times, loc):
            # No astronomical darkness, but the Sun is below -12 degrees for
            # the full sampled block, so TARGETS should still rank objects.
            return np.full(len(times), -13.0, dtype=float)

    FakeLegacyTarget.np = np

    window = target_planner._select_targets_planning_window(
        FakeLegacyTarget,
        datetime(2026, 6, 19, 12, tzinfo=ZoneInfo("Europe/Berlin")),
        ZoneInfo("Europe/Berlin"),
        object(),
    )

    assert window is not None
    assert window["type"] == "nautical_twilight"
    assert window["has_astro_dark"] is False
    assert window["score_cap"] == 70
    assert "No astronomical darkness" in window["note"]


def test_plan_targets_caches_repeated_site_date_filter_requests(monkeypatch):
    target_planner._plan_targets_cached.cache_clear()
    monkeypatch.setattr(
        target_planner,
        "_catalog_cache_token",
        lambda: ("catalog.sqlite3", 123, 456),
    )
    calls = []

    def fake_uncached(location, **kwargs):
        calls.append((dict(location), dict(kwargs)))
        return {
            "ok": True,
            "location": dict(location),
            "picks": [{"name": "M 13"}],
            "nested": {"call": len(calls)},
        }

    monkeypatch.setattr(target_planner, "_plan_targets_uncached", fake_uncached)

    try:
        first = target_planner.plan_targets(
            {"lat": 50.1, "lon": 8.6, "elev": 120, "tz": "Europe/Berlin"},
            date_iso="2026-06-19",
            limit=10,
            min_alt=45,
        )
        first["nested"]["call"] = 999
        second = target_planner.plan_targets(
            {"lat": 50.1, "lon": 8.6, "elev": 120, "tz": "Europe/Berlin"},
            date_iso="2026-06-19",
            limit=10,
            min_alt=45,
        )
    finally:
        target_planner._plan_targets_cached.cache_clear()

    assert len(calls) == 1
    assert second["nested"]["call"] == 1
    assert second["picks"] == [{"name": "M 13"}]

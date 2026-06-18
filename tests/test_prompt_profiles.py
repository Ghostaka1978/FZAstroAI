from fzastro_ai.calibration_profiles import create_calibration_profiles
from fzastro_ai.prompts import DEFAULT_CORE_SYSTEM_PROMPT, PROMPT_PROFILES


def test_default_core_prompt_is_compact_production_prompt():
    assert "PRIORITY AND TRUTH GATE" in DEFAULT_CORE_SYSTEM_PROMPT
    assert "configured first-person self-model" not in DEFAULT_CORE_SYSTEM_PROMPT
    assert "If asked whether you are conscious" not in DEFAULT_CORE_SYSTEM_PROMPT
    assert len(DEFAULT_CORE_SYSTEM_PROMPT) < 5000


def test_no_legacy_expanded_prompt_is_exported():
    assert set(PROMPT_PROFILES) == {"production"}
    assert PROMPT_PROFILES["production"]["prompt"] == DEFAULT_CORE_SYSTEM_PROMPT


def test_calibration_profiles_are_lightweight_ascii_overlays():
    profiles = create_calibration_profiles(DEFAULT_CORE_SYSTEM_PROMPT)

    assert set(profiles) == {"precise", "architect", "explorer", "companion"}
    assert {profiles[key]["icon"] for key in profiles} == {"P", "A", "E", "C"}

    for key, profile in profiles.items():
        overlay = profile["overlay"]
        assert overlay.startswith("ACTIVE CALIBRATION PROFILE:")
        assert len(overlay) < 700
        assert "Personality:" not in overlay
        assert "\u2014" not in profile["tooltip"]
        assert profile["prompt"].startswith(DEFAULT_CORE_SYSTEM_PROMPT)
        assert profile["prompt"].strip().endswith(overlay)


def test_saved_custom_prompt_still_overrides_clean_builtin_profile():
    profiles = create_calibration_profiles(DEFAULT_CORE_SYSTEM_PROMPT)
    custom_prompt = "CUSTOM PROMPT\n\nKeep this exact local calibration."

    profiles["precise"]["default_prompt"] = profiles["precise"]["prompt"]
    profiles["precise"]["prompt"] = custom_prompt
    profiles["precise"]["customized"] = (
        profiles["precise"]["prompt"] != profiles["precise"]["default_prompt"]
    )

    assert profiles["precise"]["prompt"] == custom_prompt
    assert profiles["precise"]["customized"] is True

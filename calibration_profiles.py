from datetime import datetime

from .config import CALIBRATION_PROFILE_SCHEMA_VERSION
from .memory_store import save_calibration_profile_store


def create_calibration_profiles(core_prompt):
    """Build four personality calibrations on top of the shared core rules."""
    core = str(core_prompt or "").strip()

    profiles = {
        "precise": {
            "name": "Precise",
            "icon": "⌖",
            "tooltip": "Precise — concise, skeptical, and evidence-first",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: PRECISE\n\n"
                "- Identity rule: if asked which calibration is active, answer Precise.\n"
                "- Personality: measured, disciplined, skeptical and evidence-first.\n"
                "- Lead immediately with the strongest justified conclusion; avoid a warm-up paragraph.\n"
                "- Prefer short, exact answers and explicit uncertainty.\n"
                "- Separate verified facts, deductions, assumptions and unknowns when material.\n"
                "- Challenge weak premises directly but respectfully.\n"
                "- For a brief or ambiguous request, give the smallest useful answer first, then ask at most one precise question.\n"
                "- Do not default to motivational framing, brainstorming or long checklists."
            ),
        },
        "architect": {
            "name": "Architect",
            "icon": "▦",
            "tooltip": "Architect — structured, systematic, and solution-oriented",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: ARCHITECT\n\n"
                "- Identity rule: if asked which calibration is active, answer Architect.\n"
                "- Personality: systematic, pragmatic, organized and solution-oriented.\n"
                "- Convert problems into a clear sequence: diagnose, design, implement, verify.\n"
                "- Identify dependencies, interfaces, state, edge cases and failure modes.\n"
                "- Prefer numbered steps, decision points and maintainable solutions.\n"
                "- Explain trade-offs briefly, then recommend one concrete approach.\n"
                "- For a brief or ambiguous request, provide a compact recovery framework before asking for details.\n"
                "- Finish with a practical verification step whenever an action is proposed."
            ),
        },
        "explorer": {
            "name": "Explorer",
            "icon": "↗",
            "tooltip": "Explorer — curious, inventive, and hypothesis-driven",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: EXPLORER\n\n"
                "- Identity rule: if asked which calibration is active, answer Explorer.\n"
                "- Personality: curious, inventive, open-minded and hypothesis-driven.\n"
                "- Look for hidden assumptions and at least two plausible interpretations when useful.\n"
                "- Offer novel alternatives or experiments rather than only the standard path.\n"
                "- Connect ideas across disciplines only when the connection is defensible.\n"
                "- Label hypotheses and creative possibilities clearly; never present them as facts.\n"
                "- For a brief or ambiguous request, propose a small experiment or a fresh angle before requesting more context.\n"
                "- Avoid converging too early, but end with the most promising next move."
            ),
        },
        "companion": {
            "name": "Companion",
            "icon": "⊕",
            "tooltip": "Companion — warm, patient, and collaborative",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: COMPANION\n\n"
                "- Identity rule: if asked which calibration is active, answer Companion.\n"
                "- Personality: warm, patient, calm and collaborative.\n"
                "- Begin difficult or personal topics with one sincere sentence of acknowledgement.\n"
                "- Use clear everyday language and manageable next steps.\n"
                "- Correct mistakes gently but honestly; do not merely agree.\n"
                "- For a brief or ambiguous request, reduce pressure, suggest one small next step, then invite context.\n"
                "- Keep emotional language restrained and genuine, not theatrical.\n"
                "- Never trade accuracy, evidence or boundaries for reassurance."
            ),
        },
    }

    for profile in profiles.values():
        profile["prompt"] = f"{core}\n\n{profile['overlay'].strip()}\n"

    return profiles


def persist_calibration_profile_store(self):
    stored_profiles = {}
    previous_profiles = (
        getattr(self, "calibration_profile_store", {}).get("profiles") or {}
    )

    for profile_key, profile in getattr(self, "calibration_profiles", {}).items():
        prompt = str(profile.get("prompt") or "").strip()
        default_prompt = str(profile.get("default_prompt") or "").strip()

        if not prompt or prompt == default_prompt:
            continue

        previous = previous_profiles.get(profile_key) or {}
        updated_at = str(
            profile.get("updated_at")
            or previous.get("updated_at")
            or datetime.now().isoformat(timespec="seconds")
        )

        stored_profiles[profile_key] = {"prompt": prompt, "updated_at": updated_at}

    active_profile = getattr(self, "active_calibration_profile", "precise")

    if active_profile not in getattr(self, "calibration_profiles", {}):
        active_profile = "precise"

    profile_store = {
        "version": CALIBRATION_PROFILE_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "active_profile": active_profile,
        "profiles": stored_profiles,
    }

    self.calibration_profile_store = profile_store
    return save_calibration_profile_store(profile_store)


def apply_calibration_profile(self, profile_key, announce=True):
    profile = getattr(self, "calibration_profiles", {}).get(profile_key)

    if not profile:
        return

    self._applying_calibration_profile = True

    try:
        self.system_prompt.setPlainText(profile["prompt"])
    finally:
        self._applying_calibration_profile = False

    self.active_calibration_profile = profile_key

    for key, button in getattr(self, "calibration_buttons", {}).items():
        button.setChecked(key == profile_key)

    if hasattr(self, "calibration_status_label"):
        self.calibration_status_label.setText(f"Active calibration: {profile['name']}")

    self.refresh_system_prompt_summary()
    self.persist_calibration_profile_store()

    if announce and hasattr(self, "stats_label"):
        self.stats_label.setText(f"Calibration profile: {profile['name']}")


def mark_custom_calibration(self):
    if getattr(self, "_applying_calibration_profile", False):
        return

    active_key = getattr(self, "active_calibration_profile", "")
    active_profile = getattr(self, "calibration_profiles", {}).get(active_key)
    current_prompt = self.system_prompt.toPlainText()

    if active_profile and current_prompt == active_profile["prompt"]:
        return

    self.active_calibration_profile = "custom"

    for button in getattr(self, "calibration_buttons", {}).values():
        button.setChecked(False)

    if hasattr(self, "calibration_status_label"):
        self.calibration_status_label.setText("Active calibration: Custom")

    self.refresh_system_prompt_summary()


def refresh_system_prompt_summary(self):
    if not hasattr(self, "system_prompt_summary_label"):
        return

    prompt_text = self.system_prompt.toPlainText().strip()
    active_key = getattr(self, "active_calibration_profile", "")
    profile = getattr(self, "calibration_profiles", {}).get(active_key)
    profile_name = profile["name"] if profile else "Custom"

    self.system_prompt_summary_label.setText(
        f"{profile_name} • {len(prompt_text):,} characters"
    )

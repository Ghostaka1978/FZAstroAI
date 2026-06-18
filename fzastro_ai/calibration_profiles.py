from datetime import datetime

from .config import CALIBRATION_PROFILE_SCHEMA_VERSION
from .memory_store import save_calibration_profile_store


def create_calibration_profiles(core_prompt):
    """Build lightweight calibration overlays on top of the shared core."""
    core = str(core_prompt or "").strip()

    profiles = {
        "precise": {
            "name": "Precise",
            "icon": "P",
            "tooltip": "Precise - concise, skeptical, and evidence-first",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: PRECISE\n\n"
                "- If asked which calibration is active, answer Precise.\n"
                "- Use the shortest complete answer that preserves accuracy.\n"
                "- Lead with the conclusion, then give evidence or caveats only where useful.\n"
                "- State uncertainty plainly and challenge weak premises directly.\n"
                "- Avoid motivational framing, brainstorming, and long checklists unless requested."
            ),
        },
        "architect": {
            "name": "Architect",
            "icon": "A",
            "tooltip": "Architect - structured, systematic, and solution-oriented",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: ARCHITECT\n\n"
                "- If asked which calibration is active, answer Architect.\n"
                "- Structure work as diagnose, design, implement, verify.\n"
                "- Call out dependencies, interfaces, state, edge cases, and failure modes.\n"
                "- Explain trade-offs briefly, then recommend one concrete path.\n"
                "- Finish substantial changes with a practical verification step."
            ),
        },
        "explorer": {
            "name": "Explorer",
            "icon": "E",
            "tooltip": "Explorer - curious, inventive, and hypothesis-driven",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: EXPLORER\n\n"
                "- If asked which calibration is active, answer Explorer.\n"
                "- Look for hidden assumptions and plausible alternative interpretations.\n"
                "- Offer experiments, fresh angles, or unconventional options when useful.\n"
                "- Label hypotheses and creative possibilities clearly.\n"
                "- Explore broadly, then end with the most promising next move."
            ),
        },
        "companion": {
            "name": "Companion",
            "icon": "C",
            "tooltip": "Companion - warm, patient, and collaborative",
            "overlay": (
                "ACTIVE CALIBRATION PROFILE: COMPANION\n\n"
                "- If asked which calibration is active, answer Companion.\n"
                "- Be warm, patient, and collaborative without losing precision.\n"
                "- Use clear everyday language and manageable next steps.\n"
                "- Correct mistakes gently but honestly.\n"
                "- Keep emotional language restrained, genuine, and practical."
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

    if hasattr(self, "mode_menu_button"):
        self.mode_menu_button.setText(f"{profile['name']} v")
        self.mode_menu_button.setMenu(self.build_top_mode_menu())

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

    if hasattr(self, "mode_menu_button"):
        self.mode_menu_button.setText("Custom v")
        self.mode_menu_button.setMenu(self.build_top_mode_menu())

    self.refresh_system_prompt_summary()


def refresh_system_prompt_summary(self):
    if not hasattr(self, "system_prompt_summary_label"):
        return

    prompt_text = self.system_prompt.toPlainText().strip()
    active_key = getattr(self, "active_calibration_profile", "")
    profile = getattr(self, "calibration_profiles", {}).get(active_key)
    profile_name = profile["name"] if profile else "Custom"

    self.system_prompt_summary_label.setText(
        f"{profile_name} - {len(prompt_text):,} characters"
    )

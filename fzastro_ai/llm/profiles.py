"""Named generation profiles for OpenAI-compatible chat requests."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class GenerationProfile:
    name: str
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    num_predict: int | None = None
    repeat_penalty: float | None = None
    repeat_last_n: int | None = None
    num_ctx: int | None = None
    think: bool | None = None
    top_k: int | None = None
    include_temperature_option: bool = False

    def with_overrides(self, **overrides):
        clean_overrides = {
            key: value for key, value in overrides.items() if value is not None
        }
        return replace(self, **clean_overrides)


GENERATION_PROFILES: dict[str, GenerationProfile] = {
    "chat": GenerationProfile(
        name="chat",
        temperature=0.3,
        top_p=0.95,
        presence_penalty=0.2,
        num_predict=4096,
        repeat_penalty=1.08,
        repeat_last_n=64,
        think=True,
        top_k=20,
    ),
    "vision": GenerationProfile(
        name="vision",
        temperature=0.12,
        top_p=0.90,
        presence_penalty=0.0,
        num_predict=1200,
        repeat_penalty=1.16,
        repeat_last_n=256,
        think=False,
        top_k=20,
    ),
    "router": GenerationProfile(
        name="router",
        temperature=0.0,
        num_ctx=4096,
        think=False,
    ),
    "memory_extract": GenerationProfile(
        name="memory_extract",
        temperature=0.1,
        num_ctx=32768,
        think=False,
    ),
    "daily_news": GenerationProfile(
        name="daily_news",
        temperature=0.3,
        top_p=0.95,
        presence_penalty=0.2,
        num_predict=12000,
        repeat_penalty=1.08,
        repeat_last_n=64,
        think=False,
        top_k=20,
    ),
    "document_exhaustive": GenerationProfile(
        name="document_exhaustive",
        temperature=0.3,
        top_p=0.95,
        presence_penalty=0.2,
        num_predict=12000,
        repeat_penalty=1.08,
        repeat_last_n=64,
        think=False,
        top_k=20,
    ),
    "benchmark": GenerationProfile(
        name="benchmark",
        temperature=0.3,
        num_predict=512,
        repeat_penalty=1.05,
        think=False,
        include_temperature_option=True,
    ),
}


def get_generation_profile(profile):
    if isinstance(profile, GenerationProfile):
        return profile

    clean_name = str(profile or "chat").strip().lower()

    try:
        return GENERATION_PROFILES[clean_name]
    except KeyError as exc:
        raise ValueError(f"Unknown generation profile: {profile}") from exc

"""UTF-8 Water Safety notification copy used by the Home Assistant output adapter."""

from __future__ import annotations

# Source-of-truth notification copy. Must remain valid UTF-8; never ASCII-fold Czech.
WATER_SAFETY_DEFAULT_TITLES: dict[str, str] = {
    "cs": "Controlel – únik vody",
    "en": "Controlel – water leak",
}

WATER_SAFETY_DEFAULT_MESSAGES: dict[str, dict[str, str]] = {
    "water_safety.wet": {
        "cs": "Detekována voda nebo vlhkost v oblasti „{area_name}“.",
        "en": 'Water or moisture detected in area "{area_name}".',
    },
    "water_safety.recovery": {
        "cs": "Vlhkost v oblasti „{area_name}“ již není detekována.",
        "en": 'Moisture in area "{area_name}" is no longer detected.',
    },
    "water_safety.sensor_fault": {
        "cs": "Porucha senzoru vlhkosti v oblasti „{area_name}“.",
        "en": 'Moisture sensor fault in area "{area_name}".',
    },
}

WATER_SAFETY_FALLBACK_MESSAGES: dict[str, dict[str, str]] = {
    "water_safety.wet": {
        "cs": "Detekována voda nebo vlhkost.",
        "en": "Water or moisture detected.",
    },
    "water_safety.recovery": {
        "cs": "Vlhkost již není detekována.",
        "en": "Moisture is no longer detected.",
    },
    "water_safety.sensor_fault": {
        "cs": "Porucha senzoru vlhkosti.",
        "en": "Moisture sensor fault.",
    },
}

# Fragments from the previously corrupted source literals; must never reappear.
WATER_SAFETY_MOJIBAKE_FRAGMENTS: tuple[str, ...] = (
    "Bezpe—",
    "Bezpe─",
    "Ôtů",
    "Ôťů",
    "čÍž",
    "­čĺž",
    "Detekovĺna",
    "Detekov├ína",
)


def water_safety_locale(language: str) -> str:
    return "cs" if language.casefold().startswith("cs") else "en"


def default_water_safety_title(language: str) -> str:
    return WATER_SAFETY_DEFAULT_TITLES[water_safety_locale(language)]


def default_water_safety_message(
    message_code: str | None,
    language: str,
    *,
    area_name: str | None = None,
) -> str:
    if message_code is None:
        raise ValueError("notification requires message_code when custom_message is absent")
    locale = water_safety_locale(language)
    templates = WATER_SAFETY_DEFAULT_MESSAGES.get(message_code)
    fallbacks = WATER_SAFETY_FALLBACK_MESSAGES.get(message_code)
    if templates is None or fallbacks is None:
        raise ValueError(f"unsupported water safety message code: {message_code}")
    cleaned = area_name.strip() if isinstance(area_name, str) else ""
    if cleaned:
        return templates[locale].format(area_name=cleaned)
    return fallbacks[locale]

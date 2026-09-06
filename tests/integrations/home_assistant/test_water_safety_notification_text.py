"""Regression coverage for Water Safety notification wording and UTF-8 encoding."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.controlel.water_safety_messages import (
    WATER_SAFETY_DEFAULT_MESSAGES,
    WATER_SAFETY_DEFAULT_TITLES,
    WATER_SAFETY_FALLBACK_MESSAGES,
    WATER_SAFETY_MOJIBAKE_FRAGMENTS,
    default_water_safety_message,
    default_water_safety_title,
)

ROOT = Path(__file__).resolve().parents[3]


def test_czech_and_english_wet_dry_copy_uses_correct_diacritics() -> None:
    assert default_water_safety_title("cs") == "Controlel – únik vody"
    assert default_water_safety_title("en") == "Controlel – water leak"
    assert (
        default_water_safety_message("water_safety.wet", "cs", area_name="Technická místnost")
        == "Detekována voda nebo vlhkost v oblasti „Technická místnost“."
    )
    assert (
        default_water_safety_message("water_safety.recovery", "cs", area_name="Technická místnost")
        == "Vlhkost v oblasti „Technická místnost“ již není detekována."
    )
    assert (
        default_water_safety_message("water_safety.wet", "en", area_name="Utility room")
        == 'Water or moisture detected in area "Utility room".'
    )
    assert (
        default_water_safety_message("water_safety.recovery", "en", area_name="Utility room")
        == 'Moisture in area "Utility room" is no longer detected.'
    )
    assert default_water_safety_message("water_safety.wet", "cs") == "Detekována voda nebo vlhkost."
    assert default_water_safety_message("water_safety.recovery", "cs") == "Vlhkost již není detekována."


def test_notification_constants_remain_valid_utf8_without_mojibake() -> None:
    corpus = "\n".join(
        [
            *WATER_SAFETY_DEFAULT_TITLES.values(),
            *(value for messages in WATER_SAFETY_DEFAULT_MESSAGES.values() for value in messages.values()),
            *(value for messages in WATER_SAFETY_FALLBACK_MESSAGES.values() for value in messages.values()),
        ]
    )
    encoded = corpus.encode("utf-8")
    assert encoded.decode("utf-8") == corpus
    for fragment in WATER_SAFETY_MOJIBAKE_FRAGMENTS:
        assert fragment not in corpus
    assert "Detekována" in corpus
    assert "únik" in corpus
    assert "již" in corpus
    assert "Controlel – únik vody" in corpus


def test_translation_json_files_parse_as_utf8() -> None:
    for relative in (
        "custom_components/controlel/strings.json",
        "custom_components/controlel/translations/en.json",
        "custom_components/controlel/translations/cs.json",
    ):
        path = ROOT / relative
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        payload = json.loads(text)
        assert isinstance(payload, dict)
        dumped = json.dumps(payload, ensure_ascii=False)
        for fragment in WATER_SAFETY_MOJIBAKE_FRAGMENTS:
            assert fragment not in text
            assert fragment not in dumped
        if relative.endswith("cs.json"):
            assert "úniku vody" in text or "únik vody" in text

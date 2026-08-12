"""Keep the public HA entity reference synchronized with stable descriptors."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
COMPONENT = ROOT / "custom_components" / "controlel"
REFERENCE = ROOT / "docs" / "operations" / "EntityReference.md"
MARKER = re.compile(r"<!-- entity:(sensor|binary_sensor):([^ ]+) -->")
BINARY_DISPLAY_MARKER = re.compile(r"<!-- binary-display:([^: ]+):(yes_no|on_off) -->")


def _descriptor_keys(path: Path, constructor: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != constructor:
            continue
        key = next((item.value for item in node.keywords if item.arg == "key"), None)
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        keys.add(key.value)
    return keys


def test_entity_reference_covers_every_public_entity_definition_exactly_once() -> None:
    expected = {
        *(f"sensor:{key}" for key in _descriptor_keys(COMPONENT / "sensor.py", "ControlelSensorDescription")),
        *(
            f"binary_sensor:{key}"
            for key in _descriptor_keys(
                COMPONENT / "binary_sensor.py",
                "ControlelBinarySensorDescription",
            )
        ),
        "sensor:heating_performance_{zone_id}",
    }
    markers = [f"{platform}:{key}" for platform, key in MARKER.findall(REFERENCE.read_text(encoding="utf-8"))]

    assert len(markers) == len(set(markers)), "EntityReference.md contains duplicate entity markers"
    assert set(markers) == expected


def test_every_public_binary_entity_has_yes_no_documentation_and_translation() -> None:
    expected = _descriptor_keys(
        COMPONENT / "binary_sensor.py",
        "ControlelBinarySensorDescription",
    )
    reference = REFERENCE.read_text(encoding="utf-8")
    classifications = BINARY_DISPLAY_MARKER.findall(reference)
    assert len(classifications) == len(set(classifications))
    assert dict(classifications) == dict.fromkeys(expected, "yes_no")

    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    strings_entities = strings["entity"]["binary_sensor"]
    english_entities = english["entity"]["binary_sensor"]
    assert set(strings_entities) == set(english_entities) == expected
    for key in expected:
        assert strings_entities[key]["state"] == {"on": "Yes", "off": "No"}
        assert english_entities[key] == strings_entities[key]

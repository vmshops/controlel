"""Verify Water Safety integration boundaries against public and candidate core."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from custom_components.controlel.const import INTEGRATION_VERSION

ROOT = Path(__file__).parents[3]
COMPONENT = ROOT / "custom_components" / "controlel"
PUBLIC_CORE_VERSION = "0.16.0"


def test_manifest_pins_public_core_baseline() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["requirements"] == [f"controlel=={PUBLIC_CORE_VERSION}"]
    assert manifest["version"] == INTEGRATION_VERSION


def test_public_core_0160_excludes_water_safety_symbols() -> None:
    if importlib.util.find_spec("controlel.application.water_safety") is not None:
        pytest.skip("editable candidate core shadows the public composition under test")

    frontend_api = importlib.import_module("controlel.frontend_api.v1")
    assert not hasattr(frontend_api, "WaterSafetyEvidenceV1")
    assert importlib.util.find_spec("controlel.infrastructure.home_assistant.water_safety_setup_host") is None


def test_candidate_core_exposes_water_safety_symbols() -> None:
    if importlib.util.find_spec("controlel.application.water_safety") is None:
        pytest.skip("candidate Water Safety core is not installed in this environment")

    frontend_api = importlib.import_module("controlel.frontend_api.v1")
    assert hasattr(frontend_api, "WaterSafetyEvidenceV1")
    assert importlib.util.find_spec("controlel.infrastructure.home_assistant.water_safety_setup_host") is not None


def test_integration_detects_optional_water_core_at_runtime() -> None:
    from custom_components.controlel.core_capabilities import water_safety_core_available

    assert water_safety_core_available() == (importlib.util.find_spec("controlel.application.water_safety") is not None)

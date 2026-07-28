import importlib.metadata
import os
import sys
from pathlib import Path

import pytest
from homeassistant.loader import async_get_integration

import controlel
from custom_components.controlel.const import DOMAIN

ROOT = Path(__file__).parents[4].resolve()
CORE_VERSION = "0.1.0"
INTEGRATION_VERSION = "0.3.1"
FRAMEWORK_COMPOSITION = "CONTROLEL_FRAMEWORK_COMPOSITION"


@pytest.mark.asyncio
async def test_real_loader_accepts_manifest_and_discovers_component(hass) -> None:
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.domain == DOMAIN
    assert str(integration.version) == INTEGRATION_VERSION
    assert integration.manifest["codeowners"] == ["@vmshops"]
    assert integration.manifest["documentation"] == "https://github.com/vmshops/controlel"
    assert integration.manifest["issue_tracker"] == "https://github.com/vmshops/controlel/issues"
    assert integration.manifest["config_flow"] is True
    assert integration.single_config_entry is True
    assert integration.manifest["integration_type"] == "hub"
    assert integration.manifest["iot_class"] == "local_push"
    assert integration.requirements == [f"controlel=={CORE_VERSION}"]
    assert integration.file_path.name == DOMAIN


def test_core_package_matches_framework_composition() -> None:
    composition = os.environ.get(FRAMEWORK_COMPOSITION, "local")
    package_path = Path(controlel.__file__).resolve()
    source_root = (ROOT / "src").resolve()

    assert composition in {"local", "public"}
    assert importlib.metadata.version("controlel") == CORE_VERSION
    assert controlel.__version__ == CORE_VERSION
    if composition == "local":
        assert package_path.is_relative_to(source_root)
    else:
        assert "site-packages" in package_path.as_posix()
        assert not package_path.is_relative_to(ROOT)
        assert source_root not in {Path(entry or ".").resolve() for entry in sys.path}


def test_custom_component_does_not_vendor_core() -> None:
    component = ROOT / "custom_components" / DOMAIN

    assert not (component / "controlel").exists()

import importlib.metadata
import sys
from pathlib import Path

import pytest
from homeassistant.loader import async_get_integration

import controlel
from custom_components.controlel.const import DOMAIN

ROOT = Path(__file__).parents[4].resolve()
INTEGRATION_VERSION = "0.9.0"


@pytest.mark.asyncio
async def test_real_loader_accepts_manifest_and_discovers_component(
    hass,
    manifest_core_requirement: str,
) -> None:
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
    assert integration.requirements == [manifest_core_requirement]
    assert integration.file_path.name == DOMAIN


def test_core_package_matches_framework_composition(
    framework_composition: str,
    expected_framework_core_version: str,
) -> None:
    package_path = Path(controlel.__file__).resolve()
    source_root = (ROOT / "src").resolve()

    assert importlib.metadata.version("controlel") == expected_framework_core_version
    assert controlel.__version__ == expected_framework_core_version
    if framework_composition == "local":
        assert package_path.is_relative_to(source_root)
    else:
        assert "site-packages" in package_path.as_posix()
        assert not package_path.is_relative_to(source_root)
        assert source_root not in {Path(entry or ".").resolve() for entry in sys.path}


def test_custom_component_does_not_vendor_core() -> None:
    component = ROOT / "custom_components" / DOMAIN

    assert not (component / "controlel").exists()

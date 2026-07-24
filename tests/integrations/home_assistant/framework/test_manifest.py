from pathlib import Path

import pytest
from homeassistant.loader import async_get_integration

from custom_components.controlel.const import DOMAIN

ROOT = Path(__file__).parents[4]


@pytest.mark.asyncio
async def test_real_loader_accepts_manifest_and_discovers_component(hass) -> None:
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.domain == DOMAIN
    assert str(integration.version) == "0.1.0"
    assert integration.manifest["codeowners"] == ["@vmshops"]
    assert integration.manifest["documentation"] == "https://github.com/vmshops/controlel"
    assert integration.manifest["config_flow"] is True
    assert integration.single_config_entry is True
    assert integration.manifest["integration_type"] == "hub"
    assert integration.manifest["iot_class"] == "local_push"
    assert integration.requirements == []
    assert integration.file_path.name == DOMAIN


def test_custom_component_does_not_vendor_core() -> None:
    component = ROOT / "custom_components" / DOMAIN

    assert not (component / "controlel").exists()

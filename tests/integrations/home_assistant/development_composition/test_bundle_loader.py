import importlib.metadata
from pathlib import Path

import pytest
from homeassistant.loader import async_get_integration

import controlel

CORE_VERSION = "0.16.0"
INTEGRATION_VERSION = "0.13.0"


@pytest.mark.asyncio
async def test_real_loader_uses_the_bundled_integration_and_matching_core(
    hass,
    hass_config_dir: str,
) -> None:
    integration = await async_get_integration(hass, "controlel")
    component = Path(hass_config_dir).resolve() / "custom_components" / "controlel"
    package_path = Path(controlel.__file__).resolve()

    assert str(integration.version) == INTEGRATION_VERSION
    assert integration.requirements == [f"controlel=={CORE_VERSION}"]
    assert integration.file_path.resolve() == component
    assert (component / "frontend" / "wizard.js").is_file()
    assert importlib.metadata.version("controlel") == CORE_VERSION
    assert controlel.__version__ == CORE_VERSION
    assert "site-packages" in package_path.as_posix()

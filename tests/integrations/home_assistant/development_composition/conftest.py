import io
import os
import zipfile
from pathlib import Path, PurePosixPath

import pytest

COMPOSITION_ENV = "CONTROLEL_DEVELOPMENT_COMPOSITION"


def pytest_configure(config: pytest.Config) -> None:
    """Use the mode required by Home Assistant's async fixtures in this suite."""
    config.option.asyncio_mode = "auto"


@pytest.fixture(scope="session")
def development_composition() -> Path:
    """Return the explicitly selected non-publishable development bundle."""
    configured = os.environ.get(COMPOSITION_ENV)
    if configured is None:
        pytest.skip(f"{COMPOSITION_ENV} is required for development-composition smoke tests")
    bundle = Path(configured).resolve()
    if not bundle.is_file():
        pytest.fail(f"development composition does not exist: {bundle}")
    return bundle


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str, development_composition: Path) -> str:
    """Install the integration from the bundle, not from repository source."""
    component = Path(hass_tmp_config_dir) / "custom_components" / "controlel"
    with zipfile.ZipFile(development_composition, "r") as outer:
        integration_content = outer.read("integration/controlel.zip")
    with zipfile.ZipFile(io.BytesIO(integration_content), "r") as integration:
        for name in integration.namelist():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                pytest.fail(f"unsafe integration path in development composition: {name}")
            destination = component.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(integration.read(name))
    return hass_tmp_config_dir


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integration discovery for every composition test."""

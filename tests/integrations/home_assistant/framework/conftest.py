import json
import os
import tomllib
from collections.abc import Iterator
from pathlib import Path
from shutil import copytree

import pytest

from custom_components.controlel.const import (
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
)

ROOT = Path(__file__).parents[4]
FRAMEWORK_COMPOSITION_ENV = "CONTROLEL_FRAMEWORK_COMPOSITION"
MANIFEST_REQUIREMENT = json.loads(
    (ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8")
)["requirements"][0]
MANIFEST_CORE_VERSION = MANIFEST_REQUIREMENT.removeprefix("controlel==")
with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
    REPOSITORY_CORE_VERSION = tomllib.load(pyproject_file)["project"]["version"]
FRAMEWORK_CORE_VERSION_BY_COMPOSITION = {
    "local": REPOSITORY_CORE_VERSION,
    "public": MANIFEST_CORE_VERSION,
}


def pytest_configure(config: pytest.Config) -> None:
    """Use the mode required by Home Assistant's async fixtures in this suite."""
    config.option.asyncio_mode = "auto"


@pytest.fixture(scope="session")
def framework_composition() -> str:
    """Return the explicitly selected framework package composition."""
    composition = os.environ.get(FRAMEWORK_COMPOSITION_ENV, "local")
    if composition not in FRAMEWORK_CORE_VERSION_BY_COMPOSITION:
        pytest.fail(
            f"{FRAMEWORK_COMPOSITION_ENV} must be one of "
            f"{sorted(FRAMEWORK_CORE_VERSION_BY_COMPOSITION)}, got {composition!r}"
        )
    return composition


@pytest.fixture(scope="session")
def expected_framework_core_version(framework_composition: str) -> str:
    """Return the exact core version selected by the framework composition."""
    return FRAMEWORK_CORE_VERSION_BY_COMPOSITION[framework_composition]


@pytest.fixture(scope="session")
def manifest_core_requirement() -> str:
    """Return the released public core requirement declared by the integration."""
    return MANIFEST_REQUIREMENT


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Expose this repository's custom component to the real HA loader."""
    destination = Path(hass_tmp_config_dir) / "custom_components"
    copytree(ROOT / "custom_components", destination, dirs_exist_ok=True)
    return hass_tmp_config_dir


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integration discovery for every framework test."""


@pytest.fixture
def entry_data() -> dict[str, object]:
    return {
        CONF_SENSOR_ID: "living_room_temperature",
        CONF_SENSOR_NAME: "Living room temperature",
        CONF_TEMPERATURE_ENTITY_ID: "sensor.living_room_temperature",
        CONF_ZONE_ID: "living_room",
        CONF_ZONE_NAME: "Living room",
        CONF_TARGET_TEMPERATURE: 21.0,
        CONF_PRIMARY_MEASUREMENT_MAX_AGE: 300.0,
        CONF_MAX_FUTURE_SKEW: 5.0,
        CONF_INDETERMINATE_GRACE_PERIOD: 60.0,
        CONF_INDETERMINATE_TIMEOUT_ACTION: "disable_heating",
        CONF_ENABLE_SERVICE_DOMAIN: "switch",
        CONF_ENABLE_SERVICE_NAME: "turn_on",
        CONF_ENABLE_TARGET_ENTITY_ID: "switch.boiler",
        CONF_DISABLE_SERVICE_DOMAIN: "switch",
        CONF_DISABLE_SERVICE_NAME: "turn_off",
        CONF_DISABLE_TARGET_ENTITY_ID: "switch.boiler",
    }


@pytest.fixture
def service_calls(hass) -> Iterator[list[tuple[str, dict[str, object]]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    async def record_service(call) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("switch", "turn_on", record_service)
    hass.services.async_register("switch", "turn_off", record_service)
    yield calls
    hass.services.async_remove("switch", "turn_on")
    hass.services.async_remove("switch", "turn_off")

from datetime import timedelta
from math import inf, nan

import pytest

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel.config import (
    HomeAssistantConfigurationError,
    integration_config_from_entry_data,
)
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


def test_reconstructs_one_zone_typed_effective_configuration():
    config = integration_config_from_entry_data(entry_data())

    assert config.sensor_id == SensorId("living_room_temperature")
    assert config.zone_id == ZoneId("living_room")
    assert config.sensor_binding.entity_id == "sensor.living_room_temperature"
    assert config.target_temperature.value == 21.0
    assert config.primary_measurement_max_age == timedelta(minutes=5)
    assert config.max_future_skew == timedelta(seconds=5)
    assert config.indeterminate_grace_period == timedelta(minutes=1)
    assert config.indeterminate_timeout_action is HeatingAction.DISABLE_HEATING
    assert config.heat_source.enable_heating.domain == "switch"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, 0),
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, -1),
        (CONF_MAX_FUTURE_SKEW, -1),
        (CONF_INDETERMINATE_GRACE_PERIOD, -1),
        (CONF_TARGET_TEMPERATURE, nan),
        (CONF_MAX_FUTURE_SKEW, inf),
    ],
)
def test_rejects_invalid_durations_and_non_finite_values(field: str, value: object):
    data = entry_data()
    data[field] = value

    with pytest.raises(HomeAssistantConfigurationError):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_ENABLE_SERVICE_DOMAIN, "Switch"),
        (CONF_ENABLE_SERVICE_NAME, "turn-on"),
        (CONF_ENABLE_TARGET_ENTITY_ID, "not-an-entity"),
        (CONF_TEMPERATURE_ENTITY_ID, "sensor"),
    ],
)
def test_rejects_invalid_home_assistant_identifiers(field: str, value: object):
    data = entry_data()
    data[field] = value

    with pytest.raises(HomeAssistantConfigurationError):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    "field",
    [CONF_ENABLE_SERVICE_DOMAIN, CONF_DISABLE_SERVICE_DOMAIN],
)
def test_rejects_controlel_heat_source_service_domain(field: str):
    data = entry_data()
    data[field] = "controlel"

    with pytest.raises(HomeAssistantConfigurationError, match="own integration"):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    "action",
    [
        HeatingAction.ENABLE_HEATING.value,
        HeatingAction.DISABLE_HEATING.value,
    ],
)
def test_accepts_exact_timeout_actions(action: str):
    data = entry_data()
    data[CONF_INDETERMINATE_TIMEOUT_ACTION] = action

    assert integration_config_from_entry_data(data).indeterminate_timeout_action.value == action


def test_rejects_unsupported_timeout_action():
    data = entry_data()
    data[CONF_INDETERMINATE_TIMEOUT_ACTION] = "observe_only"

    with pytest.raises(HomeAssistantConfigurationError):
        integration_config_from_entry_data(data)


def test_entry_data_is_entirely_serializable_primitives():
    data = entry_data()

    assert all(isinstance(value, str | int | float | bool | type(None)) for value in data.values())

from datetime import timedelta
from math import inf, nan

import pytest

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel.config import (
    HomeAssistantConfigurationError,
    generated_identifier,
    integration_config_from_entry,
    integration_config_from_entry_data,
    merged_entry_configuration,
    normalize_identifier,
    validate_identifier,
)
from custom_components.controlel.const import (
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_SOURCE_CONTROL_MODE,
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
    CONTROL_MODE_CUSTOM,
    CONTROL_MODE_SIMPLE,
    DEFAULT_INDETERMINATE_GRACE_PERIOD,
    DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
    DEFAULT_MAX_FUTURE_SKEW,
    DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
    DEFAULT_TARGET_TEMPERATURE,
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
    assert config.heat_source_control_mode == CONTROL_MODE_SIMPLE
    assert config.controlled_entity_id == "switch.boiler"


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


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Teplota obývacího pokoje", "teplota_obyvaciho_pokoje"),
        ("Living room", "living_room"),
        ("Living---room...sensor", "living_room_sensor"),
        ("  repeated___separators  ", "repeated_separators"),
    ],
)
def test_identifier_normalization(name: str, expected: str):
    assert normalize_identifier(name) == expected
    assert generated_identifier(name, "sensor ID") == expected


@pytest.mark.parametrize("name", ["!!!", "123 room"])
def test_generated_identifier_rejects_empty_or_leading_digit(name: str):
    with pytest.raises(HomeAssistantConfigurationError):
        generated_identifier(name, "sensor ID")


@pytest.mark.parametrize("identifier", ["Living_room", "living-room", "1living_room", "_living_room"])
def test_explicit_identifier_format_is_enforced(identifier: str):
    with pytest.raises(HomeAssistantConfigurationError):
        validate_identifier(identifier, "sensor ID")


def test_legacy_nonconforming_ids_remain_loadable_and_stable():
    legacy = entry_data()
    legacy[CONF_SENSOR_ID] = "Living-Room-Temperature"
    legacy[CONF_ZONE_ID] = "1st-floor"

    config = integration_config_from_entry(legacy, {})

    assert config.sensor_id == SensorId("Living-Room-Temperature")
    assert config.zone_id == ZoneId("1st-floor")


def test_defaults_are_safe_and_expressed_in_runtime_seconds():
    assert DEFAULT_TARGET_TEMPERATURE == 21.0
    assert DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE == 900.0
    assert DEFAULT_MAX_FUTURE_SKEW == 30.0
    assert DEFAULT_INDETERMINATE_GRACE_PERIOD == 120.0
    assert DEFAULT_INDETERMINATE_TIMEOUT_ACTION == "disable_heating"


def test_options_override_mutable_legacy_data_but_never_stable_ids():
    data = entry_data()
    options = {
        CONF_SENSOR_ID: "replacement_sensor",
        CONF_ZONE_ID: "replacement_zone",
        CONF_SENSOR_NAME: "Renamed sensor",
        CONF_TARGET_TEMPERATURE: 22.5,
    }

    merged = merged_entry_configuration(data, options)
    config = integration_config_from_entry(data, options)

    assert merged[CONF_SENSOR_ID] == data[CONF_SENSOR_ID]
    assert merged[CONF_ZONE_ID] == data[CONF_ZONE_ID]
    assert config.sensor_id == SensorId("living_room_temperature")
    assert config.zone_id == ZoneId("living_room")
    assert config.sensor_name == "Renamed sensor"
    assert config.target_temperature.value == 22.5


def test_empty_options_preserve_legacy_entry_exactly():
    legacy = entry_data()

    assert merged_entry_configuration(legacy, {}) == legacy
    assert integration_config_from_entry(legacy, {}) == integration_config_from_entry_data(legacy)


def test_simple_mode_derives_standard_switch_bindings():
    data = entry_data()
    data.update(
        {
            CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_SIMPLE,
            CONF_CONTROLLED_ENTITY_ID: "switch.heat_pump",
            CONF_ENABLE_SERVICE_DOMAIN: "ignored",
            CONF_DISABLE_SERVICE_DOMAIN: "ignored",
        }
    )

    config = integration_config_from_entry_data(data)

    assert config.heat_source.enable_heating.domain == "switch"
    assert config.heat_source.enable_heating.service == "turn_on"
    assert config.heat_source.disable_heating.service == "turn_off"
    assert config.heat_source.enable_heating.target_entity_id == "switch.heat_pump"
    assert config.heat_source.disable_heating.target_entity_id == "switch.heat_pump"


def test_advanced_mode_preserves_separate_bindings():
    data = entry_data()
    data.update(
        {
            CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_CUSTOM,
            CONF_ENABLE_SERVICE_DOMAIN: "climate",
            CONF_ENABLE_SERVICE_NAME: "set_hvac_mode",
            CONF_ENABLE_TARGET_ENTITY_ID: "climate.boiler",
            CONF_DISABLE_SERVICE_DOMAIN: "input_boolean",
            CONF_DISABLE_SERVICE_NAME: "turn_off",
            CONF_DISABLE_TARGET_ENTITY_ID: "input_boolean.boiler_permission",
        }
    )

    config = integration_config_from_entry_data(data)

    assert config.heat_source_control_mode == CONTROL_MODE_CUSTOM
    assert config.controlled_entity_id is None
    assert config.heat_source.enable_heating.domain == "climate"
    assert config.heat_source.disable_heating.domain == "input_boolean"

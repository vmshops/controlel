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
    CONF_DEBUG_DURATION,
    CONF_DEBUG_UNTIL_CHANGED,
    CONF_DIAGNOSTIC_PROFILE,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID,
    CONF_HEAT_DELIVERY_ASSIST_POLICY,
    CONF_HEAT_DELIVERY_ASSIST_TARGET,
    CONF_HEAT_DELIVERY_MODE,
    CONF_HEAT_DELIVERY_OWNERSHIP,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_NOTIFICATIONS,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONTROL_MODE_CUSTOM,
    CONTROL_MODE_SIMPLE,
    DEFAULT_DEBUG_DURATION,
    DEFAULT_DIAGNOSTIC_PROFILE,
    DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION,
    DEFAULT_INDETERMINATE_GRACE_PERIOD,
    DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
    DEFAULT_MAX_FUTURE_SKEW,
    DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
    DEFAULT_TARGET_TEMPERATURE,
    HEAT_DELIVERY_ASSIST_ALWAYS,
    HEAT_DELIVERY_MODE_SETPOINT_ASSIST,
    HEAT_DELIVERY_MODE_UNMANAGED,
    HEAT_DELIVERY_OWNERSHIP_CONTROLEL,
    LEGACY_DIAGNOSTIC_PROFILE,
    LEGACY_HEAT_DEMAND_CONFIRMATION_DURATION,
    MAX_HEAT_DEMAND_CONFIRMATION_DURATION,
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


def test_legacy_031_entry_missing_protection_settings_retains_zero_behavior():
    data = entry_data()
    assert CONF_HEATING_TURN_ON_DIFFERENTIAL not in data
    assert CONF_HEATING_TURN_OFF_DIFFERENTIAL not in data
    assert CONF_MINIMUM_HEATING_ON_TIME not in data
    assert CONF_MINIMUM_HEATING_OFF_TIME not in data

    config = integration_config_from_entry_data(data)

    assert config.sensor_id == SensorId("living_room_temperature")
    assert config.zone_id == ZoneId("living_room")
    assert config.sensor_binding.entity_id == "sensor.living_room_temperature"
    assert config.target_temperature.value == 21.0
    assert config.primary_measurement_max_age == timedelta(minutes=5)
    assert config.max_future_skew == timedelta(seconds=5)
    assert config.indeterminate_grace_period == timedelta(minutes=1)
    assert config.indeterminate_timeout_action is HeatingAction.DISABLE_HEATING
    assert config.heating_turn_on_differential == 0.0
    assert config.heating_turn_off_differential == 0.0
    assert config.minimum_heating_on_time == timedelta(0)
    assert config.minimum_heating_off_time == timedelta(0)
    assert config.heat_demand_confirmation_duration == timedelta(0)
    assert config.diagnostic_profile == "detailed"
    assert config.debug_duration == timedelta(minutes=60)
    assert config.configured_debug_duration == timedelta(minutes=60)
    assert config.heat_source.enable_heating.domain == "switch"
    assert config.heat_source_control_mode == CONTROL_MODE_SIMPLE
    assert config.controlled_entity_id == "switch.boiler"
    assert config.heat_delivery_mode == HEAT_DELIVERY_MODE_UNMANAGED
    assert config.heat_delivery_actuator_entity_id is None
    assert config.notification_policy.enabled is False
    assert config.notification_policy.recipients == ()


def test_notification_configuration_is_modular_bounded_and_typed() -> None:
    data = entry_data()
    data[CONF_NOTIFICATIONS] = {
        "enabled": True,
        "recipients": [
            {
                "recipient_id": "family_phone",
                "transport": "home_assistant_notify",
                "target": "notify.family_phone",
                "minimum_level": "detailed",
                "categories": ["runtime", "supervision"],
            }
        ],
        "maximum_per_window": 4,
        "rate_window_seconds": 120,
        "critical_maximum_per_window": 30,
        "critical_rate_window_seconds": 180,
        "history_capacity": 250,
    }

    policy = integration_config_from_entry_data(data).notification_policy

    assert policy.enabled is True
    assert policy.maximum_per_window == 4
    assert policy.rate_window == timedelta(minutes=2)
    assert policy.critical_maximum_per_window == 30
    assert policy.critical_rate_window == timedelta(minutes=3)
    assert policy.history_capacity == 250
    assert policy.recipients[0].recipient_id == "family_phone"
    assert policy.recipients[0].target == "notify.family_phone"
    assert [category.value for category in policy.recipients[0].categories] == ["runtime", "supervision"]


def test_notification_configuration_rejects_unknown_transport_and_non_notify_target() -> None:
    data = entry_data()
    recipient = {
        "recipient_id": "phone",
        "transport": "email",
        "target": "notify.phone",
    }
    data[CONF_NOTIFICATIONS] = {"enabled": True, "recipients": [recipient]}
    with pytest.raises(HomeAssistantConfigurationError, match="transport is invalid"):
        integration_config_from_entry_data(data)
    recipient["transport"] = "home_assistant_notify"
    recipient["target"] = "switch.boiler"
    with pytest.raises(HomeAssistantConfigurationError, match="must be a notify service"):
        integration_config_from_entry_data(data)


def test_notification_configuration_rejects_duplicate_enabled_target_bindings() -> None:
    data = entry_data()
    data[CONF_NOTIFICATIONS] = {
        "enabled": True,
        "recipients": [
            {
                "recipient_id": "phone_primary",
                "transport": "home_assistant_notify",
                "target": "notify.phone",
            },
            {
                "recipient_id": "phone_duplicate",
                "transport": "home_assistant_notify",
                "target": "notify.phone",
            },
        ],
    }

    with pytest.raises(HomeAssistantConfigurationError, match="transport and target bindings must be unique"):
        integration_config_from_entry_data(data)


def test_notification_configuration_rejects_duplicate_recipient_ids_and_excess_recipients() -> None:
    data = entry_data()
    recipient = {
        "recipient_id": "phone",
        "transport": "home_assistant_notify",
        "target": "notify.phone",
    }
    duplicate = dict(recipient, target="notify.tablet")
    data[CONF_NOTIFICATIONS] = {"enabled": True, "recipients": [recipient, duplicate]}
    with pytest.raises(HomeAssistantConfigurationError, match="recipient IDs must be unique"):
        integration_config_from_entry_data(data)

    data[CONF_NOTIFICATIONS] = {
        "enabled": True,
        "recipients": [
            dict(recipient, recipient_id=f"recipient_{index}", target=f"notify.target_{index}") for index in range(17)
        ],
    }
    with pytest.raises(HomeAssistantConfigurationError, match="must not exceed 16"):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    "notifications",
    [
        "invalid",
        {"enabled": "yes", "recipients": []},
        {"enabled": True, "recipients": "notify.phone"},
        {
            "enabled": True,
            "recipients": [
                {
                    "recipient_id": "phone",
                    "transport": "home_assistant_notify",
                    "target": "notify.phone",
                    "minimum_level": "unknown",
                }
            ],
        },
        {
            "enabled": True,
            "recipients": [
                {
                    "recipient_id": "phone",
                    "transport": "home_assistant_notify",
                    "target": "notify.phone",
                    "categories": ["unknown"],
                }
            ],
        },
    ],
)
def test_malformed_persisted_notification_configuration_fails_safely(notifications: object) -> None:
    data = entry_data()
    data[CONF_NOTIFICATIONS] = notifications

    with pytest.raises(HomeAssistantConfigurationError):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_per_window", 0),
        ("maximum_per_window", 101),
        ("rate_window_seconds", 0),
        ("rate_window_seconds", 86_401),
        ("critical_maximum_per_window", 0),
        ("critical_maximum_per_window", 201),
        ("critical_rate_window_seconds", 0),
        ("critical_rate_window_seconds", 86_401),
        ("history_capacity", 0),
        ("history_capacity", 1_001),
    ],
)
def test_notification_configuration_rejects_out_of_range_limits(field: str, value: object) -> None:
    data = entry_data()
    data[CONF_NOTIFICATIONS] = {"enabled": True, "recipients": [], field: value}

    with pytest.raises(HomeAssistantConfigurationError, match="must be between"):
        integration_config_from_entry_data(data)


@pytest.mark.parametrize(
    "limits",
    [
        {
            "maximum_per_window": 1,
            "rate_window_seconds": 1,
            "critical_maximum_per_window": 1,
            "critical_rate_window_seconds": 1,
            "history_capacity": 1,
        },
        {
            "maximum_per_window": 100,
            "rate_window_seconds": 86_400,
            "critical_maximum_per_window": 200,
            "critical_rate_window_seconds": 86_400,
            "history_capacity": 1_000,
        },
    ],
)
def test_notification_configuration_accepts_hard_limit_boundaries(limits: dict[str, int]) -> None:
    data = entry_data()
    data[CONF_NOTIFICATIONS] = {"enabled": True, "recipients": [], **limits}

    policy = integration_config_from_entry_data(data).notification_policy

    assert policy.maximum_per_window == limits["maximum_per_window"]
    assert policy.critical_maximum_per_window == limits["critical_maximum_per_window"]
    assert policy.history_capacity == limits["history_capacity"]


def test_reconstructs_setpoint_assist_without_changing_config_entry_version() -> None:
    data = entry_data()
    data.update(
        {
            CONF_HEAT_DELIVERY_MODE: HEAT_DELIVERY_MODE_SETPOINT_ASSIST,
            CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID: "climate.bedroom_trv",
            CONF_HEAT_DELIVERY_OWNERSHIP: HEAT_DELIVERY_OWNERSHIP_CONTROLEL,
            CONF_HEAT_DELIVERY_ASSIST_POLICY: HEAT_DELIVERY_ASSIST_ALWAYS,
            CONF_HEAT_DELIVERY_ASSIST_TARGET: 30,
        }
    )
    config = integration_config_from_entry_data(data)
    assert config.heat_delivery_configuration.actuator_entity_id == "climate.bedroom_trv"
    assert config.heat_delivery_configuration.assist_target_temperature == 30


def test_setpoint_assist_rejects_missing_or_non_climate_actuator() -> None:
    data = entry_data()
    data.update(
        {
            CONF_HEAT_DELIVERY_MODE: HEAT_DELIVERY_MODE_SETPOINT_ASSIST,
            CONF_HEAT_DELIVERY_OWNERSHIP: HEAT_DELIVERY_OWNERSHIP_CONTROLEL,
        }
    )
    with pytest.raises(HomeAssistantConfigurationError, match="requires an actuator"):
        integration_config_from_entry_data(data)
    data[CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID] = "switch.not_a_climate"
    with pytest.raises(HomeAssistantConfigurationError, match="must be a climate"):
        integration_config_from_entry_data(data)


def test_reconstructs_explicit_hysteresis_and_anti_cycling_configuration():
    data = entry_data()
    data.update(
        {
            CONF_HEATING_TURN_ON_DIFFERENTIAL: 0.3,
            CONF_HEATING_TURN_OFF_DIFFERENTIAL: 0.1,
            CONF_MINIMUM_HEATING_ON_TIME: 600,
            CONF_MINIMUM_HEATING_OFF_TIME: 300,
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 120,
        }
    )

    config = integration_config_from_entry_data(data)

    assert config.heating_turn_on_differential == 0.3
    assert config.heating_turn_off_differential == 0.1
    assert config.minimum_heating_on_time == timedelta(minutes=10)
    assert config.minimum_heating_off_time == timedelta(minutes=5)
    assert config.heat_demand_confirmation_duration == timedelta(minutes=2)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, 0),
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, -1),
        (CONF_MAX_FUTURE_SKEW, -1),
        (CONF_INDETERMINATE_GRACE_PERIOD, -1),
        (CONF_TARGET_TEMPERATURE, nan),
        (CONF_MAX_FUTURE_SKEW, inf),
        (CONF_HEATING_TURN_ON_DIFFERENTIAL, -0.1),
        (CONF_HEATING_TURN_OFF_DIFFERENTIAL, nan),
        (CONF_MINIMUM_HEATING_ON_TIME, -1),
        (CONF_MINIMUM_HEATING_OFF_TIME, inf),
        (CONF_HEAT_DEMAND_CONFIRMATION_DURATION, nan),
        (CONF_HEAT_DEMAND_CONFIRMATION_DURATION, -1),
        (
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
            MAX_HEAT_DEMAND_CONFIRMATION_DURATION + 1,
        ),
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
    assert DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION == 120.0
    assert LEGACY_HEAT_DEMAND_CONFIRMATION_DURATION == 0.0
    assert DEFAULT_DIAGNOSTIC_PROFILE == "basic"
    assert LEGACY_DIAGNOSTIC_PROFILE == "detailed"
    assert DEFAULT_DEBUG_DURATION == 3600.0


def test_040_entry_missing_profile_resolves_detailed_without_mutation() -> None:
    data = entry_data()
    data.update(
        {
            CONF_HEATING_TURN_ON_DIFFERENTIAL: 0.3,
            CONF_HEATING_TURN_OFF_DIFFERENTIAL: 0.1,
            CONF_MINIMUM_HEATING_ON_TIME: 600.0,
            CONF_MINIMUM_HEATING_OFF_TIME: 300.0,
        }
    )
    original = dict(data)

    first_load = integration_config_from_entry(data, {})
    restarted = integration_config_from_entry(data, {})

    assert first_load.diagnostic_profile == "detailed"
    assert restarted.diagnostic_profile == "detailed"
    assert data == original
    assert CONF_DIAGNOSTIC_PROFILE not in data


@pytest.mark.parametrize("profile", ["basic", "detailed"])
def test_explicit_profile_is_preserved_exactly(profile: str) -> None:
    data = entry_data()
    data[CONF_DIAGNOSTIC_PROFILE] = profile

    assert integration_config_from_entry_data(data).diagnostic_profile == profile


def test_regulation_configuration_is_identical_across_diagnostic_profiles() -> None:
    configurations = []
    for profile in ("basic", "detailed", "debug"):
        data = entry_data()
        data[CONF_DIAGNOSTIC_PROFILE] = profile
        configurations.append(integration_config_from_entry_data(data))

    first = configurations[0]
    for candidate in configurations[1:]:
        assert candidate.zone_control == first.zone_control
        assert candidate.heat_source_configuration == first.heat_source_configuration
        assert candidate.max_future_skew == first.max_future_skew
        assert candidate.indeterminate_grace_period == first.indeterminate_grace_period
        assert candidate.indeterminate_timeout_action is first.indeterminate_timeout_action


def test_debug_profile_supports_bounded_and_manual_duration() -> None:
    bounded = entry_data()
    bounded.update(
        {
            CONF_DIAGNOSTIC_PROFILE: "debug",
            CONF_DEBUG_DURATION: 1800.0,
            CONF_DEBUG_UNTIL_CHANGED: False,
        }
    )
    manual = dict(bounded)
    manual[CONF_DEBUG_UNTIL_CHANGED] = True

    bounded_config = integration_config_from_entry_data(bounded)
    manual_config = integration_config_from_entry_data(manual)

    assert bounded_config.diagnostic_profile == "debug"
    assert bounded_config.debug_duration == timedelta(minutes=30)
    assert manual_config.diagnostic_profile == "debug"
    assert manual_config.debug_duration is None
    assert manual_config.configured_debug_duration == timedelta(minutes=30)


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


def test_normalized_zone_and_heat_source_groups_preserve_flat_entry_contract():
    data = entry_data()
    data[CONF_HEATING_TURN_ON_DIFFERENTIAL] = 0.3
    data[CONF_HEATING_TURN_OFF_DIFFERENTIAL] = 0.1
    data[CONF_MINIMUM_HEATING_ON_TIME] = 600.0
    data[CONF_MINIMUM_HEATING_OFF_TIME] = 300.0
    data[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] = 92.5

    config = integration_config_from_entry_data(data)
    zone = config.zone_control
    source = config.heat_source_configuration

    assert zone.zone_id is config.zone_id
    assert zone.sensor_id is config.sensor_id
    assert zone.target_temperature is config.target_temperature
    assert zone.heating_turn_on_differential == 0.3
    assert zone.heating_turn_off_differential == 0.1
    assert zone.heat_demand_confirmation_duration == timedelta(seconds=92.5)
    assert source.binding is config.heat_source
    assert source.minimum_heating_on_time == timedelta(minutes=10)
    assert source.minimum_heating_off_time == timedelta(minutes=5)
    assert merged_entry_configuration(data, {}) == data


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

import json
import logging

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfTemperature,
)
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controlel.const import (
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DEBUG_DURATION,
    CONF_DEBUG_DURATION_MINUTES,
    CONF_DEBUG_UNTIL_CHANGED,
    CONF_DIAGNOSTIC_PROFILE,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_GRACE_PERIOD_MINUTES,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_OFF_TIME_MINUTES,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_MINIMUM_HEATING_ON_TIME_MINUTES,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_SHOW_ADVANCED,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONTROL_MODE_CUSTOM,
    CONTROL_MODE_SIMPLE,
    DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION,
    DIAGNOSTIC_PROFILE_BASIC,
    DIAGNOSTIC_PROFILE_DETAILED,
    DOMAIN,
)


def _schema_fields(result) -> dict[str, object]:
    return {marker.schema: validator for marker, validator in result["data_schema"].schema.items()}


def _schema_defaults(result) -> dict[str, object]:
    defaults = {}
    for marker in result["data_schema"].schema:
        if marker.default is not None:
            try:
                defaults[marker.schema] = marker.default()
            except TypeError:
                pass
    return defaults


def _basic_input(entry_data, **updates) -> dict[str, object]:
    result = {
        CONF_ZONE_NAME: entry_data[CONF_ZONE_NAME],
        CONF_SENSOR_NAME: entry_data[CONF_SENSOR_NAME],
        CONF_TEMPERATURE_ENTITY_ID: entry_data[CONF_TEMPERATURE_ENTITY_ID],
        CONF_TARGET_TEMPERATURE: entry_data[CONF_TARGET_TEMPERATURE],
        CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES: (
            entry_data.get(
                CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
                DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION,
            )
            / 60
        ),
        CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_SIMPLE,
        CONF_CONTROLLED_ENTITY_ID: entry_data[CONF_ENABLE_TARGET_ENTITY_ID],
        CONF_SHOW_ADVANCED: False,
    }
    result.update(updates)
    return result


def _advanced_input(entry_data, **updates) -> dict[str, object]:
    result = {
        CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES: (entry_data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] / 60),
        CONF_MAX_FUTURE_SKEW: entry_data[CONF_MAX_FUTURE_SKEW],
        CONF_INDETERMINATE_GRACE_PERIOD_MINUTES: (entry_data[CONF_INDETERMINATE_GRACE_PERIOD] / 60),
        CONF_INDETERMINATE_TIMEOUT_ACTION: entry_data[CONF_INDETERMINATE_TIMEOUT_ACTION],
    }
    result.update(updates)
    return result


def _options_basic_input(entry_data, **updates) -> dict[str, object]:
    result = _basic_input(entry_data, **updates)
    result[CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES] = (
        entry_data.get(CONF_HEAT_DEMAND_CONFIRMATION_DURATION, 0.0) / 60
    )
    result.pop(CONF_SHOW_ADVANCED)
    return result


def _set_temperature_state(hass, entity_id: str, state: str = "20.5") -> None:
    hass.states.async_set(
        entity_id,
        state,
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )


@pytest.mark.asyncio
async def test_user_step_has_basic_defaults_and_filtered_selectors(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    fields = _schema_fields(result)
    assert set(fields) == {
        CONF_ZONE_NAME,
        CONF_SENSOR_NAME,
        CONF_TEMPERATURE_ENTITY_ID,
        CONF_TARGET_TEMPERATURE,
        CONF_HEATING_TURN_ON_DIFFERENTIAL,
        CONF_HEATING_TURN_OFF_DIFFERENTIAL,
        CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES,
        CONF_HEAT_SOURCE_CONTROL_MODE,
        CONF_CONTROLLED_ENTITY_ID,
        CONF_SHOW_ADVANCED,
    }
    temperature_selector = fields[CONF_TEMPERATURE_ENTITY_ID]
    assert isinstance(temperature_selector, selector.EntitySelector)
    assert temperature_selector.config["filter"] == [{"domain": ["sensor"], "device_class": ["temperature"]}]
    switch_selector = fields[CONF_CONTROLLED_ENTITY_ID]
    assert isinstance(switch_selector, selector.EntitySelector)
    assert switch_selector.config["domain"] == ["switch"]
    defaults = _schema_defaults(result)
    assert defaults[CONF_TARGET_TEMPERATURE] == 21.0
    assert defaults[CONF_HEATING_TURN_ON_DIFFERENTIAL] == 0.3
    assert defaults[CONF_HEATING_TURN_OFF_DIFFERENTIAL] == 0.1
    assert defaults[CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES] == 2.0
    assert defaults[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_SIMPLE
    assert defaults[CONF_SHOW_ADVANCED] is False


@pytest.mark.asyncio
async def test_basic_input_generates_ids_and_stores_mutable_options(hass, entry_data) -> None:
    entry_data[CONF_ZONE_NAME] = "Patro 1"
    entry_data[CONF_SENSOR_NAME] = "Teplota obývacího pokoje"
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(entry_data),
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Patro 1"
    assert result["data"] == {
        CONF_SENSOR_ID: "teplota_obyvaciho_pokoje",
        CONF_ZONE_ID: "patro_1",
    }
    assert result["options"][CONF_PRIMARY_MEASUREMENT_MAX_AGE] == 900.0
    assert result["options"][CONF_MAX_FUTURE_SKEW] == 30.0
    assert result["options"][CONF_INDETERMINATE_GRACE_PERIOD] == 120.0
    assert result["options"][CONF_INDETERMINATE_TIMEOUT_ACTION] == "disable_heating"
    assert result["options"][CONF_HEATING_TURN_ON_DIFFERENTIAL] == 0.3
    assert result["options"][CONF_HEATING_TURN_OFF_DIFFERENTIAL] == 0.1
    assert result["options"][CONF_MINIMUM_HEATING_ON_TIME] == 600.0
    assert result["options"][CONF_MINIMUM_HEATING_OFF_TIME] == 300.0
    assert result["options"][CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == 120.0
    assert result["options"][CONF_DIAGNOSTIC_PROFILE] == DIAGNOSTIC_PROFILE_BASIC
    assert result["options"][CONF_DEBUG_DURATION] == 3600.0
    assert result["options"][CONF_DEBUG_UNTIL_CHANGED] is False
    assert result["options"][CONF_CONTROLLED_ENTITY_ID] == entry_data[CONF_ENABLE_TARGET_ENTITY_ID]
    json.dumps(result["data"])
    json.dumps(result["options"])


@pytest.mark.asyncio
async def test_advanced_initial_flow_accepts_explicit_stable_ids(hass, entry_data) -> None:
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    advanced = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(entry_data, **{CONF_SHOW_ADVANCED: True}),
    )

    result = await hass.config_entries.flow.async_configure(
        advanced["flow_id"],
        _advanced_input(
            entry_data,
            **{
                CONF_SENSOR_ID: "explicit_sensor",
                CONF_ZONE_ID: "explicit_zone",
            },
        ),
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SENSOR_ID: "explicit_sensor",
        CONF_ZONE_ID: "explicit_zone",
    }


@pytest.mark.parametrize(
    ("sensor_id", "zone_id", "error_field"),
    [
        ("Invalid-ID", "living_room", CONF_SENSOR_ID),
        ("living_room_temperature", "1st_floor", CONF_ZONE_ID),
    ],
)
@pytest.mark.asyncio
async def test_advanced_initial_flow_rejects_invalid_explicit_ids(
    hass,
    entry_data,
    sensor_id,
    zone_id,
    error_field,
) -> None:
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    advanced = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(entry_data, **{CONF_SHOW_ADVANCED: True}),
    )

    result = await hass.config_entries.flow.async_configure(
        advanced["flow_id"],
        _advanced_input(
            entry_data,
            **{CONF_SENSOR_ID: sensor_id, CONF_ZONE_ID: zone_id},
        ),
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"][error_field].startswith("invalid_")


@pytest.mark.asyncio
async def test_basic_flow_reports_name_when_generated_id_would_be_invalid(
    hass,
    entry_data,
) -> None:
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(
            entry_data,
            **{CONF_SENSOR_NAME: "123 !!!"},
        ),
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_SENSOR_NAME: "cannot_generate_id"}


@pytest.mark.asyncio
async def test_custom_service_mode_preserves_different_bindings(hass, entry_data) -> None:
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    advanced = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _options_basic_input(
            entry_data,
            **{CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_CUSTOM},
        ),
    )
    custom = _advanced_input(
        entry_data,
        **{
            CONF_ENABLE_SERVICE_DOMAIN: "climate",
            CONF_ENABLE_SERVICE_NAME: "set_hvac_mode",
            CONF_ENABLE_TARGET_ENTITY_ID: "climate.boiler",
            CONF_DISABLE_SERVICE_DOMAIN: "input_boolean",
            CONF_DISABLE_SERVICE_NAME: "turn_off",
            CONF_DISABLE_TARGET_ENTITY_ID: "input_boolean.boiler_permission",
        },
    )

    result = await hass.config_entries.flow.async_configure(
        advanced["flow_id"],
        custom,
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    for key in (
        CONF_ENABLE_SERVICE_DOMAIN,
        CONF_ENABLE_SERVICE_NAME,
        CONF_ENABLE_TARGET_ENTITY_ID,
        CONF_DISABLE_SERVICE_DOMAIN,
        CONF_DISABLE_SERVICE_NAME,
        CONF_DISABLE_TARGET_ENTITY_ID,
    ):
        assert result["options"][key] == custom[key]


@pytest.mark.asyncio
async def test_custom_service_mode_rejects_controlel_service_domain(
    hass,
    entry_data,
) -> None:
    _set_temperature_state(hass, entry_data[CONF_TEMPERATURE_ENTITY_ID])
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    advanced = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(
            entry_data,
            **{CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_CUSTOM},
        ),
    )

    result = await hass.config_entries.flow.async_configure(
        advanced["flow_id"],
        _advanced_input(
            entry_data,
            **{
                CONF_ENABLE_SERVICE_DOMAIN: DOMAIN,
                CONF_ENABLE_SERVICE_NAME: "turn_on",
                CONF_ENABLE_TARGET_ENTITY_ID: "switch.boiler",
                CONF_DISABLE_SERVICE_DOMAIN: "switch",
                CONF_DISABLE_SERVICE_NAME: "turn_off",
                CONF_DISABLE_TARGET_ENTITY_ID: "switch.boiler",
            },
        ),
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "controlel_service_not_allowed"}


@pytest.mark.asyncio
async def test_temperature_entity_with_unsupported_unit_is_rejected(
    hass,
    entry_data,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "293",
        {
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: "K",
        },
    )
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(entry_data),
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_TEMPERATURE_ENTITY_ID: "unsupported_temperature_unit"}


@pytest.mark.parametrize(
    ("entity_id", "attributes"),
    [
        ("switch.room", {}),
        (
            "sensor.humidity",
            {
                ATTR_DEVICE_CLASS: "humidity",
                ATTR_UNIT_OF_MEASUREMENT: "%",
            },
        ),
        (
            "sensor.power",
            {
                ATTR_DEVICE_CLASS: "power",
                ATTR_UNIT_OF_MEASUREMENT: "W",
            },
        ),
        (
            "sensor.unclassified",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        ),
    ],
)
@pytest.mark.asyncio
async def test_server_rejects_non_temperature_entities(
    hass,
    entry_data,
    entity_id,
    attributes,
) -> None:
    hass.states.async_set(entity_id, "20", attributes)
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(
            entry_data,
            **{CONF_TEMPERATURE_ENTITY_ID: entity_id},
        ),
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_TEMPERATURE_ENTITY_ID: "not_temperature_sensor"}


@pytest.mark.parametrize("state_value", ["unknown", "unavailable"])
@pytest.mark.asyncio
async def test_unavailable_temperature_entity_with_device_class_is_accepted(
    hass,
    entry_data,
    state_value,
) -> None:
    _set_temperature_state(
        hass,
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        state_value,
    )
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        initial["flow_id"],
        _basic_input(entry_data),
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_options_prefill_legacy_entry_and_preserve_ids_after_rename(
    hass,
    entry_data,
) -> None:
    entry_data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = 7.0
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 11.0
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data=entry_data,
        options={},
    )
    entry.add_to_hass(hass)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = _schema_defaults(initial)

    assert defaults[CONF_ZONE_NAME] == "Living room"
    assert defaults[CONF_SENSOR_NAME] == "Living room temperature"
    assert defaults[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_SIMPLE
    assert defaults[CONF_CONTROLLED_ENTITY_ID] == "switch.boiler"
    assert defaults[CONF_HEATING_TURN_ON_DIFFERENTIAL] == 0.0
    assert defaults[CONF_HEATING_TURN_OFF_DIFFERENTIAL] == 0.0
    assert defaults[CONF_HEAT_DEMAND_CONFIRMATION_DURATION_MINUTES] == 0.0

    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(
            entry_data,
            **{
                CONF_ZONE_NAME: "Upstairs",
                CONF_SENSOR_NAME: "Upstairs temperature",
            },
        ),
    )
    assert _schema_defaults(advanced)[CONF_DIAGNOSTIC_PROFILE] == (DIAGNOSTIC_PROFILE_DETAILED)
    result = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        _advanced_input(entry_data),
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SENSOR_ID] == "living_room_temperature"
    assert entry.data[CONF_ZONE_ID] == "living_room"
    assert entry.options[CONF_SENSOR_NAME] == "Upstairs temperature"
    assert entry.options[CONF_ZONE_NAME] == "Upstairs"
    assert entry.options[CONF_PRIMARY_MEASUREMENT_MAX_AGE] == 7.0
    assert entry.options[CONF_INDETERMINATE_GRACE_PERIOD] == 11.0
    assert entry.options[CONF_MINIMUM_HEATING_ON_TIME] == 0.0
    assert entry.options[CONF_MINIMUM_HEATING_OFF_TIME] == 0.0
    assert entry.options[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == 0.0
    assert entry.options[CONF_DIAGNOSTIC_PROFILE] == DIAGNOSTIC_PROFILE_DETAILED


@pytest.mark.parametrize("seconds", [30, 60, 90, 900])
@pytest.mark.parametrize("storage_layout", ["legacy_data", "options", "mixed"])
@pytest.mark.asyncio
async def test_options_unchanged_timing_round_trip_preserves_exact_seconds(
    hass,
    entry_data,
    seconds,
    storage_layout,
) -> None:
    effective = dict(entry_data)
    effective[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = seconds
    effective[CONF_INDETERMINATE_GRACE_PERIOD] = seconds
    effective[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] = seconds
    if storage_layout == "legacy_data":
        data = dict(effective)
        options = {}
    elif storage_layout == "options":
        data = {
            CONF_SENSOR_ID: effective[CONF_SENSOR_ID],
            CONF_ZONE_ID: effective[CONF_ZONE_ID],
        }
        options = {key: value for key, value in effective.items() if key not in {CONF_SENSOR_ID, CONF_ZONE_ID}}
    else:
        data = dict(effective)
        data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = seconds + 1
        data[CONF_INDETERMINATE_GRACE_PERIOD] = seconds + 1
        data[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] = seconds + 1
        options = {
            CONF_PRIMARY_MEASUREMENT_MAX_AGE: seconds,
            CONF_INDETERMINATE_GRACE_PERIOD: seconds,
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: seconds,
        }

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data=data,
        options=options,
    )
    entry.add_to_hass(hass)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(effective),
    )
    defaults = _schema_defaults(advanced)

    assert defaults[CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES] == seconds / 60
    assert defaults[CONF_INDETERMINATE_GRACE_PERIOD_MINUTES] == seconds / 60
    assert defaults[CONF_MINIMUM_HEATING_ON_TIME_MINUTES] == 0.0
    assert defaults[CONF_MINIMUM_HEATING_OFF_TIME_MINUTES] == 0.0

    result = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        {
            CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES: defaults[CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES],
            CONF_MAX_FUTURE_SKEW: defaults[CONF_MAX_FUTURE_SKEW],
            CONF_INDETERMINATE_GRACE_PERIOD_MINUTES: defaults[CONF_INDETERMINATE_GRACE_PERIOD_MINUTES],
            CONF_INDETERMINATE_TIMEOUT_ACTION: defaults[CONF_INDETERMINATE_TIMEOUT_ACTION],
        },
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PRIMARY_MEASUREMENT_MAX_AGE] == seconds
    assert entry.options[CONF_INDETERMINATE_GRACE_PERIOD] == seconds
    assert entry.options[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == seconds


@pytest.mark.asyncio
async def test_options_unchanged_debug_profile_preserves_exact_duration(
    hass,
    entry_data,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data=entry_data,
        options={
            CONF_DIAGNOSTIC_PROFILE: "debug",
            CONF_DEBUG_DURATION: 1871.0,
            CONF_DEBUG_UNTIL_CHANGED: False,
        },
    )
    entry.add_to_hass(hass)
    effective = dict(entry_data) | dict(entry.options)

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(effective),
    )
    defaults = _schema_defaults(advanced)
    assert defaults[CONF_DIAGNOSTIC_PROFILE] == "debug"
    assert defaults[CONF_DEBUG_DURATION_MINUTES] == 1871.0 / 60

    result = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        _advanced_input(effective),
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DIAGNOSTIC_PROFILE] == "debug"
    assert entry.options[CONF_DEBUG_DURATION] == 1871.0
    assert entry.options[CONF_DEBUG_UNTIL_CHANGED] is False


@pytest.mark.asyncio
async def test_options_flow_logs_only_allowlisted_effective_changes(
    hass,
    entry_data,
    caplog,
) -> None:
    entry_data["token"] = "must-not-appear"
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)
    caplog.set_level(
        logging.DEBUG,
        logger="custom_components.controlel.config_flow",
    )

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(entry_data),
    )
    unchanged = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        _advanced_input(entry_data),
    )

    assert unchanged["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert [
        record.getMessage() for record in caplog.records if record.name == "custom_components.controlel.config_flow"
    ] == ["Configuration unchanged for zone Living room"]

    caplog.clear()
    effective = dict(entry_data) | dict(entry.options)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(
            effective,
            **{CONF_TARGET_TEMPERATURE: 23.0},
        ),
    )
    changed = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        _advanced_input(
            effective,
            **{
                CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES: 1.0,
                CONF_DIAGNOSTIC_PROFILE: DIAGNOSTIC_PROFILE_BASIC,
                CONF_DEBUG_DURATION_MINUTES: 60.0,
                CONF_DEBUG_UNTIL_CHANGED: False,
            },
        ),
    )

    assert changed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    messages = [
        record.getMessage() for record in caplog.records if record.name == "custom_components.controlel.config_flow"
    ]
    assert messages == [
        "Configuration updated for zone Living room:\n"
        "target_temperature: 21.0 -> 23.0\n"
        "diagnostic_profile: detailed -> basic\n"
        "primary_measurement_max_age_seconds: 300.0 -> 60.0"
    ]
    assert "token" not in messages[0]
    assert "must-not-appear" not in messages[0]


@pytest.mark.asyncio
async def test_opening_and_submitting_legacy_custom_options_loses_no_binding(
    hass,
    entry_data,
) -> None:
    entry_data.update(
        {
            CONF_ENABLE_SERVICE_DOMAIN: "climate",
            CONF_ENABLE_SERVICE_NAME: "set_hvac_mode",
            CONF_ENABLE_TARGET_ENTITY_ID: "climate.boiler",
            CONF_DISABLE_SERVICE_DOMAIN: "input_boolean",
            CONF_DISABLE_SERVICE_NAME: "turn_off",
            CONF_DISABLE_TARGET_ENTITY_ID: "input_boolean.boiler_permission",
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = _schema_defaults(initial)
    assert defaults[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_CUSTOM

    basic = _options_basic_input(
        entry_data,
        **{
            CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_CUSTOM,
            CONF_CONTROLLED_ENTITY_ID: None,
        },
    )
    basic.pop(CONF_CONTROLLED_ENTITY_ID)
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        basic,
    )
    advanced_defaults = _schema_defaults(advanced)
    result = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        {
            **_advanced_input(entry_data),
            **{
                key: advanced_defaults[key]
                for key in (
                    CONF_ENABLE_SERVICE_DOMAIN,
                    CONF_ENABLE_SERVICE_NAME,
                    CONF_ENABLE_TARGET_ENTITY_ID,
                    CONF_DISABLE_SERVICE_DOMAIN,
                    CONF_DISABLE_SERVICE_NAME,
                    CONF_DISABLE_TARGET_ENTITY_ID,
                )
            },
        },
    )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    for key in (
        CONF_ENABLE_SERVICE_DOMAIN,
        CONF_ENABLE_SERVICE_NAME,
        CONF_ENABLE_TARGET_ENTITY_ID,
        CONF_DISABLE_SERVICE_DOMAIN,
        CONF_DISABLE_SERVICE_NAME,
        CONF_DISABLE_TARGET_ENTITY_ID,
    ):
        assert entry.options[key] == entry_data[key]


@pytest.mark.asyncio
async def test_existing_previously_accepted_sensor_remains_editable(
    hass,
    entry_data,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)
    initial = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        _options_basic_input(entry_data)
        | {
            CONF_ZONE_NAME: "Renamed zone",
        },
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "advanced"
    assert not result["errors"]


@pytest.mark.asyncio
async def test_real_single_entry_guard_aborts_second_flow(hass, entry_data) -> None:
    MockConfigEntry(domain=DOMAIN, data=entry_data).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

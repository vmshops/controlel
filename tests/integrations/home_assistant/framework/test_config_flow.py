import json

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)


def _schema_fields(result) -> dict[str, object]:
    return {marker.schema: validator for marker, validator in result["data_schema"].schema.items()}


@pytest.mark.asyncio
async def test_user_step_shows_expected_real_selectors(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    fields = _schema_fields(result)
    assert set(fields) == {
        "sensor_id",
        "sensor_name",
        "temperature_entity_id",
        "zone_id",
        "zone_name",
        "target_temperature",
        "primary_measurement_max_age",
        "max_future_skew",
        "indeterminate_grace_period",
        "indeterminate_timeout_action",
        "enable_service_domain",
        "enable_service_name",
        "enable_target_entity_id",
        "disable_service_domain",
        "disable_service_name",
        "disable_target_entity_id",
    }
    assert isinstance(fields[CONF_TEMPERATURE_ENTITY_ID], selector.EntitySelector)
    timeout_selector = fields[CONF_INDETERMINATE_TIMEOUT_ACTION]
    assert isinstance(timeout_selector, selector.SelectSelector)
    assert set(timeout_selector.config["options"]) == {
        "enable_heating",
        "disable_heating",
    }


@pytest.mark.asyncio
async def test_valid_input_creates_one_entry_with_serializable_primitives(hass, entry_data) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room"
    assert result["data"] == entry_data
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    json.dumps(result["data"])
    assert all(isinstance(value, str | int | float | bool | type(None)) for value in result["data"].values())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, 0),
        (CONF_PRIMARY_MEASUREMENT_MAX_AGE, -1),
        (CONF_MAX_FUTURE_SKEW, -1),
        (CONF_INDETERMINATE_GRACE_PERIOD, -1),
        (CONF_INDETERMINATE_TIMEOUT_ACTION, "observe_only"),
        (CONF_TEMPERATURE_ENTITY_ID, "not-an-entity"),
        (CONF_ENABLE_TARGET_ENTITY_ID, "not-an-entity"),
        (CONF_DISABLE_TARGET_ENTITY_ID, "not-an-entity"),
    ],
)
@pytest.mark.asyncio
async def test_real_flow_manager_rejects_selector_schema_violations(hass, entry_data, field, value) -> None:
    entry_data[field] = value
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with pytest.raises(data_entry_flow.InvalidData):
        await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_ENABLE_SERVICE_DOMAIN, "Switch"),
        (CONF_ENABLE_SERVICE_NAME, "turn-on"),
        (CONF_DISABLE_SERVICE_DOMAIN, "switch.example"),
        (CONF_DISABLE_SERVICE_NAME, "turn-off"),
    ],
)
@pytest.mark.asyncio
async def test_component_validation_errors_return_form(hass, entry_data, field, value) -> None:
    entry_data[field] = value
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"]
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize(
    "field",
    [CONF_ENABLE_SERVICE_DOMAIN, CONF_DISABLE_SERVICE_DOMAIN],
)
@pytest.mark.asyncio
async def test_controlel_service_domain_is_rejected(hass, entry_data, field) -> None:
    entry_data[field] = DOMAIN
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "controlel_service_not_allowed"}


@pytest.mark.parametrize("state_value", ["unknown", "unavailable"])
@pytest.mark.asyncio
async def test_unavailable_temperature_entity_can_be_selected(hass, entry_data, state_value) -> None:
    hass.states.async_set(entry_data[CONF_TEMPERATURE_ENTITY_ID], state_value)
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_available_incompatible_temperature_unit_has_field_error(hass, entry_data) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "48",
        {ATTR_UNIT_OF_MEASUREMENT: "%"},
    )
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], entry_data)

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {CONF_TEMPERATURE_ENTITY_ID: "unsupported_temperature_unit"}


@pytest.mark.asyncio
async def test_real_single_entry_guard_aborts_second_flow(hass, entry_data) -> None:
    MockConfigEntry(domain=DOMAIN, data=entry_data).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

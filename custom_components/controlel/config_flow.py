"""Minimal one-zone Controlel config flow."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from controlel.domain.commands.heating_action import HeatingAction

from .config import (
    HomeAssistantConfigurationError,
    integration_config_from_entry_data,
)
from .const import (
    ATTR_UNIT_OF_MEASUREMENT,
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
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)


class ControlelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one Controlel zone and one shared heat source."""

    VERSION = CONFIG_ENTRY_VERSION

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                integration_config_from_entry_data(user_input)
            except HomeAssistantConfigurationError as error:
                if "own integration service domain" in str(error):
                    errors["base"] = "controlel_service_not_allowed"
                else:
                    errors["base"] = "invalid_configuration"
            else:
                state = self.hass.states.get(user_input[CONF_TEMPERATURE_ENTITY_ID])
                if state is not None and state.state.casefold() not in {
                    STATE_UNKNOWN,
                    STATE_UNAVAILABLE,
                }:
                    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    if unit not in {UNIT_CELSIUS, UNIT_FAHRENHEIT}:
                        errors[CONF_TEMPERATURE_ENTITY_ID] = "unsupported_temperature_unit"

            if not errors:
                return self.async_create_entry(
                    title=str(user_input[CONF_ZONE_NAME]),
                    data=dict(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )


def _user_schema() -> vol.Schema:
    non_negative_seconds = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )
    positive_seconds = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.001,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )
    text = selector.TextSelector()
    entity = selector.EntitySelector()
    return vol.Schema(
        {
            vol.Required(CONF_SENSOR_ID): text,
            vol.Required(CONF_SENSOR_NAME): text,
            vol.Required(CONF_TEMPERATURE_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_ZONE_ID): text,
            vol.Required(CONF_ZONE_NAME): text,
            vol.Required(CONF_TARGET_TEMPERATURE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement=UNIT_CELSIUS,
                )
            ),
            vol.Required(CONF_PRIMARY_MEASUREMENT_MAX_AGE): positive_seconds,
            vol.Required(CONF_MAX_FUTURE_SKEW): non_negative_seconds,
            vol.Required(CONF_INDETERMINATE_GRACE_PERIOD): non_negative_seconds,
            vol.Required(CONF_INDETERMINATE_TIMEOUT_ACTION): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        HeatingAction.ENABLE_HEATING.value,
                        HeatingAction.DISABLE_HEATING.value,
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_ENABLE_SERVICE_DOMAIN): text,
            vol.Required(CONF_ENABLE_SERVICE_NAME): text,
            vol.Required(CONF_ENABLE_TARGET_ENTITY_ID): entity,
            vol.Required(CONF_DISABLE_SERVICE_DOMAIN): text,
            vol.Required(CONF_DISABLE_SERVICE_NAME): text,
            vol.Required(CONF_DISABLE_TARGET_ENTITY_ID): entity,
        }
    )

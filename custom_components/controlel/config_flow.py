"""One-zone Controlel configuration and options flows."""

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers import selector

from .config import (
    HomeAssistantConfigurationError,
    generated_identifier,
    infer_control_mode,
    integration_config_from_entry_data,
    merged_entry_configuration,
    validate_identifier,
)
from .const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
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
    CONFIG_ENTRY_VERSION,
    CONTROL_MODE_CUSTOM,
    CONTROL_MODE_SIMPLE,
    DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL,
    DEFAULT_HEATING_TURN_ON_DIFFERENTIAL,
    DEFAULT_INDETERMINATE_GRACE_PERIOD,
    DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
    DEFAULT_MAX_FUTURE_SKEW,
    DEFAULT_MINIMUM_HEATING_OFF_TIME,
    DEFAULT_MINIMUM_HEATING_ON_TIME,
    DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    LEGACY_HEATING_TURN_OFF_DIFFERENTIAL,
    LEGACY_HEATING_TURN_ON_DIFFERENTIAL,
    LEGACY_MINIMUM_HEATING_OFF_TIME,
    LEGACY_MINIMUM_HEATING_ON_TIME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)

_MUTABLE_COMMON_KEYS = (
    CONF_SENSOR_NAME,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_MAX_FUTURE_SKEW,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_HEAT_SOURCE_CONTROL_MODE,
)
_ADVANCED_BINDING_KEYS = (
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
)
_SEMANTIC_LOG_FIELDS = (
    ("zone_name", lambda config: config.zone_name),
    ("sensor_name", lambda config: config.sensor_name),
    ("temperature_entity_id", lambda config: config.temperature_entity_id),
    ("target_temperature", lambda config: config.target_temperature.value),
    (
        "heating_turn_on_differential",
        lambda config: config.heating_turn_on_differential,
    ),
    (
        "heating_turn_off_differential",
        lambda config: config.heating_turn_off_differential,
    ),
    (
        "minimum_heating_on_time_seconds",
        lambda config: config.minimum_heating_on_time.total_seconds(),
    ),
    (
        "minimum_heating_off_time_seconds",
        lambda config: config.minimum_heating_off_time.total_seconds(),
    ),
    (
        "primary_measurement_max_age_seconds",
        lambda config: config.primary_measurement_max_age.total_seconds(),
    ),
    ("max_future_skew_seconds", lambda config: config.max_future_skew.total_seconds()),
    (
        "indeterminate_grace_period_seconds",
        lambda config: config.indeterminate_grace_period.total_seconds(),
    ),
    (
        "indeterminate_timeout_action",
        lambda config: config.indeterminate_timeout_action.value,
    ),
    ("heat_source_control_mode", lambda config: config.heat_source_control_mode),
    ("controlled_entity_id", lambda config: config.controlled_entity_id),
    (
        "enable_service_domain",
        lambda config: config.heat_source.enable_heating.domain,
    ),
    (
        "enable_service_name",
        lambda config: config.heat_source.enable_heating.service,
    ),
    (
        "enable_target_entity_id",
        lambda config: config.heat_source.enable_heating.target_entity_id,
    ),
    (
        "disable_service_domain",
        lambda config: config.heat_source.disable_heating.domain,
    ),
    (
        "disable_service_name",
        lambda config: config.heat_source.disable_heating.service,
    ),
    (
        "disable_target_entity_id",
        lambda config: config.heat_source.disable_heating.target_entity_id,
    ),
)
LOGGER = logging.getLogger(__name__)


class ControlelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one Controlel zone and one shared heat source."""

    VERSION = CONFIG_ENTRY_VERSION

    def __init__(self) -> None:
        self._pending_basic: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the editable options flow for an existing entry."""

        return ControlelOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors.update(_validate_basic(self.hass, user_input))
            if not errors:
                self._pending_basic = dict(user_input)
                if (
                    user_input.get(CONF_SHOW_ADVANCED, False)
                    or user_input[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_CUSTOM
                ):
                    return await self.async_step_advanced()
                configuration, errors = _initial_configuration(
                    self._pending_basic,
                    {},
                )
                if CONF_SENSOR_ID in errors:
                    errors = {key: value for key, value in errors.items() if key != CONF_SENSOR_ID}
                    errors[CONF_SENSOR_NAME] = "cannot_generate_id"
                if CONF_ZONE_ID in errors:
                    errors = {key: value for key, value in errors.items() if key != CONF_ZONE_ID}
                    errors[CONF_ZONE_NAME] = "cannot_generate_id"
                if not errors:
                    errors.update(_configuration_errors(configuration))
                if not errors:
                    return self._create_entry_from_configuration(configuration)

        return self.async_show_form(
            step_id="user",
            data_schema=_basic_schema(),
            errors=errors,
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            configuration, errors = _initial_configuration(
                self._pending_basic,
                user_input,
            )
            if not errors:
                errors.update(_configuration_errors(configuration))
            if not errors:
                return self._create_entry_from_configuration(configuration)

        return self.async_show_form(
            step_id="advanced",
            data_schema=_advanced_schema(
                self._pending_basic[CONF_HEAT_SOURCE_CONTROL_MODE],
                {},
                include_ids=True,
            ),
            errors=errors,
            last_step=True,
        )

    def _create_entry_from_configuration(
        self,
        configuration: Mapping[str, Any],
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=str(configuration[CONF_ZONE_NAME]),
            data={
                CONF_SENSOR_ID: configuration[CONF_SENSOR_ID],
                CONF_ZONE_ID: configuration[CONF_ZONE_ID],
            },
            options=_mutable_options(configuration),
        )


class ControlelOptionsFlow(OptionsFlow):
    """Edit mutable settings while preserving stable IDs."""

    def __init__(self) -> None:
        self._pending_basic: dict[str, Any] = {}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        current = merged_entry_configuration(
            self.config_entry.data,
            self.config_entry.options,
        )
        _apply_legacy_protection_defaults(current)
        current[CONF_HEAT_SOURCE_CONTROL_MODE] = infer_control_mode(current)
        if current[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_SIMPLE:
            current.setdefault(
                CONF_CONTROLLED_ENTITY_ID,
                current.get(CONF_ENABLE_TARGET_ENTITY_ID),
            )

        errors: dict[str, str] = {}
        if user_input is not None:
            errors.update(
                _validate_basic(
                    self.hass,
                    user_input,
                    existing_temperature_entity=str(current[CONF_TEMPERATURE_ENTITY_ID]),
                )
            )
            if not errors:
                self._pending_basic = {**current, **user_input}
                return await self.async_step_advanced()

        return self.async_show_form(
            step_id="init",
            data_schema=_basic_schema(current, options_flow=True),
            errors=errors,
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        current = merged_entry_configuration(
            self.config_entry.data,
            self.config_entry.options,
        )
        _apply_legacy_protection_defaults(current)
        errors: dict[str, str] = {}
        if user_input is not None:
            configuration = _configuration_from_steps(
                self._pending_basic,
                {**current, **user_input},
                sensor_id=str(self.config_entry.data[CONF_SENSOR_ID]),
                zone_id=str(self.config_entry.data[CONF_ZONE_ID]),
            )
            _preserve_unchanged_seconds(
                configuration,
                {**current, **user_input},
                current,
            )
            errors.update(_configuration_errors(configuration))
            if not errors:
                _log_semantic_configuration_diff(
                    integration_config_from_entry_data(current),
                    integration_config_from_entry_data(configuration),
                )
                return self.async_create_entry(
                    title="",
                    data=_mutable_options(configuration),
                )

        return self.async_show_form(
            step_id="advanced",
            data_schema=_advanced_schema(
                self._pending_basic[CONF_HEAT_SOURCE_CONTROL_MODE],
                current,
                include_ids=False,
            ),
            errors=errors,
            last_step=True,
        )


def _basic_schema(
    defaults: Mapping[str, Any] | None = None,
    *,
    options_flow: bool = False,
) -> vol.Schema:
    values = defaults or {}
    schema: dict[vol.Marker, object] = {
        vol.Required(
            CONF_ZONE_NAME,
            default=values.get(CONF_ZONE_NAME, ""),
        ): selector.TextSelector(),
        vol.Required(
            CONF_SENSOR_NAME,
            default=values.get(CONF_SENSOR_NAME, ""),
        ): selector.TextSelector(),
        vol.Required(
            CONF_TEMPERATURE_ENTITY_ID,
            default=values.get(CONF_TEMPERATURE_ENTITY_ID, vol.UNDEFINED),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                filter={
                    "domain": "sensor",
                    "device_class": "temperature",
                }
            )
        ),
        vol.Required(
            CONF_TARGET_TEMPERATURE,
            default=values.get(
                CONF_TARGET_TEMPERATURE,
                DEFAULT_TARGET_TEMPERATURE,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=UNIT_CELSIUS,
            )
        ),
        vol.Required(
            CONF_HEATING_TURN_ON_DIFFERENTIAL,
            default=values.get(
                CONF_HEATING_TURN_ON_DIFFERENTIAL,
                DEFAULT_HEATING_TURN_ON_DIFFERENTIAL,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=UNIT_CELSIUS,
            )
        ),
        vol.Required(
            CONF_HEATING_TURN_OFF_DIFFERENTIAL,
            default=values.get(
                CONF_HEATING_TURN_OFF_DIFFERENTIAL,
                DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=UNIT_CELSIUS,
            )
        ),
        vol.Required(
            CONF_HEAT_SOURCE_CONTROL_MODE,
            default=values.get(
                CONF_HEAT_SOURCE_CONTROL_MODE,
                CONTROL_MODE_SIMPLE,
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {
                        "value": CONTROL_MODE_SIMPLE,
                        "label": "One controlled switch",
                    },
                    {
                        "value": CONTROL_MODE_CUSTOM,
                        "label": "Use custom Home Assistant services",
                    },
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(
            CONF_CONTROLLED_ENTITY_ID,
            default=values.get(CONF_CONTROLLED_ENTITY_ID, vol.UNDEFINED),
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
    }
    if not options_flow:
        schema[
            vol.Optional(
                CONF_SHOW_ADVANCED,
                default=False,
            )
        ] = selector.BooleanSelector()
    return vol.Schema(schema)


def _advanced_schema(
    control_mode: str,
    defaults: Mapping[str, Any],
    *,
    include_ids: bool,
) -> vol.Schema:
    fields: dict[vol.Marker, object] = {}
    if include_ids:
        fields[vol.Optional(CONF_SENSOR_ID, default="")] = selector.TextSelector()
        fields[vol.Optional(CONF_ZONE_ID, default="")] = selector.TextSelector()
    fields.update(
        {
            vol.Required(
                CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES,
                default=float(
                    defaults.get(
                        CONF_PRIMARY_MEASUREMENT_MAX_AGE,
                        DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
                    )
                )
                / 60,
            ): _minutes_selector(positive=True),
            vol.Required(
                CONF_MAX_FUTURE_SKEW,
                default=defaults.get(
                    CONF_MAX_FUTURE_SKEW,
                    DEFAULT_MAX_FUTURE_SKEW,
                ),
            ): _seconds_selector(),
            vol.Required(
                CONF_INDETERMINATE_GRACE_PERIOD_MINUTES,
                default=float(
                    defaults.get(
                        CONF_INDETERMINATE_GRACE_PERIOD,
                        DEFAULT_INDETERMINATE_GRACE_PERIOD,
                    )
                )
                / 60,
            ): _minutes_selector(),
            vol.Required(
                CONF_INDETERMINATE_TIMEOUT_ACTION,
                default=defaults.get(
                    CONF_INDETERMINATE_TIMEOUT_ACTION,
                    DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": "disable_heating",
                            "label": "Turn heating off — recommended",
                        },
                        {
                            "value": "enable_heating",
                            "label": ("Turn heating on — warning: a sensor failure may leave heating enabled"),
                        },
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_MINIMUM_HEATING_ON_TIME_MINUTES,
                default=float(
                    defaults.get(
                        CONF_MINIMUM_HEATING_ON_TIME,
                        DEFAULT_MINIMUM_HEATING_ON_TIME,
                    )
                )
                / 60,
            ): _minutes_selector(),
            vol.Required(
                CONF_MINIMUM_HEATING_OFF_TIME_MINUTES,
                default=float(
                    defaults.get(
                        CONF_MINIMUM_HEATING_OFF_TIME,
                        DEFAULT_MINIMUM_HEATING_OFF_TIME,
                    )
                )
                / 60,
            ): _minutes_selector(),
        }
    )
    if control_mode == CONTROL_MODE_CUSTOM:
        text = selector.TextSelector()
        entity = selector.EntitySelector()
        for key, default in (
            (CONF_ENABLE_SERVICE_DOMAIN, "switch"),
            (CONF_ENABLE_SERVICE_NAME, "turn_on"),
            (
                CONF_ENABLE_TARGET_ENTITY_ID,
                defaults.get(CONF_CONTROLLED_ENTITY_ID, vol.UNDEFINED),
            ),
            (CONF_DISABLE_SERVICE_DOMAIN, "switch"),
            (CONF_DISABLE_SERVICE_NAME, "turn_off"),
            (
                CONF_DISABLE_TARGET_ENTITY_ID,
                defaults.get(CONF_CONTROLLED_ENTITY_ID, vol.UNDEFINED),
            ),
        ):
            value = defaults.get(key, default)
            fields[vol.Required(key, default=value)] = entity if "target_entity" in key else text
    return vol.Schema(fields)


def _minutes_selector(*, positive: bool = False) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.001 if positive else 0,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


def _seconds_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _initial_configuration(
    basic: Mapping[str, Any],
    advanced: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    sensor_id = str(advanced.get(CONF_SENSOR_ID, "")).strip()
    zone_id = str(advanced.get(CONF_ZONE_ID, "")).strip()
    try:
        sensor_id = sensor_id or generated_identifier(
            str(basic[CONF_SENSOR_NAME]),
            "sensor ID",
        )
    except HomeAssistantConfigurationError:
        errors[CONF_SENSOR_ID] = "invalid_sensor_id"
    try:
        zone_id = zone_id or generated_identifier(
            str(basic[CONF_ZONE_NAME]),
            "zone ID",
        )
    except HomeAssistantConfigurationError:
        errors[CONF_ZONE_ID] = "invalid_zone_id"
    if sensor_id:
        try:
            validate_identifier(sensor_id, "sensor ID")
        except HomeAssistantConfigurationError:
            errors[CONF_SENSOR_ID] = "invalid_sensor_id"
    if zone_id:
        try:
            validate_identifier(zone_id, "zone ID")
        except HomeAssistantConfigurationError:
            errors[CONF_ZONE_ID] = "invalid_zone_id"
    return (
        _configuration_from_steps(
            basic,
            advanced,
            sensor_id=sensor_id,
            zone_id=zone_id,
        ),
        errors,
    )


def _configuration_from_steps(
    basic: Mapping[str, Any],
    advanced: Mapping[str, Any],
    *,
    sensor_id: str,
    zone_id: str,
) -> dict[str, Any]:
    configuration = {
        CONF_SENSOR_ID: sensor_id,
        CONF_SENSOR_NAME: str(basic[CONF_SENSOR_NAME]).strip(),
        CONF_TEMPERATURE_ENTITY_ID: basic[CONF_TEMPERATURE_ENTITY_ID],
        CONF_ZONE_ID: zone_id,
        CONF_ZONE_NAME: str(basic[CONF_ZONE_NAME]).strip(),
        CONF_TARGET_TEMPERATURE: basic[CONF_TARGET_TEMPERATURE],
        CONF_HEATING_TURN_ON_DIFFERENTIAL: basic.get(
            CONF_HEATING_TURN_ON_DIFFERENTIAL,
            DEFAULT_HEATING_TURN_ON_DIFFERENTIAL,
        ),
        CONF_HEATING_TURN_OFF_DIFFERENTIAL: basic.get(
            CONF_HEATING_TURN_OFF_DIFFERENTIAL,
            DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL,
        ),
        CONF_MINIMUM_HEATING_ON_TIME: float(
            advanced.get(
                CONF_MINIMUM_HEATING_ON_TIME_MINUTES,
                DEFAULT_MINIMUM_HEATING_ON_TIME / 60,
            )
        )
        * 60,
        CONF_MINIMUM_HEATING_OFF_TIME: float(
            advanced.get(
                CONF_MINIMUM_HEATING_OFF_TIME_MINUTES,
                DEFAULT_MINIMUM_HEATING_OFF_TIME / 60,
            )
        )
        * 60,
        CONF_PRIMARY_MEASUREMENT_MAX_AGE: float(
            advanced.get(
                CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES,
                DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE / 60,
            )
        )
        * 60,
        CONF_MAX_FUTURE_SKEW: advanced.get(
            CONF_MAX_FUTURE_SKEW,
            DEFAULT_MAX_FUTURE_SKEW,
        ),
        CONF_INDETERMINATE_GRACE_PERIOD: float(
            advanced.get(
                CONF_INDETERMINATE_GRACE_PERIOD_MINUTES,
                DEFAULT_INDETERMINATE_GRACE_PERIOD / 60,
            )
        )
        * 60,
        CONF_INDETERMINATE_TIMEOUT_ACTION: advanced.get(
            CONF_INDETERMINATE_TIMEOUT_ACTION,
            DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
        ),
        CONF_HEAT_SOURCE_CONTROL_MODE: basic[CONF_HEAT_SOURCE_CONTROL_MODE],
    }
    if basic[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_SIMPLE:
        configuration[CONF_CONTROLLED_ENTITY_ID] = basic.get(
            CONF_CONTROLLED_ENTITY_ID,
            "",
        )
    else:
        configuration.update({key: advanced.get(key, "") for key in _ADVANCED_BINDING_KEYS})
    return configuration


def _mutable_options(configuration: Mapping[str, Any]) -> dict[str, Any]:
    options = {key: configuration[key] for key in _MUTABLE_COMMON_KEYS}
    if configuration[CONF_HEAT_SOURCE_CONTROL_MODE] == CONTROL_MODE_SIMPLE:
        options[CONF_CONTROLLED_ENTITY_ID] = configuration[CONF_CONTROLLED_ENTITY_ID]
    else:
        options.update({key: configuration[key] for key in _ADVANCED_BINDING_KEYS})
    return options


def _preserve_unchanged_seconds(
    configuration: dict[str, Any],
    advanced_input: Mapping[str, Any],
    current: Mapping[str, Any],
) -> None:
    """Keep exact legacy seconds when the displayed minute value was unchanged."""

    for minutes_key, seconds_key in (
        (
            CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES,
            CONF_PRIMARY_MEASUREMENT_MAX_AGE,
        ),
        (
            CONF_INDETERMINATE_GRACE_PERIOD_MINUTES,
            CONF_INDETERMINATE_GRACE_PERIOD,
        ),
        (
            CONF_MINIMUM_HEATING_ON_TIME_MINUTES,
            CONF_MINIMUM_HEATING_ON_TIME,
        ),
        (
            CONF_MINIMUM_HEATING_OFF_TIME_MINUTES,
            CONF_MINIMUM_HEATING_OFF_TIME,
        ),
    ):
        current_seconds = current[seconds_key]
        if float(advanced_input[minutes_key]) == float(current_seconds) / 60:
            configuration[seconds_key] = current_seconds


def _apply_legacy_protection_defaults(configuration: dict[str, Any]) -> None:
    """Expose legacy entries without silently changing regulation behavior."""

    configuration.setdefault(
        CONF_HEATING_TURN_ON_DIFFERENTIAL,
        LEGACY_HEATING_TURN_ON_DIFFERENTIAL,
    )
    configuration.setdefault(
        CONF_HEATING_TURN_OFF_DIFFERENTIAL,
        LEGACY_HEATING_TURN_OFF_DIFFERENTIAL,
    )
    configuration.setdefault(
        CONF_MINIMUM_HEATING_ON_TIME,
        LEGACY_MINIMUM_HEATING_ON_TIME,
    )
    configuration.setdefault(
        CONF_MINIMUM_HEATING_OFF_TIME,
        LEGACY_MINIMUM_HEATING_OFF_TIME,
    )


def _log_semantic_configuration_diff(before: Any, after: Any) -> None:
    """Log only allowlisted effective configuration changes."""

    changes = [
        (field, before_value, after_value)
        for field, value_fn in _SEMANTIC_LOG_FIELDS
        if (before_value := value_fn(before)) != (after_value := value_fn(after))
    ]
    zone_name = _safe_log_value(after.zone_name)
    if not changes:
        LOGGER.debug("Configuration unchanged for zone %s", zone_name)
        return
    lines = [
        f"{field}: {_safe_log_value(before_value)} -> {_safe_log_value(after_value)}"
        for field, before_value, after_value in changes
    ]
    LOGGER.info(
        "Configuration updated for zone %s:\n%s",
        zone_name,
        "\n".join(lines),
    )


def _safe_log_value(value: object) -> str:
    return str(value).replace("\r", r"\r").replace("\n", r"\n")


def _validate_basic(
    hass,
    user_input: Mapping[str, Any],
    *,
    existing_temperature_entity: str | None = None,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not str(user_input.get(CONF_ZONE_NAME, "")).strip():
        errors[CONF_ZONE_NAME] = "required"
    if not str(user_input.get(CONF_SENSOR_NAME, "")).strip():
        errors[CONF_SENSOR_NAME] = "required"
    if user_input.get(CONF_HEAT_SOURCE_CONTROL_MODE) == CONTROL_MODE_SIMPLE and not user_input.get(
        CONF_CONTROLLED_ENTITY_ID
    ):
        errors[CONF_CONTROLLED_ENTITY_ID] = "controlled_switch_required"
    temperature_entity = str(user_input.get(CONF_TEMPERATURE_ENTITY_ID, ""))
    if temperature_entity != existing_temperature_entity:
        temperature_error = _temperature_entity_error(hass, temperature_entity)
        if temperature_error is not None:
            errors[CONF_TEMPERATURE_ENTITY_ID] = temperature_error
    return errors


def _temperature_entity_error(hass, entity_id: str) -> str | None:
    if not entity_id.startswith("sensor."):
        return "not_temperature_sensor"
    state = hass.states.get(entity_id)
    if state is None or state.attributes.get(ATTR_DEVICE_CLASS) != "temperature":
        return "not_temperature_sensor"
    if state.state.casefold() not in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit not in {UNIT_CELSIUS, UNIT_FAHRENHEIT}:
            return "unsupported_temperature_unit"
    return None


def _configuration_errors(
    configuration: Mapping[str, Any],
) -> dict[str, str]:
    try:
        integration_config_from_entry_data(configuration)
    except HomeAssistantConfigurationError as error:
        message = str(error)
        if "own integration service domain" in message:
            return {"base": "controlel_service_not_allowed"}
        for field in (
            CONF_SENSOR_ID,
            CONF_ZONE_ID,
            CONF_PRIMARY_MEASUREMENT_MAX_AGE,
            CONF_MAX_FUTURE_SKEW,
            CONF_INDETERMINATE_GRACE_PERIOD,
            CONF_INDETERMINATE_TIMEOUT_ACTION,
            CONF_HEATING_TURN_ON_DIFFERENTIAL,
            CONF_HEATING_TURN_OFF_DIFFERENTIAL,
            CONF_MINIMUM_HEATING_ON_TIME,
            CONF_MINIMUM_HEATING_OFF_TIME,
            CONF_CONTROLLED_ENTITY_ID,
            *_ADVANCED_BINDING_KEYS,
        ):
            if field.replace("_", " ") in message or field in message:
                return {field: "invalid_value"}
        return {"base": "invalid_configuration"}
    return {}

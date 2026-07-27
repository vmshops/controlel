"""Immutable effective configuration for the Home Assistant adapter."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Any

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

from .const import (
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
    DOMAIN,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
_ENTITY_ID_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_IDENTITY_KEYS = frozenset({CONF_SENSOR_ID, CONF_ZONE_ID})


class HomeAssistantConfigurationError(ValueError):
    """Raised when stored adapter configuration is invalid."""


@dataclass(frozen=True)
class HomeAssistantSensorBinding:
    entity_id: str
    sensor_id: SensorId

    def __post_init__(self) -> None:
        _validate_entity_id(self.entity_id, "temperature entity ID")


@dataclass(frozen=True)
class HomeAssistantServiceCall:
    domain: str
    service: str
    target_entity_id: str

    def __post_init__(self) -> None:
        _validate_slug(self.domain, "service domain")
        _validate_slug(self.service, "service name")
        _validate_entity_id(self.target_entity_id, "service target entity ID")
        if self.domain == DOMAIN:
            raise HomeAssistantConfigurationError("Controlel cannot call its own integration service domain")


@dataclass(frozen=True)
class HomeAssistantHeatSourceBinding:
    enable_heating: HomeAssistantServiceCall
    disable_heating: HomeAssistantServiceCall


@dataclass(frozen=True)
class HomeAssistantIntegrationConfig:
    sensor_id: SensorId
    sensor_name: str
    temperature_entity_id: str
    zone_id: ZoneId
    zone_name: str
    target_temperature: Temperature
    primary_measurement_max_age: timedelta
    max_future_skew: timedelta
    indeterminate_grace_period: timedelta
    indeterminate_timeout_action: HeatingAction
    heat_source: HomeAssistantHeatSourceBinding
    heat_source_control_mode: str
    controlled_entity_id: str | None

    def __post_init__(self) -> None:
        _validate_nonempty(self.sensor_name, "sensor name")
        _validate_nonempty(self.zone_name, "zone name")
        _validate_entity_id(self.temperature_entity_id, "temperature entity ID")
        if self.primary_measurement_max_age <= timedelta(0):
            raise HomeAssistantConfigurationError("primary measurement maximum age must be positive")
        if self.max_future_skew < timedelta(0):
            raise HomeAssistantConfigurationError("maximum future skew must not be negative")
        if self.indeterminate_grace_period < timedelta(0):
            raise HomeAssistantConfigurationError("indeterminate grace period must not be negative")
        if self.heat_source_control_mode not in {
            CONTROL_MODE_SIMPLE,
            CONTROL_MODE_CUSTOM,
        }:
            raise HomeAssistantConfigurationError("heat source control mode is invalid")

    @property
    def sensor_binding(self) -> HomeAssistantSensorBinding:
        return HomeAssistantSensorBinding(
            entity_id=self.temperature_entity_id,
            sensor_id=self.sensor_id,
        )


def integration_config_from_entry_data(
    data: Mapping[str, Any],
) -> HomeAssistantIntegrationConfig:
    """Reconstruct typed immutable configuration from primitive entry data."""

    try:
        sensor_id_value = _required_string(data, CONF_SENSOR_ID)
        zone_id_value = _required_string(data, CONF_ZONE_ID)
        sensor_id = SensorId(sensor_id_value)
        zone_id = ZoneId(zone_id_value)
        timeout_action = HeatingAction(_required_string(data, CONF_INDETERMINATE_TIMEOUT_ACTION))
        target_temperature = Temperature(_finite_number(data, CONF_TARGET_TEMPERATURE))
        primary_max_age = timedelta(seconds=_finite_duration(data, CONF_PRIMARY_MEASUREMENT_MAX_AGE, positive=True))
        max_future_skew = timedelta(seconds=_finite_duration(data, CONF_MAX_FUTURE_SKEW))
        grace_period = timedelta(seconds=_finite_duration(data, CONF_INDETERMINATE_GRACE_PERIOD))
        control_mode = infer_control_mode(data)
        controlled_entity_id: str | None = None
        if control_mode == CONTROL_MODE_SIMPLE:
            controlled_entity_id = _required_string(
                data,
                CONF_CONTROLLED_ENTITY_ID,
                fallback=CONF_ENABLE_TARGET_ENTITY_ID,
            )
            if not controlled_entity_id.startswith("switch."):
                raise HomeAssistantConfigurationError("controlled entity must be a switch")
            heat_source = simple_heat_source_binding(controlled_entity_id)
        else:
            heat_source = HomeAssistantHeatSourceBinding(
                enable_heating=HomeAssistantServiceCall(
                    domain=_required_string(data, CONF_ENABLE_SERVICE_DOMAIN),
                    service=_required_string(data, CONF_ENABLE_SERVICE_NAME),
                    target_entity_id=_required_string(data, CONF_ENABLE_TARGET_ENTITY_ID),
                ),
                disable_heating=HomeAssistantServiceCall(
                    domain=_required_string(data, CONF_DISABLE_SERVICE_DOMAIN),
                    service=_required_string(data, CONF_DISABLE_SERVICE_NAME),
                    target_entity_id=_required_string(data, CONF_DISABLE_TARGET_ENTITY_ID),
                ),
            )
        return HomeAssistantIntegrationConfig(
            sensor_id=sensor_id,
            sensor_name=_required_string(data, CONF_SENSOR_NAME),
            temperature_entity_id=_required_string(data, CONF_TEMPERATURE_ENTITY_ID),
            zone_id=zone_id,
            zone_name=_required_string(data, CONF_ZONE_NAME),
            target_temperature=target_temperature,
            primary_measurement_max_age=primary_max_age,
            max_future_skew=max_future_skew,
            indeterminate_grace_period=grace_period,
            indeterminate_timeout_action=timeout_action,
            heat_source=heat_source,
            heat_source_control_mode=control_mode,
            controlled_entity_id=controlled_entity_id,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, HomeAssistantConfigurationError):
            raise
        raise HomeAssistantConfigurationError(str(error)) from error


def integration_config_from_entry(
    data: Mapping[str, Any],
    options: Mapping[str, Any],
) -> HomeAssistantIntegrationConfig:
    """Build effective configuration with options overriding mutable legacy data."""

    return integration_config_from_entry_data(merged_entry_configuration(data, options))


def merged_entry_configuration(
    data: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge legacy/bootstrap data with mutable options without replacing IDs."""

    merged = dict(data)
    merged.update({key: value for key, value in options.items() if key not in _IDENTITY_KEYS})
    return merged


def infer_control_mode(data: Mapping[str, Any]) -> str:
    """Return explicit control mode or infer it losslessly from legacy bindings."""

    explicit = data.get(CONF_HEAT_SOURCE_CONTROL_MODE)
    if explicit is not None:
        if explicit not in {CONTROL_MODE_SIMPLE, CONTROL_MODE_CUSTOM}:
            raise HomeAssistantConfigurationError("heat source control mode is invalid")
        return str(explicit)
    if (
        data.get(CONF_ENABLE_SERVICE_DOMAIN) == "switch"
        and data.get(CONF_ENABLE_SERVICE_NAME) == "turn_on"
        and data.get(CONF_DISABLE_SERVICE_DOMAIN) == "switch"
        and data.get(CONF_DISABLE_SERVICE_NAME) == "turn_off"
        and data.get(CONF_ENABLE_TARGET_ENTITY_ID) == data.get(CONF_DISABLE_TARGET_ENTITY_ID)
    ):
        return CONTROL_MODE_SIMPLE
    return CONTROL_MODE_CUSTOM


def simple_heat_source_binding(entity_id: str) -> HomeAssistantHeatSourceBinding:
    """Derive the standard switch service calls from one controlled entity."""

    return HomeAssistantHeatSourceBinding(
        enable_heating=HomeAssistantServiceCall(
            domain="switch",
            service="turn_on",
            target_entity_id=entity_id,
        ),
        disable_heating=HomeAssistantServiceCall(
            domain="switch",
            service="turn_off",
            target_entity_id=entity_id,
        ),
    )


def normalize_identifier(value: str) -> str:
    """Normalize a user-facing name into a deterministic ASCII identifier."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", ascii_value)).strip("_")


def generated_identifier(value: str, label: str) -> str:
    """Generate and validate a stable identifier from a display name."""

    identifier = normalize_identifier(value)
    validate_identifier(identifier, label)
    return identifier


def validate_identifier(value: str, label: str) -> None:
    """Validate the public format used by stable Controlel IDs."""

    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise HomeAssistantConfigurationError(
            f"{label} must start with a lowercase letter and contain only lowercase letters, numbers, and underscores"
        )


def _required_string(
    data: Mapping[str, Any],
    key: str,
    *,
    fallback: str | None = None,
) -> str:
    if key in data:
        value = data[key]
    elif fallback is not None:
        value = data[fallback]
    else:
        raise KeyError(key)
    if not isinstance(value, str) or not value.strip():
        raise HomeAssistantConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _finite_number(data: Mapping[str, Any], key: str) -> float:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HomeAssistantConfigurationError(f"{key} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise HomeAssistantConfigurationError(f"{key} must be a finite number")
    return result


def _finite_duration(
    data: Mapping[str, Any],
    key: str,
    *,
    positive: bool = False,
) -> float:
    value = _finite_number(data, key)
    if value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise HomeAssistantConfigurationError(f"{key} must be {qualifier}")
    return value


def _validate_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HomeAssistantConfigurationError(f"{label} must be a non-empty string")


def _validate_slug(value: str, label: str) -> None:
    if not isinstance(value, str) or _SLUG_PATTERN.fullmatch(value) is None:
        raise HomeAssistantConfigurationError(f"{label} must contain only lowercase letters, numbers, and underscores")


def _validate_entity_id(value: str, label: str) -> None:
    if not isinstance(value, str) or _ENTITY_ID_PATTERN.fullmatch(value) is None:
        raise HomeAssistantConfigurationError(f"{label} must be a valid entity ID")

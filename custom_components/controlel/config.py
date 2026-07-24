"""Immutable effective configuration for the Home Assistant adapter."""

import re
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
    DOMAIN,
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
_ENTITY_ID_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


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
        sensor_id = SensorId(_required_string(data, CONF_SENSOR_ID))
        zone_id = ZoneId(_required_string(data, CONF_ZONE_ID))
        timeout_action = HeatingAction(_required_string(data, CONF_INDETERMINATE_TIMEOUT_ACTION))
        target_temperature = Temperature(_finite_number(data, CONF_TARGET_TEMPERATURE))
        primary_max_age = timedelta(seconds=_finite_duration(data, CONF_PRIMARY_MEASUREMENT_MAX_AGE, positive=True))
        max_future_skew = timedelta(seconds=_finite_duration(data, CONF_MAX_FUTURE_SKEW))
        grace_period = timedelta(seconds=_finite_duration(data, CONF_INDETERMINATE_GRACE_PERIOD))
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
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, HomeAssistantConfigurationError):
            raise
        raise HomeAssistantConfigurationError(str(error)) from error


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
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

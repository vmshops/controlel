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
    CONF_DEBUG_DURATION,
    CONF_DEBUG_UNTIL_CHANGED,
    CONF_DIAGNOSTIC_PROFILE,
    CONF_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
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
    DEFAULT_DEBUG_UNTIL_CHANGED,
    DEFAULT_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
    DEFAULT_HEAT_DELIVERY_ASSIST_TARGET,
    DIAGNOSTIC_PROFILE_BASIC,
    DIAGNOSTIC_PROFILE_DEBUG,
    DIAGNOSTIC_PROFILE_DETAILED,
    DOMAIN,
    HEAT_DELIVERY_ASSIST_ALWAYS,
    HEAT_DELIVERY_ASSIST_NONE,
    HEAT_DELIVERY_MODE_SETPOINT_ASSIST,
    HEAT_DELIVERY_MODE_UNMANAGED,
    HEAT_DELIVERY_OWNERSHIP_CONTROLEL,
    HEAT_DELIVERY_OWNERSHIP_DEVICE,
    LEGACY_DIAGNOSTIC_PROFILE,
    LEGACY_HEAT_DEMAND_CONFIRMATION_DURATION,
    LEGACY_HEATING_TURN_OFF_DIFFERENTIAL,
    LEGACY_HEATING_TURN_ON_DIFFERENTIAL,
    LEGACY_MINIMUM_HEATING_OFF_TIME,
    LEGACY_MINIMUM_HEATING_ON_TIME,
    MAX_HEAT_DEMAND_CONFIRMATION_DURATION,
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
class ZoneControlConfiguration:
    sensor_id: SensorId
    sensor_name: str
    temperature_entity_id: str
    zone_id: ZoneId
    zone_name: str
    target_temperature: Temperature
    heating_turn_on_differential: float
    heating_turn_off_differential: float
    heat_demand_confirmation_duration: timedelta
    primary_measurement_max_age: timedelta


@dataclass(frozen=True)
class HeatSourceConfiguration:
    binding: HomeAssistantHeatSourceBinding
    control_mode: str
    controlled_entity_id: str | None
    minimum_heating_on_time: timedelta
    minimum_heating_off_time: timedelta


@dataclass(frozen=True)
class DiagnosticConfiguration:
    profile: str
    debug_duration: timedelta | None
    configured_debug_duration: timedelta
    profile_before_debug: str


@dataclass(frozen=True)
class HeatDeliveryConfiguration:
    mode: str
    actuator_entity_id: str | None
    ownership: str
    assist_policy: str
    assist_target_temperature: float


@dataclass(frozen=True)
class HomeAssistantIntegrationConfig:
    sensor_id: SensorId
    sensor_name: str
    temperature_entity_id: str
    zone_id: ZoneId
    zone_name: str
    target_temperature: Temperature
    heating_turn_on_differential: float
    heating_turn_off_differential: float
    minimum_heating_on_time: timedelta
    minimum_heating_off_time: timedelta
    primary_measurement_max_age: timedelta
    max_future_skew: timedelta
    indeterminate_grace_period: timedelta
    indeterminate_timeout_action: HeatingAction
    heat_source: HomeAssistantHeatSourceBinding
    heat_source_control_mode: str
    controlled_entity_id: str | None
    diagnostic_profile: str
    debug_duration: timedelta | None
    configured_debug_duration: timedelta
    diagnostic_profile_before_debug: str
    heat_demand_confirmation_duration: timedelta = timedelta(0)
    heat_delivery_mode: str = HEAT_DELIVERY_MODE_UNMANAGED
    heat_delivery_actuator_entity_id: str | None = None
    heat_delivery_ownership: str = HEAT_DELIVERY_OWNERSHIP_DEVICE
    heat_delivery_assist_policy: str = HEAT_DELIVERY_ASSIST_NONE
    heat_delivery_assist_target: float = DEFAULT_HEAT_DELIVERY_ASSIST_TARGET

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
        for value, label in (
            (self.heating_turn_on_differential, "heating turn-on differential"),
            (self.heating_turn_off_differential, "heating turn-off differential"),
        ):
            if not isfinite(value) or value < 0:
                raise HomeAssistantConfigurationError(f"{label} must be a finite non-negative number")
        if self.minimum_heating_on_time < timedelta(0):
            raise HomeAssistantConfigurationError("minimum heating-on time must not be negative")
        if self.minimum_heating_off_time < timedelta(0):
            raise HomeAssistantConfigurationError("minimum heating-off time must not be negative")
        if self.heat_demand_confirmation_duration < timedelta(0):
            raise HomeAssistantConfigurationError("heat demand confirmation duration must not be negative")
        if self.heat_demand_confirmation_duration > timedelta(seconds=MAX_HEAT_DEMAND_CONFIRMATION_DURATION):
            raise HomeAssistantConfigurationError("heat demand confirmation duration must not exceed 24 hours")
        if self.heat_source_control_mode not in {
            CONTROL_MODE_SIMPLE,
            CONTROL_MODE_CUSTOM,
        }:
            raise HomeAssistantConfigurationError("heat source control mode is invalid")
        if self.diagnostic_profile not in {
            DIAGNOSTIC_PROFILE_BASIC,
            DIAGNOSTIC_PROFILE_DETAILED,
            DIAGNOSTIC_PROFILE_DEBUG,
        }:
            raise HomeAssistantConfigurationError("diagnostic profile is invalid")
        if self.debug_duration is not None and self.debug_duration <= timedelta(0):
            raise HomeAssistantConfigurationError("Debug duration must be positive")
        if self.configured_debug_duration <= timedelta(0):
            raise HomeAssistantConfigurationError("configured Debug duration must be positive")
        if self.diagnostic_profile_before_debug not in {
            DIAGNOSTIC_PROFILE_BASIC,
            DIAGNOSTIC_PROFILE_DETAILED,
        }:
            raise HomeAssistantConfigurationError("profile before Debug is invalid")
        if self.heat_delivery_mode not in {
            HEAT_DELIVERY_MODE_UNMANAGED,
            HEAT_DELIVERY_MODE_SETPOINT_ASSIST,
        }:
            raise HomeAssistantConfigurationError("heat delivery mode is invalid")
        if self.heat_delivery_ownership not in {
            HEAT_DELIVERY_OWNERSHIP_DEVICE,
            HEAT_DELIVERY_OWNERSHIP_CONTROLEL,
        }:
            raise HomeAssistantConfigurationError("heat delivery ownership is invalid")
        if self.heat_delivery_assist_policy not in {
            HEAT_DELIVERY_ASSIST_NONE,
            HEAT_DELIVERY_ASSIST_ALWAYS,
        }:
            raise HomeAssistantConfigurationError("heat delivery assist policy is invalid")
        if not isfinite(self.heat_delivery_assist_target):
            raise HomeAssistantConfigurationError("heat delivery assist target must be finite")
        if self.heat_delivery_mode == HEAT_DELIVERY_MODE_SETPOINT_ASSIST:
            if not self.heat_delivery_actuator_entity_id:
                raise HomeAssistantConfigurationError("setpoint assist requires an actuator entity")
            _validate_entity_id(self.heat_delivery_actuator_entity_id, "heat delivery actuator entity ID")
            if not self.heat_delivery_actuator_entity_id.startswith("climate."):
                raise HomeAssistantConfigurationError("setpoint assist actuator must be a climate entity")
            if self.heat_delivery_ownership != HEAT_DELIVERY_OWNERSHIP_CONTROLEL:
                raise HomeAssistantConfigurationError("setpoint assist requires Controlel ownership")

    @property
    def sensor_binding(self) -> HomeAssistantSensorBinding:
        return HomeAssistantSensorBinding(
            entity_id=self.temperature_entity_id,
            sensor_id=self.sensor_id,
        )

    @property
    def zone_control(self) -> ZoneControlConfiguration:
        return ZoneControlConfiguration(
            sensor_id=self.sensor_id,
            sensor_name=self.sensor_name,
            temperature_entity_id=self.temperature_entity_id,
            zone_id=self.zone_id,
            zone_name=self.zone_name,
            target_temperature=self.target_temperature,
            heating_turn_on_differential=self.heating_turn_on_differential,
            heating_turn_off_differential=self.heating_turn_off_differential,
            heat_demand_confirmation_duration=(self.heat_demand_confirmation_duration),
            primary_measurement_max_age=self.primary_measurement_max_age,
        )

    @property
    def heat_source_configuration(self) -> HeatSourceConfiguration:
        return HeatSourceConfiguration(
            binding=self.heat_source,
            control_mode=self.heat_source_control_mode,
            controlled_entity_id=self.controlled_entity_id,
            minimum_heating_on_time=self.minimum_heating_on_time,
            minimum_heating_off_time=self.minimum_heating_off_time,
        )

    @property
    def diagnostic_configuration(self) -> DiagnosticConfiguration:
        return DiagnosticConfiguration(
            profile=self.diagnostic_profile,
            debug_duration=self.debug_duration,
            configured_debug_duration=self.configured_debug_duration,
            profile_before_debug=self.diagnostic_profile_before_debug,
        )

    @property
    def heat_delivery_configuration(self) -> HeatDeliveryConfiguration:
        return HeatDeliveryConfiguration(
            mode=self.heat_delivery_mode,
            actuator_entity_id=self.heat_delivery_actuator_entity_id,
            ownership=self.heat_delivery_ownership,
            assist_policy=self.heat_delivery_assist_policy,
            assist_target_temperature=self.heat_delivery_assist_target,
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
        turn_on_differential = _finite_optional_number(
            data,
            CONF_HEATING_TURN_ON_DIFFERENTIAL,
            LEGACY_HEATING_TURN_ON_DIFFERENTIAL,
        )
        turn_off_differential = _finite_optional_number(
            data,
            CONF_HEATING_TURN_OFF_DIFFERENTIAL,
            LEGACY_HEATING_TURN_OFF_DIFFERENTIAL,
        )
        minimum_on_time = timedelta(
            seconds=_finite_optional_duration(
                data,
                CONF_MINIMUM_HEATING_ON_TIME,
                LEGACY_MINIMUM_HEATING_ON_TIME,
            )
        )
        minimum_off_time = timedelta(
            seconds=_finite_optional_duration(
                data,
                CONF_MINIMUM_HEATING_OFF_TIME,
                LEGACY_MINIMUM_HEATING_OFF_TIME,
            )
        )
        confirmation_duration = timedelta(
            seconds=_finite_optional_duration(
                data,
                CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
                LEGACY_HEAT_DEMAND_CONFIRMATION_DURATION,
            )
        )
        primary_max_age = timedelta(seconds=_finite_duration(data, CONF_PRIMARY_MEASUREMENT_MAX_AGE, positive=True))
        max_future_skew = timedelta(seconds=_finite_duration(data, CONF_MAX_FUTURE_SKEW))
        grace_period = timedelta(seconds=_finite_duration(data, CONF_INDETERMINATE_GRACE_PERIOD))
        diagnostic_profile = str(data.get(CONF_DIAGNOSTIC_PROFILE, LEGACY_DIAGNOSTIC_PROFILE))
        debug_until_changed = data.get(
            CONF_DEBUG_UNTIL_CHANGED,
            DEFAULT_DEBUG_UNTIL_CHANGED,
        )
        if not isinstance(debug_until_changed, bool):
            raise HomeAssistantConfigurationError("Debug until changed must be a boolean")
        configured_debug_duration = timedelta(
            seconds=_finite_optional_duration(
                data,
                CONF_DEBUG_DURATION,
                DEFAULT_DEBUG_DURATION,
            )
        )
        debug_duration = None if debug_until_changed else configured_debug_duration
        profile_before_debug = str(
            data.get(
                CONF_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
                DEFAULT_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
            )
        )
        control_mode = infer_control_mode(data)
        heat_delivery_mode = str(data.get(CONF_HEAT_DELIVERY_MODE, HEAT_DELIVERY_MODE_UNMANAGED))
        heat_delivery_entity = data.get(CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID)
        if heat_delivery_entity is not None:
            heat_delivery_entity = str(heat_delivery_entity).strip() or None
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
            heating_turn_on_differential=turn_on_differential,
            heating_turn_off_differential=turn_off_differential,
            heat_demand_confirmation_duration=confirmation_duration,
            minimum_heating_on_time=minimum_on_time,
            minimum_heating_off_time=minimum_off_time,
            primary_measurement_max_age=primary_max_age,
            max_future_skew=max_future_skew,
            indeterminate_grace_period=grace_period,
            indeterminate_timeout_action=timeout_action,
            heat_source=heat_source,
            heat_source_control_mode=control_mode,
            controlled_entity_id=controlled_entity_id,
            diagnostic_profile=diagnostic_profile,
            debug_duration=debug_duration,
            configured_debug_duration=configured_debug_duration,
            diagnostic_profile_before_debug=profile_before_debug,
            heat_delivery_mode=heat_delivery_mode,
            heat_delivery_actuator_entity_id=heat_delivery_entity,
            heat_delivery_ownership=str(data.get(CONF_HEAT_DELIVERY_OWNERSHIP, HEAT_DELIVERY_OWNERSHIP_DEVICE)),
            heat_delivery_assist_policy=str(data.get(CONF_HEAT_DELIVERY_ASSIST_POLICY, HEAT_DELIVERY_ASSIST_NONE)),
            heat_delivery_assist_target=_finite_optional_number(
                data, CONF_HEAT_DELIVERY_ASSIST_TARGET, DEFAULT_HEAT_DELIVERY_ASSIST_TARGET
            ),
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


def _finite_optional_number(
    data: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    return _finite_number({key: data.get(key, default)}, key)


def _finite_optional_duration(
    data: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    value = _finite_optional_number(data, key, default)
    if value < 0:
        raise HomeAssistantConfigurationError(f"{key} must be non-negative")
    return value


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

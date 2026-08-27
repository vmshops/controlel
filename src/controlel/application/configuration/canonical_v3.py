"""Scoped canonical configuration schema v3.

The immutable document separates zone demand, shared heat-source protection,
diagnostics, and notifications while truthfully retaining provider identity
and observation boundaries.  Runtime adapters consume the document as one
whole authority; the schema itself remains provider and runtime neutral.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import UnionType
from typing import Final, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.config import JsonDict

from controlel.application.configuration.canonical_defaults import (
    NEW_CONFIGURATION_DEBUG_DURATION_SECONDS,
    NEW_CONFIGURATION_DEBUG_UNTIL_CHANGED,
    NEW_CONFIGURATION_DIAGNOSTIC_STEADY_PROFILE,
    NEW_CONFIGURATION_HEAT_DELIVERY_ASSIST_POLICY,
    NEW_CONFIGURATION_HEAT_DELIVERY_ASSIST_TARGET_CELSIUS,
    NEW_CONFIGURATION_HEAT_DEMAND_CONFIRMATION_SECONDS,
    NEW_CONFIGURATION_HEATING_TURN_OFF_DIFFERENTIAL_CELSIUS,
    NEW_CONFIGURATION_HEATING_TURN_ON_DIFFERENTIAL_CELSIUS,
    NEW_CONFIGURATION_INDETERMINATE_GRACE_PERIOD_SECONDS,
    NEW_CONFIGURATION_MAXIMUM_FUTURE_SKEW_SECONDS,
    NEW_CONFIGURATION_MINIMUM_HEATING_OFF_SECONDS,
    NEW_CONFIGURATION_MINIMUM_HEATING_ON_SECONDS,
    NEW_CONFIGURATION_PRIMARY_MEASUREMENT_MAX_AGE_SECONDS,
    NEW_CONFIGURATION_TARGET_TEMPERATURE_CELSIUS,
)
from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    aware_datetime,
    canonical_json,
    immutable_json_mapping,
    normalize_json,
)
from controlel.application.setup.model import IdentityQuality, ProviderReference
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.notifications import (
    DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW,
    DEFAULT_CRITICAL_RATE_WINDOW,
    DEFAULT_NOTIFICATION_HISTORY_CAPACITY,
    DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW,
    DEFAULT_NOTIFICATION_RATE_WINDOW,
    MAX_CRITICAL_MAXIMUM_PER_WINDOW,
    MAX_CRITICAL_RATE_WINDOW,
    MAX_NOTIFICATION_HISTORY_CAPACITY,
    MAX_NOTIFICATION_MAXIMUM_PER_WINDOW,
    MAX_NOTIFICATION_RATE_WINDOW,
    MAX_NOTIFICATION_RECIPIENTS,
    NotificationLevel,
)
from controlel.domain.operational_events import OperationalEventCategory

CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3: Final[Literal[3]] = 3
CANONICAL_CONFIGURATION_V3_MIGRATION_POLICY_VERSION = 1
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z0-9_]+$"
_HOME_ASSISTANT_NOTIFY_TARGET_PATTERN = r"^notify\.[a-z0-9_]+$"
_FORBIDDEN_OPERATIONAL_CONFIGURATION_KEYS = frozenset(
    {
        "command_outcome",
        "command_outcomes",
        "counters",
        "current_debug_state",
        "current_debug_expiry",
        "deadline",
        "deadlines",
        "debug_expiry",
        "diagnostic_profile_before_debug",
        "delivery_result",
        "delivery_results",
        "demand_decision",
        "demand_decisions",
        "event",
        "event_history",
        "events",
        "measurement",
        "measurements",
        "notification_delivery_result",
        "notification_delivery_results",
        "notification_history",
        "operational_history",
        "trace",
        "traces",
    }
)


class ConfigurationOwnerV3(StrEnum):
    ZONE = "zone"
    HEAT_SOURCE = "heat_source"
    HEATING_GLOBAL = "heating_global"
    HEAT_DELIVERY = "heat_delivery"
    DIAGNOSTICS = "diagnostics"
    NOTIFICATIONS = "notifications"


class ConfigurationEditabilityV3(StrEnum):
    EDITABLE = "editable"
    IMMUTABLE_IDENTITY = "immutable_identity"
    EDITABLE_PROVIDER_BINDING = "editable_provider_binding"


class ConfigurationDefaultPolicyV3(StrEnum):
    REQUIRED = "required"
    RECOMMENDED_NEW_CONFIGURATION = "recommended_new_configuration"
    OPTIONAL_NONE = "optional_none"
    SCHEMA_DEFAULT = "schema_default"


def _metadata(
    owner: ConfigurationOwnerV3,
    *,
    unit: str | None = None,
    editability: ConfigurationEditabilityV3 = ConfigurationEditabilityV3.EDITABLE,
    default_policy: ConfigurationDefaultPolicyV3,
) -> JsonDict:
    return {
        "configuration_owner": owner.value,
        "configuration_unit": unit,
        "configuration_editability": editability.value,
        "configuration_default_policy": default_policy.value,
    }


class _CanonicalConfigurationModelV3(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True, serialize_by_alias=True)


class ZoneTopologyV3(_CanonicalConfigurationModelV3):
    """Stable provider topology; display labels and Controlel identity stay separate."""

    area_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )
    floor_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )

    @field_validator("area_reference", "floor_reference")
    @classmethod
    def topology_references_must_be_stable(
        cls,
        value: ProviderReference | None,
        info: object,
    ) -> ProviderReference | None:
        return _stable_reference(value, str(getattr(info, "field_name", "topology reference")))

    @model_validator(mode="after")
    def topology_references_must_share_provider_scope(self) -> ZoneTopologyV3:
        if self.area_reference is None or self.floor_reference is None:
            return self
        if (
            self.area_reference.provider,
            self.area_reference.provider_instance_id,
        ) != (
            self.floor_reference.provider,
            self.floor_reference.provider_instance_id,
        ):
            raise ValueError("area and floor references must belong to the same provider instance")
        return self


class PrimaryTemperatureSensorV3(_CanonicalConfigurationModelV3):
    sensor_id: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            editability=ConfigurationEditabilityV3.IMMUTABLE_IDENTITY,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    display_name: str = Field(
        min_length=1,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    provider_reference: ProviderReference = Field(
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        )
    )

    @field_validator("provider_reference")
    @classmethod
    def primary_sensor_reference_must_be_stable(cls, value: ProviderReference) -> ProviderReference:
        stable = _stable_reference(value, "primary sensor provider reference")
        assert stable is not None
        return stable

    @model_validator(mode="after")
    def logical_id_must_not_be_a_provider_locator(self) -> PrimaryTemperatureSensorV3:
        _logical_id_must_be_separate(self.sensor_id, self.provider_reference, "sensor_id")
        return self


class ZoneDemandPolicyV3(_CanonicalConfigurationModelV3):
    target_temperature_celsius: float = Field(
        default=NEW_CONFIGURATION_TARGET_TEMPERATURE_CELSIUS,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            unit="celsius",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    heating_turn_on_differential_celsius: float = Field(
        default=NEW_CONFIGURATION_HEATING_TURN_ON_DIFFERENTIAL_CELSIUS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            unit="celsius_delta",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    heating_turn_off_differential_celsius: float = Field(
        default=NEW_CONFIGURATION_HEATING_TURN_OFF_DIFFERENTIAL_CELSIUS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            unit="celsius_delta",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    heat_demand_confirmation_seconds: float = Field(
        default=NEW_CONFIGURATION_HEAT_DEMAND_CONFIRMATION_SECONDS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    primary_measurement_max_age_seconds: float = Field(
        default=NEW_CONFIGURATION_PRIMARY_MEASUREMENT_MAX_AGE_SECONDS,
        gt=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )

    @field_validator("*")
    @classmethod
    def demand_numbers_must_be_finite(cls, value: object, info: object) -> object:
        return _finite_number(value, str(getattr(info, "field_name", "zone demand field")))


class ZoneConfigurationV3(_CanonicalConfigurationModelV3):
    zone_id: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            editability=ConfigurationEditabilityV3.IMMUTABLE_IDENTITY,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    display_name: str = Field(
        min_length=1,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.ZONE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    topology: ZoneTopologyV3 = Field(default_factory=ZoneTopologyV3)
    primary_temperature_sensor: PrimaryTemperatureSensorV3
    demand_policy: ZoneDemandPolicyV3 = Field(default_factory=ZoneDemandPolicyV3)

    @model_validator(mode="after")
    def logical_id_must_not_be_an_area_reference(self) -> ZoneConfigurationV3:
        if self.topology.area_reference is not None:
            _logical_id_must_be_separate(self.zone_id, self.topology.area_reference, "zone_id")
        return self


class HeatingGlobalConfigurationV3(_CanonicalConfigurationModelV3):
    maximum_future_skew_seconds: float = Field(
        default=NEW_CONFIGURATION_MAXIMUM_FUTURE_SKEW_SECONDS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEATING_GLOBAL,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )

    @field_validator("maximum_future_skew_seconds")
    @classmethod
    def future_skew_must_be_finite(cls, value: object) -> float:
        return _finite_number(value, "maximum future skew")


class ProviderServiceCallV3(_CanonicalConfigurationModelV3):
    """Requested provider command; a successful call is not physical evidence."""

    domain: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    service: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    command_target_reference: ProviderReference = Field(
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        )
    )

    @field_validator("domain")
    @classmethod
    def command_must_not_target_controlel_domain(cls, value: str) -> str:
        if value == "controlel":
            raise ValueError("Controlel cannot call its own integration service domain")
        return value

    @field_validator("command_target_reference")
    @classmethod
    def command_target_reference_must_be_stable(cls, value: ProviderReference) -> ProviderReference:
        stable = _stable_reference(value, "heat-source command target reference")
        assert stable is not None
        return stable


class HeatSourceCommandStrategyV3(_CanonicalConfigurationModelV3):
    mode: Literal["simple", "custom"] = Field(
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        )
    )
    enable_permission: ProviderServiceCallV3
    disable_permission: ProviderServiceCallV3

    @model_validator(mode="after")
    def simple_mode_must_be_one_truthful_switch_contract(self) -> HeatSourceCommandStrategyV3:
        if self.mode != "simple":
            return self
        if (self.enable_permission.domain, self.enable_permission.service) != ("switch", "turn_on"):
            raise ValueError("simple source enable permission must use switch.turn_on")
        if (self.disable_permission.domain, self.disable_permission.service) != ("switch", "turn_off"):
            raise ValueError("simple source disable permission must use switch.turn_off")
        if (
            self.enable_permission.command_target_reference.semantic_data()
            != self.disable_permission.command_target_reference.semantic_data()
        ):
            raise ValueError("simple source permission commands must use the same provider target")
        return self


class HeatSourceObservationBindingsV3(_CanonicalConfigurationModelV3):
    """Separate actuator reports from evidence of physical source operation."""

    reported_actuator_state_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )
    physical_operation_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )

    @field_validator("reported_actuator_state_reference", "physical_operation_reference")
    @classmethod
    def observation_references_must_be_stable(
        cls,
        value: ProviderReference | None,
        info: object,
    ) -> ProviderReference | None:
        return _stable_reference(value, str(getattr(info, "field_name", "source observation reference")))

    @model_validator(mode="after")
    def actuator_report_must_not_double_as_physical_operation(self) -> HeatSourceObservationBindingsV3:
        if (
            self.reported_actuator_state_reference is not None
            and self.physical_operation_reference is not None
            and self.reported_actuator_state_reference.semantic_data()
            == self.physical_operation_reference.semantic_data()
        ):
            raise ValueError("reported actuator state and physical source operation require distinct evidence")
        return self


class HeatSourceProtectionPolicyV3(_CanonicalConfigurationModelV3):
    indeterminate_grace_period_seconds: float = Field(
        default=NEW_CONFIGURATION_INDETERMINATE_GRACE_PERIOD_SECONDS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    indeterminate_timeout_action: HeatingAction = Field(
        default=HeatingAction.DISABLE_HEATING,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    minimum_heating_on_seconds: float = Field(
        default=NEW_CONFIGURATION_MINIMUM_HEATING_ON_SECONDS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    minimum_heating_off_seconds: float = Field(
        default=NEW_CONFIGURATION_MINIMUM_HEATING_OFF_SECONDS,
        ge=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )

    @field_validator(
        "indeterminate_grace_period_seconds",
        "minimum_heating_on_seconds",
        "minimum_heating_off_seconds",
    )
    @classmethod
    def protection_durations_must_be_finite(cls, value: object, info: object) -> float:
        return _finite_number(value, str(getattr(info, "field_name", "heat-source protection duration")))


class HeatSourceConfigurationV3(_CanonicalConfigurationModelV3):
    heat_source_id: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            editability=ConfigurationEditabilityV3.IMMUTABLE_IDENTITY,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    display_name: str = Field(
        min_length=1,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    provider_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_SOURCE,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )
    command_strategy: HeatSourceCommandStrategyV3
    observations: HeatSourceObservationBindingsV3 = Field(default_factory=HeatSourceObservationBindingsV3)
    protection: HeatSourceProtectionPolicyV3 = Field(default_factory=HeatSourceProtectionPolicyV3)

    @field_validator("provider_reference")
    @classmethod
    def source_reference_must_be_stable(cls, value: ProviderReference | None) -> ProviderReference | None:
        return _stable_reference(value, "heat-source provider reference")

    @model_validator(mode="after")
    def logical_id_must_not_be_a_provider_reference(self) -> HeatSourceConfigurationV3:
        references = (
            self.provider_reference,
            self.command_strategy.enable_permission.command_target_reference,
            self.command_strategy.disable_permission.command_target_reference,
            self.observations.reported_actuator_state_reference,
            self.observations.physical_operation_reference,
        )
        for reference in references:
            if reference is not None:
                _logical_id_must_be_separate(self.heat_source_id, reference, "heat_source_id")
        return self


class ZoneHeatDeliveryConfigurationV3(_CanonicalConfigurationModelV3):
    zone_id: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            editability=ConfigurationEditabilityV3.IMMUTABLE_IDENTITY,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    mode: Literal["unmanaged", "setpoint_assist"] = Field(
        default="unmanaged",
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    actuator_reference: ProviderReference | None = Field(
        default=None,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            editability=ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING,
            default_policy=ConfigurationDefaultPolicyV3.OPTIONAL_NONE,
        ),
    )
    ownership: Literal["device_owned", "controlel_owned"] = Field(
        default="device_owned",
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    assist_policy: Literal["no_assist", "always_assist_while_heating"] = Field(
        default=NEW_CONFIGURATION_HEAT_DELIVERY_ASSIST_POLICY,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    assist_target_celsius: float = Field(
        default=NEW_CONFIGURATION_HEAT_DELIVERY_ASSIST_TARGET_CELSIUS,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.HEAT_DELIVERY,
            unit="celsius",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )

    @field_validator("actuator_reference")
    @classmethod
    def actuator_reference_must_be_stable(cls, value: ProviderReference | None) -> ProviderReference | None:
        return _stable_reference(value, "heat-delivery actuator reference")

    @field_validator("assist_target_celsius")
    @classmethod
    def assist_target_must_be_finite(cls, value: object) -> float:
        return _finite_number(value, "heat-delivery assist target")

    @model_validator(mode="after")
    def setpoint_assist_requires_explicit_controlel_ownership(self) -> ZoneHeatDeliveryConfigurationV3:
        if self.mode == "setpoint_assist":
            if self.actuator_reference is None:
                raise ValueError("setpoint assist requires an actuator provider reference")
            if self.ownership != "controlel_owned":
                raise ValueError("setpoint assist requires Controlel ownership")
        elif self.actuator_reference is not None:
            raise ValueError("unmanaged heat delivery cannot bind an actuator")
        return self


class HeatingConfigurationV3(_CanonicalConfigurationModelV3):
    global_configuration: HeatingGlobalConfigurationV3 = Field(
        default_factory=HeatingGlobalConfigurationV3,
        alias="global",
    )
    zones: tuple[ZoneConfigurationV3, ...] = Field(min_length=1, max_length=1)
    heat_sources: tuple[HeatSourceConfigurationV3, ...] = Field(min_length=1, max_length=1)
    heat_delivery: tuple[ZoneHeatDeliveryConfigurationV3, ...] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def current_single_zone_topology_must_be_consistent(self) -> HeatingConfigurationV3:
        zone_ids = tuple(zone.zone_id for zone in self.zones)
        source_ids = tuple(source.heat_source_id for source in self.heat_sources)
        delivery_zone_ids = tuple(delivery.zone_id for delivery in self.heat_delivery)
        if len(set(zone_ids)) != len(zone_ids):
            raise ValueError("zone IDs must be unique")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("heat-source IDs must be unique")
        if delivery_zone_ids != zone_ids:
            raise ValueError("heat-delivery configuration must match the configured zones exactly")
        return self


class DiagnosticDebugPolicyV3(_CanonicalConfigurationModelV3):
    configured_duration_seconds: float = Field(
        default=NEW_CONFIGURATION_DEBUG_DURATION_SECONDS,
        gt=0,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.DIAGNOSTICS,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    until_changed: bool = Field(
        default=NEW_CONFIGURATION_DEBUG_UNTIL_CHANGED,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.DIAGNOSTICS,
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )

    @field_validator("configured_duration_seconds")
    @classmethod
    def debug_duration_must_be_finite(cls, value: object) -> float:
        return _finite_number(value, "configured Debug duration")


class DiagnosticsConfigurationV3(_CanonicalConfigurationModelV3):
    """Configured steady diagnostics only; active Debug state is runtime data."""

    steady_profile: Literal["basic", "detailed"] = Field(
        default=NEW_CONFIGURATION_DIAGNOSTIC_STEADY_PROFILE,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.DIAGNOSTICS,
            default_policy=ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION,
        ),
    )
    debug_policy: DiagnosticDebugPolicyV3 = Field(default_factory=DiagnosticDebugPolicyV3)


class NotificationRecipientConfigurationV3(_CanonicalConfigurationModelV3):
    recipient_id: str = Field(
        min_length=1,
        pattern=_IDENTIFIER_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            editability=ConfigurationEditabilityV3.IMMUTABLE_IDENTITY,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    transport: Literal["home_assistant_notify"] = Field(
        default="home_assistant_notify",
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    target: str = Field(
        min_length=1,
        pattern=_HOME_ASSISTANT_NOTIFY_TARGET_PATTERN,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.REQUIRED,
        ),
    )
    enabled: bool = Field(
        default=True,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    minimum_level: NotificationLevel = Field(
        default=NotificationLevel.OPERATIONAL,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    categories: tuple[OperationalEventCategory, ...] = Field(
        default=(),
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )

    @field_validator("categories", mode="after")
    @classmethod
    def categories_must_be_deterministic(
        cls,
        value: tuple[OperationalEventCategory, ...],
    ) -> tuple[OperationalEventCategory, ...]:
        return tuple(sorted(set(value), key=lambda item: item.value))


class NotificationsConfigurationV3(_CanonicalConfigurationModelV3):
    enabled: bool = Field(
        default=False,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    recipients: tuple[NotificationRecipientConfigurationV3, ...] = Field(default=())
    maximum_per_window: int = Field(
        default=DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW,
        ge=1,
        le=MAX_NOTIFICATION_MAXIMUM_PER_WINDOW,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            unit="notifications_per_window",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    rate_window_seconds: float = Field(
        default=DEFAULT_NOTIFICATION_RATE_WINDOW.total_seconds(),
        ge=1,
        le=MAX_NOTIFICATION_RATE_WINDOW.total_seconds(),
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    critical_maximum_per_window: int = Field(
        default=DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW,
        ge=1,
        le=MAX_CRITICAL_MAXIMUM_PER_WINDOW,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            unit="notifications_per_window",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    critical_rate_window_seconds: float = Field(
        default=DEFAULT_CRITICAL_RATE_WINDOW.total_seconds(),
        ge=1,
        le=MAX_CRITICAL_RATE_WINDOW.total_seconds(),
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            unit="seconds",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )
    history_capacity: int = Field(
        default=DEFAULT_NOTIFICATION_HISTORY_CAPACITY,
        ge=1,
        le=MAX_NOTIFICATION_HISTORY_CAPACITY,
        strict=True,
        json_schema_extra=_metadata(
            ConfigurationOwnerV3.NOTIFICATIONS,
            unit="notification_records",
            default_policy=ConfigurationDefaultPolicyV3.SCHEMA_DEFAULT,
        ),
    )

    @field_validator("rate_window_seconds", "critical_rate_window_seconds")
    @classmethod
    def notification_windows_must_be_finite(cls, value: object, info: object) -> float:
        return _finite_number(value, str(getattr(info, "field_name", "notification window")))

    @model_validator(mode="after")
    def recipients_must_be_bounded_and_unique(self) -> NotificationsConfigurationV3:
        if len(self.recipients) > MAX_NOTIFICATION_RECIPIENTS:
            raise ValueError(f"notification recipients must not exceed {MAX_NOTIFICATION_RECIPIENTS}")
        recipient_ids = tuple(recipient.recipient_id for recipient in self.recipients)
        if len(recipient_ids) != len(set(recipient_ids)):
            raise ValueError("notification recipient IDs must be unique")
        enabled_bindings = tuple(
            (recipient.transport, recipient.target) for recipient in self.recipients if recipient.enabled
        )
        if len(enabled_bindings) != len(set(enabled_bindings)):
            raise ValueError("enabled notification transport and target bindings must be unique")
        return self


class CanonicalConfigurationRevisionV3(_CanonicalConfigurationModelV3):
    """Immutable v3 revision with independently-owned configuration scopes."""

    schema_version: Literal[3] = CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3
    configuration_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    parent_revision_id: str | None = None
    environment_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    created_at: datetime
    actor: str = Field(min_length=1)
    source: str = Field(min_length=1)
    change_kind: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    core_version: str = Field(min_length=1)
    integration_version: str | None = None
    heating: HeatingConfigurationV3
    diagnostics: DiagnosticsConfigurationV3 = Field(default_factory=DiagnosticsConfigurationV3)
    notifications: NotificationsConfigurationV3 = Field(default_factory=NotificationsConfigurationV3)
    lineage: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    import_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    migration_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    semantic_configuration_fingerprint: str = Field(default="", pattern=_HASH_PATTERN)
    document_hash: str = Field(default="", pattern=_HASH_PATTERN)

    @property
    def module_key(self) -> Literal["heating"]:
        """Return the shared activation scope key for this configuration."""

        return "heating"

    @property
    def module_instance_id(self) -> str:
        """Use the stable configuration identity as the activation instance."""

        return self.configuration_id

    @property
    def module_schema_version(self) -> Literal[3]:
        """Expose v3 through the existing generation/CAS activation contract."""

        return self.schema_version

    @property
    def scope_key(self) -> tuple[str, str, str]:
        return self.environment_id, self.module_key, self.module_instance_id

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "created_at")

    @field_validator("lineage", "import_provenance", "migration_provenance", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        _reject_operational_configuration_data(value, str(getattr(info, "field_name", "mapping")))
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))

    @model_validator(mode="after")
    def hashes_must_match_content(self) -> CanonicalConfigurationRevisionV3:
        expected_semantic = _sha256(self.semantic_data())
        if self.semantic_configuration_fingerprint and self.semantic_configuration_fingerprint != expected_semantic:
            raise ValueError("semantic configuration fingerprint does not match v3 revision")
        object.__setattr__(self, "semantic_configuration_fingerprint", expected_semantic)
        expected_document = _sha256(self.document_body())
        if self.document_hash and self.document_hash != expected_document:
            raise ValueError("document hash does not match v3 canonical revision")
        object.__setattr__(self, "document_hash", expected_document)
        return self

    def semantic_data(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "environment_id": self.environment_id,
            "provider": self.provider,
            "provider_instance_id": self.provider_instance_id,
            "heating": _semantic_value(self.heating),
            "diagnostics": _semantic_value(self.diagnostics),
            "notifications": _semantic_value(self.notifications),
        }

    def document_body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "configuration_id": self.configuration_id,
            "revision_id": self.revision_id,
            "revision": self.revision,
            "parent_revision_id": self.parent_revision_id,
            "environment_id": self.environment_id,
            "provider": self.provider,
            "provider_instance_id": self.provider_instance_id,
            "created_at": self.created_at,
            "actor": self.actor,
            "source": self.source,
            "change_kind": self.change_kind,
            "reason": self.reason,
            "core_version": self.core_version,
            "integration_version": self.integration_version,
            "heating": self.heating.model_dump(mode="json", by_alias=True),
            "diagnostics": self.diagnostics.model_dump(mode="json", by_alias=True),
            "notifications": self.notifications.model_dump(mode="json", by_alias=True),
            "lineage": normalize_json(self.lineage),
            "import_provenance": normalize_json(self.import_provenance),
            "migration_provenance": normalize_json(self.migration_provenance),
            "semantic_configuration_fingerprint": self.semantic_configuration_fingerprint,
        }

    def canonical_json(self) -> str:
        return canonical_json({**self.document_body(), "document_hash": self.document_hash})


@dataclass(frozen=True, slots=True)
class CanonicalFieldMetadataV3:
    owner: ConfigurationOwnerV3
    canonical_path: str
    value_type: str
    unit: str | None
    editability: ConfigurationEditabilityV3
    default_policy: ConfigurationDefaultPolicyV3


def canonical_field_registry_v3() -> tuple[CanonicalFieldMetadataV3, ...]:
    """Derive field metadata from schema fields; defaults are never copied here."""

    fields: list[CanonicalFieldMetadataV3] = []
    for scope_name in ("heating", "diagnostics", "notifications"):
        scope_field = CanonicalConfigurationRevisionV3.model_fields[scope_name]
        nested = _nested_configuration_model(scope_field.annotation)
        if nested is None:
            raise TypeError(f"canonical scope {scope_name} is not a configuration model")
        fields.extend(_field_metadata(nested[0], scope_name, collection=nested[1]))
    return tuple(fields)


def _field_metadata(
    model: type[BaseModel],
    prefix: str,
    *,
    collection: bool = False,
) -> list[CanonicalFieldMetadataV3]:
    result: list[CanonicalFieldMetadataV3] = []
    base = f"{prefix}[]" if collection else prefix
    for field_name, field in model.model_fields.items():
        serialized_name = field.alias or field_name
        path = f"{base}.{serialized_name}"
        nested = _nested_configuration_model(field.annotation)
        if nested is not None and nested[0] is not ProviderReference:
            result.extend(_field_metadata(nested[0], path, collection=nested[1]))
            continue
        extra = field.json_schema_extra
        if not isinstance(extra, Mapping):
            raise ValueError(f"configuration field {path} has no machine-readable ownership metadata")
        try:
            result.append(
                CanonicalFieldMetadataV3(
                    owner=ConfigurationOwnerV3(str(extra["configuration_owner"])),
                    canonical_path=path,
                    value_type=_value_type_name(field.annotation),
                    unit=_optional_metadata_string(extra.get("configuration_unit")),
                    editability=ConfigurationEditabilityV3(str(extra["configuration_editability"])),
                    default_policy=ConfigurationDefaultPolicyV3(str(extra["configuration_default_policy"])),
                )
            )
        except KeyError as error:
            raise ValueError(f"configuration field {path} has incomplete ownership metadata") from error
    return result


def _nested_configuration_model(annotation: object) -> tuple[type[BaseModel], bool] | None:
    origin = get_origin(annotation)
    if origin is tuple:
        arguments = get_args(annotation)
        if arguments and isinstance(arguments[0], type) and issubclass(arguments[0], BaseModel):
            return arguments[0], True
    if origin in {Union, UnionType}:
        for argument in get_args(annotation):
            if isinstance(argument, type) and issubclass(argument, BaseModel):
                return argument, False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    return None


def _value_type_name(annotation: object) -> str:
    nested = _nested_configuration_model(annotation)
    if nested is not None and nested[0] is ProviderReference:
        return "provider_reference_or_none" if get_origin(annotation) in {Union, UnionType} else "provider_reference"
    origin = get_origin(annotation)
    if origin is Literal:
        return "enum"
    if origin in {Union, UnionType}:
        return " | ".join(sorted(_value_type_name(argument) for argument in get_args(annotation)))
    if origin is tuple:
        return "list"
    return getattr(annotation, "__name__", str(annotation))


def _optional_metadata_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("configuration metadata unit must be null or a string")
    return value


def _stable_reference(value: ProviderReference | None, label: str) -> ProviderReference | None:
    if value is not None and value.identity_quality is not IdentityQuality.STABLE:
        raise ValueError(f"{label} must use stable provider identity")
    if value is not None:
        _reject_operational_configuration_data(value.recovery_evidence, f"{label}.recovery_evidence")
    return value


def _logical_id_must_be_separate(logical_id: str, reference: ProviderReference, label: str) -> None:
    provider_values = {reference.native_id, reference.current_locator}
    if logical_id in provider_values:
        raise ValueError(f"{label} must be a Controlel identity, not a provider native ID or locator")


def _reject_operational_configuration_data(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in _FORBIDDEN_OPERATIONAL_CONFIGURATION_KEYS:
                raise ValueError(f"operational data key {path}.{key_text} is forbidden in configuration")
            _reject_operational_configuration_data(item, f"{path}.{key_text}")
    elif isinstance(value, tuple | list):
        for index, item in enumerate(value):
            _reject_operational_configuration_data(item, f"{path}[{index}]")


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _semantic_value(value: object) -> object:
    if isinstance(value, ProviderReference):
        return value.semantic_data()
    if isinstance(value, BaseModel):
        return {
            field.alias or name: _semantic_value(getattr(value, name))
            for name, field in type(value).model_fields.items()
        }
    if isinstance(value, tuple | list):
        return [_semantic_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

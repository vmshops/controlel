"""Read-only operational sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from controlel.application.state.source_control_state import SourceControlReason

from . import ControlelEntryRuntime
from .entity import ControlelSnapshotEntity
from .operational import (
    ActiveLockoutType,
    CommandOutcome,
    ConfirmationState,
    DecisionCode,
    DecisionReason,
    EmergencyDisableOutcome,
    HeatDemandState,
    MeasurementStatus,
    OperationalSnapshot,
    OperationalSummaryCode,
    RuntimeStatus,
    SafetyState,
    SourceControlState,
)

type SensorValue = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class ControlelSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OperationalSnapshot], SensorValue]
    available_fn: Callable[[OperationalSnapshot], bool] = lambda snapshot: True
    always_available: bool = False
    refresh_elapsed: bool = False


def _enum_value(value: StrEnum | None) -> str | None:
    return value.value if value is not None else None


SENSORS: tuple[ControlelSensorDescription, ...] = (
    ControlelSensorDescription(
        key="operational_summary",
        translation_key="operational_summary",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in OperationalSummaryCode],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.operational_summary_code),
    ),
    ControlelSensorDescription(
        key="source_control_summary",
        translation_key="source_control_summary",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.source_control_summary,
    ),
    ControlelSensorDescription(
        key="current_temperature",
        translation_key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda snapshot: snapshot.current_temperature,
    ),
    ControlelSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        always_available=True,
        value_fn=lambda snapshot: snapshot.target_temperature,
    ),
    ControlelSensorDescription(
        key="heating_turn_on_differential",
        translation_key="heating_turn_on_differential",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        always_available=True,
        value_fn=lambda snapshot: snapshot.heating_turn_on_differential,
    ),
    ControlelSensorDescription(
        key="heating_turn_off_differential",
        translation_key="heating_turn_off_differential",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        always_available=True,
        value_fn=lambda snapshot: snapshot.heating_turn_off_differential,
    ),
    ControlelSensorDescription(
        key="heating_enable_threshold",
        translation_key="heating_enable_threshold",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        always_available=True,
        value_fn=lambda snapshot: snapshot.heating_enable_threshold,
    ),
    ControlelSensorDescription(
        key="heating_disable_threshold",
        translation_key="heating_disable_threshold",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        always_available=True,
        value_fn=lambda snapshot: snapshot.heating_disable_threshold,
    ),
    ControlelSensorDescription(
        key="measurement_age",
        translation_key="measurement_age",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.measurement_age_seconds,
    ),
    ControlelSensorDescription(
        key="measurement_maximum_age",
        translation_key="measurement_maximum_age",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.primary_measurement_max_age_seconds,
    ),
    ControlelSensorDescription(
        key="measurement_stale_deadline",
        translation_key="measurement_stale_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.measurement_stale_deadline,
        available_fn=lambda snapshot: snapshot.measurement_stale_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="measurement_stale_remaining",
        translation_key="measurement_stale_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.measurement_stale_remaining_seconds,
        available_fn=lambda snapshot: snapshot.measurement_stale_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="measurement_status",
        translation_key="measurement_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in MeasurementStatus],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.measurement_status),
    ),
    ControlelSensorDescription(
        key="latest_input_status",
        translation_key="latest_input_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in MeasurementStatus],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.latest_input_status),
    ),
    ControlelSensorDescription(
        key="active_demand_cause",
        translation_key="active_demand_cause",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in DecisionReason],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.active_demand_cause),
    ),
    ControlelSensorDescription(
        key="raw_heat_demand",
        translation_key="raw_heat_demand",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in HeatDemandState],
        value_fn=lambda snapshot: _enum_value(snapshot.raw_zone_heat_demand),
    ),
    ControlelSensorDescription(
        key="heat_demand",
        translation_key="heat_demand",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in HeatDemandState],
        value_fn=lambda snapshot: _enum_value(snapshot.zone_heat_demand),
    ),
    ControlelSensorDescription(
        key="hysteresis_demand",
        translation_key="hysteresis_demand",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in HeatDemandState],
        value_fn=lambda snapshot: _enum_value(snapshot.hysteresis_demand),
    ),
    ControlelSensorDescription(
        key="heat_demand_confirmation_duration",
        translation_key="heat_demand_confirmation_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.heat_demand_confirmation_duration_seconds,
    ),
    ControlelSensorDescription(
        key="heat_demand_confirmation_state",
        translation_key="heat_demand_confirmation_state",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in ConfirmationState],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.confirmation_state),
    ),
    ControlelSensorDescription(
        key="heat_demand_confirmation_deadline",
        translation_key="heat_demand_confirmation_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.confirmation_deadline,
        available_fn=lambda snapshot: snapshot.confirmation_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="heat_demand_confirmation_remaining",
        translation_key="heat_demand_confirmation_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.confirmation_remaining_seconds,
        available_fn=lambda snapshot: snapshot.confirmation_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="confirmed_zone_heat_demand",
        translation_key="confirmed_zone_heat_demand",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in HeatDemandState],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.confirmed_zone_heat_demand),
    ),
    ControlelSensorDescription(
        key="source_control_state",
        translation_key="source_control_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in SourceControlState],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.source_control_state),
    ),
    ControlelSensorDescription(
        key="active_lockout_type",
        translation_key="active_lockout_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in ActiveLockoutType],
        value_fn=lambda snapshot: _enum_value(snapshot.active_lockout_type),
        available_fn=lambda snapshot: snapshot.active_lockout_type is not None,
    ),
    ControlelSensorDescription(
        key="earliest_next_enable_time",
        translation_key="earliest_next_enable_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.earliest_next_enable_time,
        available_fn=lambda snapshot: snapshot.earliest_next_enable_time is not None,
    ),
    ControlelSensorDescription(
        key="earliest_next_disable_time",
        translation_key="earliest_next_disable_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.earliest_next_disable_time,
        available_fn=lambda snapshot: snapshot.earliest_next_disable_time is not None,
    ),
    ControlelSensorDescription(
        key="active_lockout_deadline",
        translation_key="active_lockout_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.active_lockout_deadline,
        available_fn=lambda snapshot: snapshot.active_lockout_deadline is not None,
    ),
    ControlelSensorDescription(
        key="active_lockout_remaining",
        translation_key="active_lockout_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.active_lockout_remaining_seconds,
        available_fn=lambda snapshot: snapshot.active_lockout_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="lockout_remaining",
        translation_key="lockout_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.lockout_remaining_seconds,
        available_fn=lambda snapshot: snapshot.lockout_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="deferred_command",
        translation_key="deferred_command",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["enable_heating", "disable_heating"],
        value_fn=lambda snapshot: snapshot.deferred_command,
        available_fn=lambda snapshot: snapshot.deferred_command is not None,
    ),
    ControlelSensorDescription(
        key="deferred_reason",
        translation_key="deferred_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in SourceControlReason],
        value_fn=lambda snapshot: snapshot.deferred_reason,
        available_fn=lambda snapshot: snapshot.deferred_reason is not None,
    ),
    ControlelSensorDescription(
        key="deferred_since",
        translation_key="deferred_since",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.deferred_since,
        available_fn=lambda snapshot: snapshot.deferred_since is not None,
    ),
    ControlelSensorDescription(
        key="deferred_deadline",
        translation_key="deferred_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.deferred_deadline,
        available_fn=lambda snapshot: snapshot.deferred_deadline is not None,
    ),
    ControlelSensorDescription(
        key="deferred_remaining",
        translation_key="deferred_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.deferred_remaining_seconds,
        available_fn=lambda snapshot: snapshot.deferred_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="last_successful_enable_dispatch",
        translation_key="last_successful_enable_dispatch",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_successful_enable_dispatch,
        available_fn=lambda snapshot: snapshot.last_successful_enable_dispatch is not None,
    ),
    ControlelSensorDescription(
        key="last_successful_disable_dispatch",
        translation_key="last_successful_disable_dispatch",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_successful_disable_dispatch,
        available_fn=lambda snapshot: snapshot.last_successful_disable_dispatch is not None,
    ),
    ControlelSensorDescription(
        key="minimum_heating_on_time",
        translation_key="minimum_heating_on_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.minimum_heating_on_time_seconds,
    ),
    ControlelSensorDescription(
        key="minimum_heating_off_time",
        translation_key="minimum_heating_off_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.minimum_heating_off_time_seconds,
    ),
    ControlelSensorDescription(
        key="minimum_on_deadline",
        translation_key="minimum_on_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.minimum_on_deadline,
        available_fn=lambda snapshot: (
            snapshot.active_lockout_type is ActiveLockoutType.MINIMUM_ON
            and snapshot.lockout_remaining_seconds is not None
        ),
    ),
    ControlelSensorDescription(
        key="minimum_off_deadline",
        translation_key="minimum_off_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.minimum_off_deadline,
        available_fn=lambda snapshot: (
            snapshot.active_lockout_type is ActiveLockoutType.MINIMUM_OFF
            and snapshot.lockout_remaining_seconds is not None
        ),
    ),
    ControlelSensorDescription(
        key="safety_state",
        translation_key="safety_state",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in SafetyState],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.safety_state),
    ),
    ControlelSensorDescription(
        key="grace_remaining",
        translation_key="grace_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.grace_remaining_seconds,
        available_fn=lambda snapshot: snapshot.grace_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="grace_deadline",
        translation_key="grace_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.grace_deadline,
        available_fn=lambda snapshot: snapshot.grace_deadline is not None,
    ),
    ControlelSensorDescription(
        key="sensor_failure_grace_period",
        translation_key="sensor_failure_grace_period",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.sensor_failure_grace_period_seconds,
    ),
    ControlelSensorDescription(
        key="timeout_action",
        translation_key="timeout_action",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["enable_heating", "disable_heating"],
        always_available=True,
        value_fn=lambda snapshot: snapshot.timeout_action,
    ),
    ControlelSensorDescription(
        key="last_decision",
        translation_key="last_decision",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in DecisionCode],
        value_fn=lambda snapshot: _enum_value(snapshot.last_decision),
    ),
    ControlelSensorDescription(
        key="last_decision_reason",
        translation_key="last_decision_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in DecisionReason],
        value_fn=lambda snapshot: _enum_value(snapshot.last_decision_reason),
    ),
    ControlelSensorDescription(
        key="last_requested_command",
        translation_key="last_requested_command",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["enable_heating", "disable_heating"],
        value_fn=lambda snapshot: snapshot.last_requested_command,
    ),
    ControlelSensorDescription(
        key="last_command_outcome",
        translation_key="last_command_outcome",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in CommandOutcome],
        value_fn=lambda snapshot: _enum_value(snapshot.last_command_outcome),
    ),
    ControlelSensorDescription(
        key="emergency_disable_outcome",
        translation_key="emergency_disable_outcome",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in EmergencyDisableOutcome],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.emergency_disable_outcome),
    ),
    ControlelSensorDescription(
        key="last_command_time",
        translation_key="last_command_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_command_timestamp,
    ),
    ControlelSensorDescription(
        key="last_meaningful_event",
        translation_key="last_meaningful_event",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_meaningful_event_at,
    ),
    ControlelSensorDescription(
        key="runtime_status",
        translation_key="runtime_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in RuntimeStatus],
        always_available=True,
        value_fn=lambda snapshot: _enum_value(snapshot.runtime_status),
    ),
    ControlelSensorDescription(
        key="diagnostic_profile",
        translation_key="diagnostic_profile",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["basic", "detailed", "debug"],
        always_available=True,
        value_fn=lambda snapshot: snapshot.diagnostic_profile,
    ),
    ControlelSensorDescription(
        key="debug_expiry_deadline",
        translation_key="debug_expiry_deadline",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.debug_expiry_deadline,
        available_fn=lambda snapshot: snapshot.debug_expiry_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="debug_profile_duration",
        translation_key="debug_profile_duration",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        always_available=True,
        value_fn=lambda snapshot: snapshot.debug_profile_duration_seconds,
    ),
    ControlelSensorDescription(
        key="debug_expiry_remaining",
        translation_key="debug_expiry_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        refresh_elapsed=True,
        value_fn=lambda snapshot: snapshot.debug_expiry_remaining_seconds,
        available_fn=lambda snapshot: snapshot.debug_expiry_remaining_seconds is not None,
    ),
    ControlelSensorDescription(
        key="decision_trace_capacity",
        translation_key="decision_trace_capacity",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.trace_capacity,
    ),
    ControlelSensorDescription(
        key="integration_version",
        translation_key="integration_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.integration_version,
    ),
    ControlelSensorDescription(
        key="core_version",
        translation_key="core_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.core_version,
    ),
    ControlelSensorDescription(
        key="duplicate_commands_suppressed",
        translation_key="duplicate_commands_suppressed",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda snapshot: snapshot.duplicate_commands_suppressed,
    ),
)


class ControlelSensor(ControlelSnapshotEntity, SensorEntity):
    entity_description: ControlelSensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        runtime_data: ControlelEntryRuntime,
        description: ControlelSensorDescription,
    ) -> None:
        if runtime_data.host is None:
            raise RuntimeError("Controlel host is unavailable")
        super().__init__(
            entry,
            runtime_data.host.snapshot_source,
            description.key,
            always_available=description.always_available,
            refresh_elapsed=description.refresh_elapsed,
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._snapshot)

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self._snapshot)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    del hass
    async_add_entities(ControlelSensor(entry, entry.runtime_data, description) for description in SENSORS)

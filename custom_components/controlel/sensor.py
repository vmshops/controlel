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

from . import ControlelEntryRuntime
from .entity import ControlelSnapshotEntity
from .operational import (
    CommandOutcome,
    DecisionCode,
    DecisionReason,
    HeatDemandState,
    MeasurementStatus,
    OperationalSnapshot,
    RuntimeStatus,
    SafetyState,
)

type SensorValue = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class ControlelSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OperationalSnapshot], SensorValue]
    always_available: bool = False


def _enum_value(value: StrEnum | None) -> str | None:
    return value.value if value is not None else None


SENSORS: tuple[ControlelSensorDescription, ...] = (
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
        key="measurement_age",
        translation_key="measurement_age",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=lambda snapshot: snapshot.measurement_age_seconds,
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
        key="heat_demand",
        translation_key="heat_demand",
        device_class=SensorDeviceClass.ENUM,
        options=[item.value for item in HeatDemandState],
        value_fn=lambda snapshot: _enum_value(snapshot.zone_heat_demand),
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
        value_fn=lambda snapshot: snapshot.grace_remaining_seconds,
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
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._snapshot)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    del hass
    async_add_entities(ControlelSensor(entry, entry.runtime_data, description) for description in SENSORS)

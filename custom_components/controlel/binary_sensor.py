"""Read-only operational binary sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ControlelEntryRuntime
from .entity import ControlelSnapshotEntity
from .operational import HeatDemandState, MeasurementStatus, OperationalSnapshot, RuntimeStatus


@dataclass(frozen=True, kw_only=True)
class ControlelBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[OperationalSnapshot], bool]
    always_available: bool = False


BINARY_SENSORS: tuple[ControlelBinarySensorDescription, ...] = (
    ControlelBinarySensorDescription(
        key="heat_required",
        translation_key="heat_required",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.zone_heat_demand is HeatDemandState.HEAT_REQUIRED,
    ),
    ControlelBinarySensorDescription(
        key="measurement_valid",
        translation_key="measurement_valid",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.measurement_status is MeasurementStatus.VALID,
    ),
    ControlelBinarySensorDescription(
        key="runtime_active",
        translation_key="runtime_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.runtime_status is RuntimeStatus.ACTIVE,
    ),
    ControlelBinarySensorDescription(
        key="recoverable_failure",
        translation_key="recoverable_failure",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.recoverable_failure_active,
    ),
    ControlelBinarySensorDescription(
        key="fatal_failure",
        translation_key="fatal_failure",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.fatal_failure_active,
    ),
    ControlelBinarySensorDescription(
        key="safety_bypassed_lockout",
        translation_key="safety_bypassed_lockout",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.safety_bypassed_lockout,
    ),
    ControlelBinarySensorDescription(
        key="emergency_disable_attempted",
        translation_key="emergency_disable_attempted",
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda snapshot: snapshot.emergency_disable_attempted,
    ),
)


class ControlelBinarySensor(ControlelSnapshotEntity, BinarySensorEntity):
    entity_description: ControlelBinarySensorDescription

    def __init__(
        self,
        entry: ConfigEntry,
        runtime_data: ControlelEntryRuntime,
        description: ControlelBinarySensorDescription,
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
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self._snapshot)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    del hass
    async_add_entities(ControlelBinarySensor(entry, entry.runtime_data, description) for description in BINARY_SENSORS)

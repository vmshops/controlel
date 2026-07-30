"""Shared read-only entities backed by the operational snapshot."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, INTEGRATION_VERSION
from .operational import OperationalSnapshot, OperationalSnapshotSource, RuntimeStatus


class ControlelSnapshotEntity(Entity):
    """Base class for entities that observe, but never mutate, runtime state."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        source: OperationalSnapshotSource,
        key: str,
        *,
        always_available: bool = False,
        refresh_elapsed: bool = False,
    ) -> None:
        self._source = source
        self._snapshot = source.current
        self._always_available = always_available
        self._refresh_elapsed = refresh_elapsed
        self._unsubscribe_snapshot: Callable[[], None] | None = None
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Controlel",
            model="Zone controller",
            name=f"Controlel — {self._snapshot.zone_name}",
            sw_version=INTEGRATION_VERSION,
        )

    @property
    def available(self) -> bool:
        """Keep lifecycle and diagnostic status visible during failures."""

        return self._always_available or self._snapshot.runtime_status not in {
            RuntimeStatus.STOPPED,
            RuntimeStatus.FATAL_ERROR,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsubscribe_snapshot = self._source.subscribe(
            self._handle_snapshot,
            elapsed_refresh=self._refresh_elapsed,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe_snapshot is not None:
            self._unsubscribe_snapshot()
            self._unsubscribe_snapshot = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_snapshot(self, snapshot: OperationalSnapshot) -> None:
        self._snapshot = snapshot
        if self.hass is not None:
            self.async_write_ha_state()

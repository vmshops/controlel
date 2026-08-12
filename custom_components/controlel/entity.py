"""Shared read-only entities backed by the operational snapshot."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock, get_ident

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
        self._snapshot_lock = Lock()
        self._event_loop_thread_id: int | None = None
        self._publication_pending = False
        self._removed = False
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
        with self._snapshot_lock:
            self._event_loop_thread_id = get_ident()
            self._removed = False
        self._unsubscribe_snapshot = self._source.subscribe(
            self._handle_snapshot,
            elapsed_refresh=self._refresh_elapsed,
        )

    async def async_will_remove_from_hass(self) -> None:
        with self._snapshot_lock:
            self._removed = True
            self._publication_pending = False
        if self._unsubscribe_snapshot is not None:
            self._unsubscribe_snapshot()
            self._unsubscribe_snapshot = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_snapshot(self, snapshot: OperationalSnapshot) -> None:
        with self._snapshot_lock:
            if self._removed:
                return
            self._snapshot = snapshot
            hass = self.hass
            if hass is None:
                return
            if get_ident() == self._event_loop_thread_id:
                publish_now = True
            elif self._publication_pending:
                return
            else:
                self._publication_pending = True
                publish_now = False
        if publish_now:
            self.async_write_ha_state()
        else:
            hass.loop.call_soon_threadsafe(self._publish_pending_snapshot)

    @callback
    def _publish_pending_snapshot(self) -> None:
        """Coalesce worker-thread notifications onto the Home Assistant loop."""

        with self._snapshot_lock:
            if self._removed:
                self._publication_pending = False
                return
            self._publication_pending = False
            hass = self.hass
        if hass is not None:
            self.async_write_ha_state()

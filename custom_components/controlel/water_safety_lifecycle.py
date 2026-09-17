"""Entry-scoped production ownership for Water Safety runtime hosts."""

from __future__ import annotations

from typing import Any, Protocol

from .const import DOMAIN

_LIFECYCLE_OWNERS_KEY = f"{DOMAIN}_water_safety_lifecycle_owners"


class WaterSafetyHost(Protocol):
    """The lifecycle surface required from a Water Safety host."""

    @property
    def stopped(self) -> bool: ...

    async def async_stop(self) -> None: ...


class WaterSafetyLifecycleOwner:
    """Own the active host and every host still requiring cleanup for one entry."""

    def __init__(self) -> None:
        self._active_host: WaterSafetyHost | None = None
        self._pending_cleanup_hosts: list[WaterSafetyHost] = []

    @property
    def active_host(self) -> WaterSafetyHost | None:
        """Return the active host, if one is still owned."""

        self._prune_stopped_hosts()
        return self._active_host

    @property
    def pending_cleanup_hosts(self) -> tuple[WaterSafetyHost, ...]:
        """Return hosts retained until their owned resources are fully released."""

        self._prune_stopped_hosts()
        return tuple(self._pending_cleanup_hosts)

    def register_constructed_host(self, host: WaterSafetyHost) -> None:
        """Own a newly constructed host before initialization can allocate resources."""

        self._prune_stopped_hosts()
        if self._active_host is not None or self._pending_cleanup_hosts:
            raise RuntimeError("Water Safety cannot start while a prior host remains lifecycle-owned")
        self._pending_cleanup_hosts.append(host)

    def mark_host_active(self, host: WaterSafetyHost) -> None:
        """Promote an initialized host from provisional cleanup ownership to active."""

        if host not in self._pending_cleanup_hosts:
            raise RuntimeError("Water Safety host was not registered before activation")
        self._pending_cleanup_hosts.remove(host)
        self._active_host = host

    async def async_prepare_for_start(self) -> None:
        """Retry prior cleanup and reject duplicate ownership if it remains unresolved."""

        await self.async_retry_pending_cleanup()
        self._prune_stopped_hosts()
        if self._active_host is not None or self._pending_cleanup_hosts:
            raise RuntimeError("Water Safety cannot start while a prior host remains lifecycle-owned")

    async def async_stop_host(self, host: WaterSafetyHost) -> bool:
        """Retire one host, retaining it until its cleanup is genuinely complete."""

        if self._active_host is host:
            self._active_host = None
        if host not in self._pending_cleanup_hosts and not host.stopped:
            self._pending_cleanup_hosts.append(host)
        try:
            await host.async_stop()
        finally:
            if host.stopped:
                self._release_host(host)
        return host.stopped

    async def async_retry_pending_cleanup(self) -> bool:
        """Retry every incompletely cleaned host without creating replacement resources."""

        self._prune_stopped_hosts()
        for host in tuple(self._pending_cleanup_hosts):
            await self.async_stop_host(host)
        self._prune_stopped_hosts()
        return not self._pending_cleanup_hosts

    async def async_stop_all(self) -> bool:
        """Stop the active host and retry all pending cleanup owned by the entry."""

        active = self.active_host
        if active is not None:
            await self.async_stop_host(active)
        return await self.async_retry_pending_cleanup()

    def _prune_stopped_hosts(self) -> None:
        active = self._active_host
        if active is not None and active.stopped:
            self._active_host = None
        self._pending_cleanup_hosts[:] = [host for host in self._pending_cleanup_hosts if not host.stopped]

    def _release_host(self, host: WaterSafetyHost) -> None:
        if self._active_host is host:
            self._active_host = None
        if host in self._pending_cleanup_hosts:
            self._pending_cleanup_hosts.remove(host)


def water_safety_lifecycle_owner(hass: Any, entry_id: str) -> WaterSafetyLifecycleOwner:
    """Return the process-reachable lifecycle owner for one config entry."""

    owners = hass.data.setdefault(_LIFECYCLE_OWNERS_KEY, {})
    owner = owners.get(entry_id)
    if owner is None:
        owner = WaterSafetyLifecycleOwner()
        owners[entry_id] = owner
    return owner

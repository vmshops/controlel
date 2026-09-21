"""Entry-scoped production ownership for Water Safety runtime hosts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from .const import DOMAIN

WATER_SAFETY_LIFECYCLE_OWNERS_KEY = f"{DOMAIN}_water_safety_lifecycle_owners"
_LOGGER = logging.getLogger(__name__)


class WaterSafetyHost(Protocol):
    """The lifecycle surface required from a Water Safety host."""

    @property
    def stopped(self) -> bool: ...

    @property
    def quiescent(self) -> bool: ...

    async def async_stop(self) -> None: ...

    def incomplete_owned_tasks(self) -> tuple[asyncio.Task[Any], ...]: ...


class WaterSafetyLifecycleOwner:
    """Own the active host and every host still requiring cleanup for one entry."""

    def __init__(self) -> None:
        self._active_host: WaterSafetyHost | None = None
        self._pending_cleanup_hosts: list[WaterSafetyHost] = []
        self._completion_task: asyncio.Task[Any] | None = None

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

    @property
    def completion_task(self) -> asyncio.Task[Any] | None:
        """Return the production-owned removed-entry cleanup continuation, if any."""

        return self._completion_task

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

    @property
    def pending_cleanup_is_quiescent(self) -> bool:
        """Return whether every retained host is logically unable to do new work."""

        self._prune_stopped_hosts()
        return all(host.quiescent for host in self._pending_cleanup_hosts)

    def ensure_removed_entry_completion(self, hass: Any, entry_id: str) -> asyncio.Task[Any]:
        """Own one continuation that finishes cleanup without a later reload."""

        task = self._completion_task
        if task is not None and not task.done():
            return task
        self._completion_task = hass.async_create_background_task(
            self._async_complete_removed_entry(hass, entry_id),
            name=f"Controlel Water Safety removed-entry cleanup ({entry_id})",
            eager_start=False,
        )
        return self._completion_task

    async def _async_complete_removed_entry(self, hass: Any, entry_id: str) -> None:
        released = False
        try:
            released = await self._async_run_until_released()
        except asyncio.CancelledError:
            _LOGGER.error(
                "Water Safety removed-entry cleanup was cancelled before host release (entry_id=%s)",
                entry_id,
            )
            raise
        except Exception:
            _LOGGER.exception(
                "Water Safety removed-entry cleanup failed (entry_id=%s)",
                entry_id,
            )
        finally:
            if released:
                drop_water_safety_lifecycle_owner(hass, entry_id)
            if self._completion_task is asyncio.current_task():
                self._completion_task = None

    async def _async_run_until_released(self) -> bool:
        while True:
            await self.async_retry_pending_cleanup()
            self._prune_stopped_hosts()
            if self._active_host is None and not self._pending_cleanup_hosts:
                return True
            waiters = [
                task for host in self._owned_hosts() for task in host.incomplete_owned_tasks() if not task.done()
            ]
            if waiters:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                continue
            await self.async_retry_pending_cleanup()
            self._prune_stopped_hosts()
            if self._active_host is None and not self._pending_cleanup_hosts:
                return True
            _LOGGER.error(
                "Water Safety removed-entry cleanup remains pending without owned waiters; "
                "the lifecycle owner is retained"
            )
            return False

    def _owned_hosts(self) -> tuple[WaterSafetyHost, ...]:
        hosts: list[WaterSafetyHost] = []
        if self._active_host is not None:
            hosts.append(self._active_host)
        hosts.extend(self._pending_cleanup_hosts)
        return tuple(hosts)

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

    owners = hass.data.setdefault(WATER_SAFETY_LIFECYCLE_OWNERS_KEY, {})
    owner = owners.get(entry_id)
    if owner is None:
        owner = WaterSafetyLifecycleOwner()
        owners[entry_id] = owner
    return owner


def drop_water_safety_lifecycle_owner(hass: Any, entry_id: str) -> None:
    """Remove one entry owner only after it no longer retains hosts."""

    owners = hass.data.get(WATER_SAFETY_LIFECYCLE_OWNERS_KEY)
    if not isinstance(owners, dict):
        return
    owner = owners.get(entry_id)
    if owner is None:
        return
    owner._prune_stopped_hosts()
    if owner.active_host is not None or owner.pending_cleanup_hosts:
        return
    owners.pop(entry_id, None)
    if not owners:
        hass.data.pop(WATER_SAFETY_LIFECYCLE_OWNERS_KEY, None)


async def async_complete_removed_entry_cleanup(hass: Any, entry_id: str) -> None:
    """Continue Water cleanup after permanent removal without requiring reload."""

    owners = hass.data.get(WATER_SAFETY_LIFECYCLE_OWNERS_KEY)
    if not isinstance(owners, dict) or entry_id not in owners:
        return
    owner = owners[entry_id]
    await owner.async_retry_pending_cleanup()
    owner._prune_stopped_hosts()
    if owner.active_host is None and not owner.pending_cleanup_hosts:
        drop_water_safety_lifecycle_owner(hass, entry_id)
        return
    owner.ensure_removed_entry_completion(hass, entry_id)

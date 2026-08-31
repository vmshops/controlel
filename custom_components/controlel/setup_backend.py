"""Lazy Home Assistant composition for the new Setup backend.

This module is intentionally not imported by the released runtime/config flow.
The public integration remains compatible with its pinned Core until Setup is
published as part of that package contract.
"""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Mapping
from datetime import datetime
from importlib import import_module
from typing import Any, cast

from controlel.application.setup import DiscoverySnapshot
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    MODULE_ACTIVE_REFERENCES_KEY,
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HeatingSetupHostService,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    LegacyConfigurationStatusDTO,
)

from .const import DOMAIN
from .core_capabilities import water_safety_core_available

_SETUP_CACHE_KEY = f"{DOMAIN}_setup_backend"
_LIFECYCLE_DATA_KEYS = frozenset({ACTIVE_REFERENCE_KEY, MODULE_ACTIVE_REFERENCES_KEY})
_HEATING_MODULE_KEY = "heating"
_WATER_SAFETY_MODULE_KEY = "water_safety"
_REPOSITORY_LOCK_KEY = "__repository_lock__"


def _legacy_status(entry: Any) -> LegacyConfigurationStatusDTO:
    data_keys = set(entry.data)
    options = dict(entry.options)
    legacy_present = bool(data_keys - _LIFECYCLE_DATA_KEYS or options)
    return LegacyConfigurationStatusDTO(
        present=legacy_present,
        conversion_available=False,
        silently_merged=False,
        reason_code="setup.legacy_configuration_present" if legacy_present else None,
    )


async def _repository_for_entry(
    hass: Any,
    entry: Any,
    *,
    module_key: str,
    lock: Lock,
) -> HomeAssistantSetupRepository:
    storage_module = import_module("homeassistant.helpers.storage")
    store_type = getattr(storage_module, "Store")
    store = cast(Any, store_type(hass, SETUP_STORAGE_VERSION, f"{DOMAIN}.setup.{entry.entry_id}"))

    def update_entry_data(data: Mapping[str, object]) -> None:
        hass.config_entries.async_update_entry(entry, data=dict(data))

    active_references = ConfigEntryActiveReferenceStore(
        entry,
        update_entry_data,
        module_key=module_key,
    )
    return HomeAssistantSetupRepository(store, active_references, lock=lock)


async def async_get_setup_service(hass: Any, entry: Any, *, module_key: str = _HEATING_MODULE_KEY) -> Any:
    """Return the shared setup service/repository for this config entry and module."""

    if module_key not in {_HEATING_MODULE_KEY, _WATER_SAFETY_MODULE_KEY}:
        raise ValueError(f"unsupported setup module_key: {module_key}")
    cache = hass.data.setdefault(_SETUP_CACHE_KEY, {})
    entry_cache = cache.setdefault(entry.entry_id, {})
    existing = entry_cache.get(module_key)
    if existing is not None:
        return existing

    lock = entry_cache.setdefault(_REPOSITORY_LOCK_KEY, Lock())
    repository = await _repository_for_entry(
        hass,
        entry,
        module_key=module_key,
        lock=lock,
    )
    legacy_status = _legacy_status(entry)

    if module_key == _WATER_SAFETY_MODULE_KEY:
        if not water_safety_core_available():
            raise ValueError("Water Safety setup requires candidate core with water_safety APIs")
        from controlel.infrastructure.home_assistant import WaterSafetySetupHostService
        from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services

        async def water_snapshot_loader(snapshot_id: str, captured_at: datetime) -> DiscoverySnapshot:
            return await async_snapshot_with_notify_services(
                hass,
                snapshot_id=snapshot_id,
                captured_at=captured_at,
            )

        service = WaterSafetySetupHostService(
            repository,
            water_snapshot_loader,
            legacy_configuration=legacy_status,
        )
    elif module_key == _HEATING_MODULE_KEY:

        async def heating_snapshot_loader(snapshot_id: str, captured_at: datetime) -> DiscoverySnapshot:
            return await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
                hass,
                snapshot_id=snapshot_id,
                captured_at=captured_at,
            )

        service = HeatingSetupHostService(
            repository,
            heating_snapshot_loader,
            legacy_configuration=legacy_status,
        )
    entry_cache[module_key] = service
    return service

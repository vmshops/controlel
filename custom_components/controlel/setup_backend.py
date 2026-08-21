"""Lazy Home Assistant composition for the new Setup backend.

This module is intentionally not imported by the released runtime/config flow.
The public integration remains compatible with its pinned Core until Setup is
published as part of that package contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from importlib import import_module
from typing import Any, cast

from controlel.application.setup import DiscoverySnapshot
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HeatingSetupHostService,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    LegacyConfigurationStatusDTO,
)

from .const import DOMAIN

_SETUP_CACHE_KEY = f"{DOMAIN}_setup_backend"
_LIFECYCLE_DATA_KEYS = frozenset({ACTIVE_REFERENCE_KEY})


async def async_get_setup_service(hass: Any, entry: Any) -> HeatingSetupHostService:
    """Return the one shared setup service/repository for this config entry."""

    cache = hass.data.setdefault(_SETUP_CACHE_KEY, {})
    existing = cache.get(entry.entry_id)
    if isinstance(existing, HeatingSetupHostService):
        return existing

    storage_module = import_module("homeassistant.helpers.storage")
    store_type = getattr(storage_module, "Store")
    store = cast(Any, store_type(hass, SETUP_STORAGE_VERSION, f"{DOMAIN}.setup.{entry.entry_id}"))

    def update_entry_data(data: Mapping[str, object]) -> None:
        hass.config_entries.async_update_entry(entry, data=dict(data))

    active_references = ConfigEntryActiveReferenceStore(entry, update_entry_data)
    repository = HomeAssistantSetupRepository(store, active_references)

    async def snapshot_loader(snapshot_id: str, captured_at: datetime) -> DiscoverySnapshot:
        return await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            hass,
            snapshot_id=snapshot_id,
            captured_at=captured_at,
        )

    data_keys = set(entry.data)
    options = dict(entry.options)
    legacy_present = bool(data_keys - _LIFECYCLE_DATA_KEYS or options)
    legacy_status = LegacyConfigurationStatusDTO(
        present=legacy_present,
        conversion_available=False,
        silently_merged=False,
        reason_code="setup.legacy_configuration_present" if legacy_present else None,
    )
    service = HeatingSetupHostService(
        repository,
        snapshot_loader,
        legacy_configuration=legacy_status,
    )
    cache[entry.entry_id] = service
    return service

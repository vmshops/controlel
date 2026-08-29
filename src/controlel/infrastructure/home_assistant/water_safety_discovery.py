"""Home Assistant discovery for Water Safety setup including notify service endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from controlel.application.setup import DiscoverySnapshot, IdentityQuality, ProviderReference
from controlel.infrastructure.home_assistant.setup_discovery import (
    HA_ENDPOINT_KIND,
    HOME_ASSISTANT_PROVIDER,
    HomeAssistantDiscoveryAdapter,
)


async def async_snapshot_with_notify_services(
    hass: object,
    *,
    snapshot_id: str,
    captured_at: datetime,
) -> DiscoverySnapshot:
    """Load HA registry discovery plus notify services as stable endpoint references."""

    base = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )
    notify_refs = _notify_service_references(hass, base.provider_instance_id)
    if not notify_refs:
        return base
    return DiscoverySnapshot(
        snapshot_id=base.snapshot_id,
        provider=base.provider,
        provider_instance_id=base.provider_instance_id,
        adapter_contract_version=base.adapter_contract_version,
        captured_at=base.captured_at,
        objects=(*base.objects, *notify_refs),
    )


def _notify_service_references(hass: object, provider_instance_id: str) -> tuple[ProviderReference, ...]:
    services_obj = getattr(hass, "services", None)
    if services_obj is None:
        return ()
    async_services = getattr(services_obj, "async_services", None)
    if async_services is None:
        return ()
    all_services = async_services()
    if not isinstance(all_services, Mapping):
        return ()
    notify_services = all_services.get("notify", {})
    if not isinstance(notify_services, Mapping):
        return ()
    references: list[ProviderReference] = []
    for service_name in sorted(notify_services):
        if not isinstance(service_name, str) or not service_name:
            continue
        locator = f"notify.{service_name}"
        references.append(
            ProviderReference(
                provider=HOME_ASSISTANT_PROVIDER,
                provider_instance_id=provider_instance_id,
                object_kind=HA_ENDPOINT_KIND,
                native_id=locator,
                identity_quality=IdentityQuality.STABLE,
                current_locator=locator,
                recovery_evidence={"domain": "notify"},
            )
        )
    return tuple(references)

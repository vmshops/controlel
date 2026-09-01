"""Canonical Water Safety activation and runtime startup for Home Assistant."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, cast

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WaterSafetySetupPayload,
)
from controlel.application.setup import (
    ActivationCoordinator,
    CandidateRuntimeReady,
    EffectiveRuntimeConfiguration,
    LoadedRuntimeConfiguration,
    derive_real_runtime_configuration,
)
from controlel.application.setup.json_data import canonical_json
from controlel.domain.water_safety import WaterSafetySnapshot
from controlel.infrastructure.home_assistant import (
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HomeAssistantSetupRepository,
)

from .const import DOMAIN
from .event_loop_bridge import HomeAssistantEventLoopBridge
from .scheduler import HomeAssistantScheduler
from .water_safety_host import HomeAssistantWaterSafetyHost, build_water_safety_host
from .water_safety_persistence import (
    create_water_safety_evidence_store,
    create_water_safety_state_store,
)

LOGGER = logging.getLogger(__name__)
_HOST_ADAPTER = "home_assistant_water_safety"


class WaterSafetyActivationService:
    """Activate canonical Water Safety revisions and start the HA runtime host."""

    async def activate_canonical_revision(
        self,
        hass: Any,
        entry: Any,
        canonical_revision_id: str,
        *,
        attempt_id: str | None = None,
    ) -> HomeAssistantWaterSafetyHost:
        repository = await self._async_get_repository(hass, entry)
        coordinator = ActivationCoordinator(repository, repository)
        prepared = coordinator.prepare(
            canonical_revision_id,
            attempt_id=attempt_id or f"water-safety-{uuid.uuid4().hex}",
            prepared_at=datetime.now(UTC),
        )
        coordinator.begin_applying(prepared.attempt_id, applying_at=datetime.now(UTC))
        revision = await repository.get_canonical_revision(canonical_revision_id)
        if revision.module_key != WATER_SAFETY_MODULE_KEY:
            raise ValueError("canonical revision is not a Water Safety configuration")
        resolved = {binding.role: binding.reference for binding in revision.bindings}
        effective = derive_real_runtime_configuration(revision, resolved)
        host = await self._async_build_and_start_host(hass, entry, effective)
        coordinator.record_candidate_runtime_ready(
            prepared.attempt_id,
            candidate_ready=CandidateRuntimeReady(
                runtime=LoadedRuntimeConfiguration(
                    canonical_revision_id=revision.revision_id,
                    semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
                    environment_id=revision.environment_id,
                    module_key=revision.module_key,
                    module_instance_id=revision.module_instance_id,
                ),
                ready_at=datetime.now(UTC),
                host_adapter=_HOST_ADAPTER,
                readiness_evidence={"current_sensor_evaluated": True},
            ),
        )
        coordinator.commit(prepared.attempt_id, committed_at=datetime.now(UTC))
        return host

    async def async_start_from_active_reference(
        self,
        hass: Any,
        entry: Any,
        *,
        bridge: HomeAssistantEventLoopBridge,
    ) -> HomeAssistantWaterSafetyHost | None:
        active_reference_store = ConfigEntryActiveReferenceStore(
            entry,
            lambda data: hass.config_entries.async_update_entry(entry, data=dict(data)),
        )
        active = active_reference_store.get()
        if active is None or active.module_key != WATER_SAFETY_MODULE_KEY:
            return None
        repository = await self._async_get_repository(hass, entry)
        revision = await repository.get_canonical_revision(active.canonical_revision_id)
        resolved = {binding.role: binding.reference for binding in revision.bindings}
        effective = derive_real_runtime_configuration(revision, resolved)
        return await self._async_build_and_start_host(hass, entry, effective, bridge=bridge)

    async def _async_build_and_start_host(
        self,
        hass: Any,
        entry: Any,
        effective: EffectiveRuntimeConfiguration,
        *,
        bridge: HomeAssistantEventLoopBridge | None = None,
    ) -> HomeAssistantWaterSafetyHost:
        bridge = bridge or HomeAssistantEventLoopBridge(hass.loop)
        host_holder: list[HomeAssistantWaterSafetyHost] = []

        def submit_runtime_callback(callback) -> None:
            if host_holder:
                host_holder[0].submit_scheduled_callback(callback)

        scheduler = HomeAssistantScheduler(
            hass=hass,
            bridge=bridge,
            submit_runtime_callback=submit_runtime_callback,
        )
        state_store = create_water_safety_state_store(hass, entry.entry_id, bridge)
        evidence_store = create_water_safety_evidence_store(hass, entry.entry_id, bridge)
        restored_snapshot = await state_store.async_load_snapshot()
        restored_snapshot = _restored_snapshot_for_effective(restored_snapshot, effective)
        host = build_water_safety_host(
            hass,
            effective,
            bridge=bridge,
            scheduler=scheduler,
            state_store=state_store,
            evidence_store=evidence_store,
            logger=LOGGER,
            restored_snapshot=restored_snapshot,
        )
        host_holder.append(host)
        await host.async_initialize()
        return host

    async def _async_get_repository(self, hass: Any, entry: Any) -> HomeAssistantSetupRepository:
        storage_module = import_module("homeassistant.helpers.storage")
        store_type = getattr(storage_module, "Store")
        store = cast(Any, store_type(hass, SETUP_STORAGE_VERSION, f"{DOMAIN}.setup.{entry.entry_id}"))
        active_references = ConfigEntryActiveReferenceStore(
            entry,
            lambda data: hass.config_entries.async_update_entry(entry, data=dict(data)),
        )
        cache = hass.data.setdefault(f"{DOMAIN}_setup_backend", {})
        existing = cache.get(entry.entry_id)
        if existing is not None and hasattr(existing, "_repository"):
            return existing._repository
        return HomeAssistantSetupRepository(store, active_references)


def _restored_snapshot_for_effective(
    restored_snapshot: WaterSafetySnapshot | None,
    effective: EffectiveRuntimeConfiguration,
) -> WaterSafetySnapshot | None:
    """Carry an active incident across an explicit same-sensor authority update."""

    if restored_snapshot is None:
        return None
    if (
        restored_snapshot.canonical_revision_id == effective.canonical_revision_id
        and restored_snapshot.semantic_configuration_fingerprint == effective.semantic_configuration_fingerprint
    ):
        return restored_snapshot

    config = WaterSafetySetupPayload.model_validate_json(canonical_json(effective.module_payload))
    same_incident_authority = (
        restored_snapshot.canonical_revision_id != effective.canonical_revision_id
        and restored_snapshot.environment_id == effective.environment_id
        and restored_snapshot.module_instance_id == effective.module_instance_id
        and restored_snapshot.sensor_id == config.sensor_id
        and restored_snapshot.active_incident is not None
    )
    if not same_incident_authority:
        LOGGER.info(
            "Water Safety restart snapshot was not reused for changed canonical authority "
            "(previous_revision=%s, candidate_revision=%s)",
            restored_snapshot.canonical_revision_id,
            effective.canonical_revision_id,
        )
        return None

    LOGGER.info(
        "Water Safety active incident will continue across same-sensor canonical activation "
        "(incident_id=%s, previous_revision=%s, candidate_revision=%s)",
        restored_snapshot.active_incident.incident_id,
        restored_snapshot.canonical_revision_id,
        effective.canonical_revision_id,
    )
    return replace(
        restored_snapshot,
        canonical_revision_id=effective.canonical_revision_id,
        semantic_configuration_fingerprint=effective.semantic_configuration_fingerprint,
    )

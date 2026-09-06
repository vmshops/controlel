"""Canonical Water Safety activation and runtime startup for Home Assistant."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WaterSafetySetupPayload,
)
from controlel.application.setup import (
    ActivationState,
    ActiveReference,
    CandidateRuntimeReady,
    EffectiveRuntimeConfiguration,
    LoadedRuntimeConfiguration,
    ReferenceResolutionStatus,
    derive_real_runtime_configuration,
)
from controlel.application.setup.json_data import canonical_json
from controlel.domain.water_safety import WaterSafetySnapshot
from controlel.infrastructure.home_assistant import HomeAssistantReferenceResolver, active_reference_for_module
from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services

from .event_loop_bridge import HomeAssistantEventLoopBridge
from .scheduler import HomeAssistantScheduler
from .setup_backend import async_get_setup_backend
from .water_safety_host import HomeAssistantWaterSafetyHost, build_water_safety_host
from .water_safety_persistence import (
    create_water_safety_evidence_store,
    create_water_safety_state_store,
)

LOGGER = logging.getLogger(__name__)
_HOST_ADAPTER = "home_assistant_water_safety"
_STAGED_RUNTIME_KEY = "controlel_staged_water_runtime"


def water_reference_for_runtime(hass: Any, entry: Any) -> ActiveReference | None:
    """Select a process-local handover candidate, otherwise persisted authority."""
    staged = hass.data.get(_STAGED_RUNTIME_KEY, {}).get(entry.entry_id)
    return staged if staged is not None else active_reference_for_module(entry.data, WATER_SAFETY_MODULE_KEY)


def _running_water_stamp(entry: Any) -> LoadedRuntimeConfiguration | None:
    data = getattr(entry, "runtime_data", None)
    host = getattr(data, "water_safety_host", None)
    stamp = getattr(data, "loaded_water_safety_configuration", None)
    if host is None or stamp is None or host._stopped or host._stopping:
        return None
    snapshot = host.runtime.snapshot
    if (
        snapshot.canonical_revision_id != stamp.canonical_revision_id
        or snapshot.semantic_configuration_fingerprint != stamp.semantic_configuration_fingerprint
        or snapshot.environment_id != stamp.environment_id
        or snapshot.module_instance_id != stamp.module_instance_id
        or stamp.module_key != WATER_SAFETY_MODULE_KEY
    ):
        return None
    return stamp


def _authority_is_running(entry: Any) -> bool:
    active = active_reference_for_module(entry.data, WATER_SAFETY_MODULE_KEY)
    if active is None:
        return getattr(getattr(entry, "runtime_data", None), "water_safety_host", None) is None
    stamp = _running_water_stamp(entry)
    return stamp is not None and (
        stamp.canonical_revision_id == active.canonical_revision_id
        and stamp.semantic_configuration_fingerprint == active.semantic_configuration_fingerprint
        and (stamp.environment_id, stamp.module_key, stamp.module_instance_id) == active.scope_key
    )


async def _async_restore_authority(hass: Any, entry: Any) -> bool:
    """Reload retained authority if needed, and quiesce a mismatched Water host."""
    if _authority_is_running(entry):
        return True
    try:
        if not await hass.config_entries.async_reload(entry.entry_id):
            raise RuntimeError("Water Safety rollback reload did not complete")
    except Exception:
        LOGGER.exception("Failed to reload authoritative Water Safety configuration")
    if _authority_is_running(entry):
        return True
    data = getattr(entry, "runtime_data", None)
    host = getattr(data, "water_safety_host", None)
    if host is not None:
        await host.async_stop()
        data.water_safety_host = None
        data.loaded_water_safety_configuration = None
    return False


async def _async_recover_attempts(hass: Any, entry: Any, backend: Any) -> None:
    """Called with the activation lock held; persisted attempts alone are not live."""
    active = active_reference_for_module(entry.data, WATER_SAFETY_MODULE_KEY)
    attempts = tuple(
        attempt
        for attempt in await backend.repository.list_non_terminal_attempts()
        if attempt.module_key == WATER_SAFETY_MODULE_KEY and (active is None or attempt.scope_key == active.scope_key)
    )
    if not attempts:
        return
    restored = await _async_restore_authority(hass, entry)
    stamp = _running_water_stamp(entry)
    for attempt in attempts:
        rollback_succeeded = restored and (
            (active is None and attempt.previous_revision_id is None)
            or (stamp is not None and stamp.canonical_revision_id == attempt.previous_revision_id)
        )
        await backend.activation.recover_interrupted(
            attempt.attempt_id,
            recovered_at=datetime.now(UTC),
            rollback_succeeded=rollback_succeeded,
            rollback_runtime_stamp=stamp if rollback_succeeded else None,
        )


async def async_recover_water_activation(hass: Any, entry: Any) -> None:
    """Recover only after setup; a locked in-process transaction owns its handover."""
    backend = await async_get_setup_backend(hass, entry)
    if backend.activation_lock.locked():
        return
    async with backend.activation_lock:
        await _async_recover_attempts(hass, entry, backend)


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
        backend = await async_get_setup_backend(hass, entry)
        repository = backend.repository
        revision = await repository.get_canonical_revision(canonical_revision_id)
        if revision.module_key != WATER_SAFETY_MODULE_KEY:
            raise ValueError("canonical revision is not a Water Safety configuration")
        activation_attempt_id = attempt_id or f"water-safety-{uuid.uuid4().hex}"
        async with backend.activation_lock:
            await _async_recover_attempts(hass, entry, backend)
            prepared = await backend.activation.prepare(
                canonical_revision_id,
                attempt_id=activation_attempt_id,
                prepared_at=datetime.now(UTC),
            )
            previous_data = getattr(entry, "runtime_data", None)
            if previous_data is not None:
                previous_data.reloading = True
            staged = hass.data.setdefault(_STAGED_RUNTIME_KEY, {})
            try:
                await backend.activation.begin_applying(prepared.attempt_id, applying_at=datetime.now(UTC))
                # The existing coordinator commits only after the actual HA handover.
                # This candidate is never published as active before reload readiness.
                candidate = ActiveReference(
                    environment_id=revision.environment_id,
                    module_key=revision.module_key,
                    module_instance_id=revision.module_instance_id,
                    canonical_revision_id=revision.revision_id,
                    semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
                    generation=prepared.expected_active_generation + 1,
                    committing_operation_id=prepared.attempt_id,
                )
                staged[entry.entry_id] = candidate
                if not await hass.config_entries.async_reload(entry.entry_id):
                    raise RuntimeError("Water Safety candidate reload did not complete")
                stamp = _running_water_stamp(entry)
                if stamp is None or (
                    stamp.canonical_revision_id != candidate.canonical_revision_id
                    or stamp.semantic_configuration_fingerprint != candidate.semantic_configuration_fingerprint
                    or (stamp.environment_id, stamp.module_key, stamp.module_instance_id) != candidate.scope_key
                ):
                    raise RuntimeError("Water Safety candidate reload did not install the prepared runtime")
                entry.runtime_data.reloading = True
                await backend.activation.record_candidate_runtime_ready(
                    prepared.attempt_id,
                    candidate_ready=CandidateRuntimeReady(
                        runtime=stamp,
                        ready_at=datetime.now(UTC),
                        host_adapter=_HOST_ADAPTER,
                        readiness_evidence={"current_sensor_evaluated": True, "serialized_entry_reload": True},
                    ),
                )
                try:
                    await backend.activation.commit(prepared.attempt_id, committed_at=datetime.now(UTC))
                except Exception:
                    # A durable CAS plus verified installed runtime may outlive a
                    # failed terminal-evidence write. Reconcile that exact commit.
                    active = active_reference_for_module(entry.data, WATER_SAFETY_MODULE_KEY)
                    if active != candidate or not _authority_is_running(entry):
                        raise
                    await backend.activation.recover_interrupted(
                        prepared.attempt_id,
                        recovered_at=datetime.now(UTC),
                        rollback_succeeded=False,
                    )
                return entry.runtime_data.water_safety_host
            except Exception:
                staged.pop(entry.entry_id, None)
                restored = await _async_restore_authority(hass, entry)
                try:
                    attempt = await repository.get_activation_attempt(prepared.attempt_id)
                    active = active_reference_for_module(entry.data, WATER_SAFETY_MODULE_KEY)
                    durable_commit = active is not None and active.committing_operation_id == prepared.attempt_id
                    stamp = _running_water_stamp(entry) if restored else None
                    if attempt.state is ActivationState.APPLYING and not durable_commit:
                        await backend.activation.record_failed_application(
                            prepared.attempt_id,
                            completed_at=datetime.now(UTC),
                            failure_code="water_safety_runtime_handover_failed",
                            rollback_succeeded=restored,
                            rollback_runtime_stamp=stamp,
                        )
                    else:
                        await backend.activation.recover_interrupted(
                            prepared.attempt_id,
                            recovered_at=datetime.now(UTC),
                            rollback_succeeded=restored,
                            rollback_runtime_stamp=stamp,
                        )
                except Exception:
                    LOGGER.exception("Failed to persist Water Safety activation rollback evidence")
                raise
            finally:
                staged.pop(entry.entry_id, None)
                if previous_data is not None:
                    previous_data.reloading = False
                current_data = getattr(entry, "runtime_data", None)
                if current_data is not None:
                    current_data.reloading = False

    async def async_start_from_active_reference(
        self,
        hass: Any,
        entry: Any,
        *,
        bridge: HomeAssistantEventLoopBridge,
    ) -> HomeAssistantWaterSafetyHost | None:
        active = water_reference_for_runtime(hass, entry)
        if active is None:
            return None
        repository = (await async_get_setup_backend(hass, entry)).repository
        revision = await repository.get_canonical_revision(active.canonical_revision_id)
        captured_at = datetime.now(UTC)
        snapshot = await async_snapshot_with_notify_services(
            hass,
            snapshot_id=f"water-runtime:{revision.revision_id}:{captured_at.isoformat()}",
            captured_at=captured_at,
        )
        resolver = HomeAssistantReferenceResolver()
        resolved = {}
        for binding in revision.bindings:
            resolution = resolver.resolve(binding.reference, snapshot)
            if resolution.status is not ReferenceResolutionStatus.RESOLVED or resolution.resolved_reference is None:
                raise ValueError(
                    f"canonical Water Safety binding {binding.role} is not resolvable: {resolution.status.value}"
                )
            resolved[binding.role] = resolution.resolved_reference
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
        try:
            await host.async_initialize()
        except Exception:
            await host.async_stop()
            raise
        return host


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

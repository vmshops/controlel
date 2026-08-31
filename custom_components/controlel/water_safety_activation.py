"""Canonical Water Safety activation and runtime startup for Home Assistant."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from controlel.application.configuration.water_safety_setup_adapter import WATER_SAFETY_MODULE_KEY
from controlel.application.setup import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    CandidateRuntimeReady,
    EffectiveRuntimeConfiguration,
    LoadedRuntimeConfiguration,
    derive_real_runtime_configuration,
)
from controlel.infrastructure.home_assistant import (
    ConfigEntryActiveReferenceStore,
    HomeAssistantSetupRepository,
)

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
        await _recover_interrupted_water_activations(repository)
        revision = await repository.get_canonical_revision(canonical_revision_id)
        if revision.module_key != WATER_SAFETY_MODULE_KEY:
            raise ValueError("canonical revision is not a Water Safety configuration")
        scope = (revision.environment_id, revision.module_key, revision.module_instance_id)
        active = await repository.get_active_reference(scope)
        prepared = ActivationAttempt(
            attempt_id=attempt_id or f"water-safety-{uuid.uuid4().hex}",
            environment_id=revision.environment_id,
            module_key=revision.module_key,
            module_instance_id=revision.module_instance_id,
            state=ActivationState.PREPARED,
            candidate_revision_id=revision.revision_id,
            candidate_semantic_fingerprint=revision.semantic_configuration_fingerprint,
            previous_revision_id=None if active is None else active.canonical_revision_id,
            previous_semantic_fingerprint=(None if active is None else active.semantic_configuration_fingerprint),
            last_known_good_revision_id=None if active is None else active.canonical_revision_id,
            last_known_good_semantic_fingerprint=(
                None if active is None else active.semantic_configuration_fingerprint
            ),
            expected_active_generation=0 if active is None else active.generation,
            prepared_at=datetime.now(UTC),
        )
        await repository.reserve_activation_attempt(prepared)
        applying = _updated_activation(
            prepared,
            state=ActivationState.APPLYING,
            applying_at=datetime.now(UTC),
        )
        await repository.transition_activation_attempt(
            applying,
            expected_state=ActivationState.PREPARED,
            expected_version=prepared.version,
        )
        resolved = {binding.role: binding.reference for binding in revision.bindings}
        effective = derive_real_runtime_configuration(revision, resolved)
        try:
            host = await self._async_build_and_start_host(hass, entry, effective)
        except BaseException as error:
            await _record_failed_activation(
                repository,
                applying,
                failure_code=f"candidate_start_failed:{type(error).__name__}",
            )
            raise
        try:
            candidate_ready = CandidateRuntimeReady(
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
            )
            ready = _updated_activation(applying, candidate_runtime_ready=candidate_ready)
            await repository.transition_activation_attempt(
                ready,
                expected_state=ActivationState.APPLYING,
                expected_version=applying.version,
            )
        except BaseException as error:
            await _stop_candidate(host)
            await _record_failed_activation(
                repository,
                applying,
                failure_code=f"candidate_readiness_failed:{type(error).__name__}",
            )
            raise
        replacement = ActiveReference(
            environment_id=revision.environment_id,
            module_key=revision.module_key,
            module_instance_id=revision.module_instance_id,
            canonical_revision_id=revision.revision_id,
            semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
            generation=prepared.expected_active_generation + 1,
            committing_operation_id=prepared.attempt_id,
        )
        try:
            await repository.compare_and_swap_active_reference(
                scope=scope,
                expected_revision_id=prepared.previous_revision_id,
                expected_generation=prepared.expected_active_generation,
                replacement=replacement,
            )
        except BaseException as error:
            await _stop_candidate(host)
            await _record_failed_activation(
                repository,
                ready,
                failure_code=f"active_reference_commit_failed:{type(error).__name__}",
            )
            raise
        committed = _updated_activation(
            ready,
            state=ActivationState.COMMITTED,
            completed_at=datetime.now(UTC),
        )
        try:
            await repository.transition_activation_attempt(
                committed,
                expected_state=ActivationState.APPLYING,
                expected_version=ready.version,
            )
        except Exception:
            # The scoped active pointer is already durable and is runtime
            # authority. Recovery closes this evidence record before the next
            # activation; do not report failure and leave an active host orphaned.
            LOGGER.exception("Water Safety authority committed but activation evidence remains incomplete")
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
            module_key=WATER_SAFETY_MODULE_KEY,
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
        except BaseException:
            await host.async_stop()
            raise
        return host

    async def _async_get_repository(self, hass: Any, entry: Any) -> HomeAssistantSetupRepository:
        from .setup_backend import async_get_setup_service

        service = await async_get_setup_service(
            hass,
            entry,
            module_key=WATER_SAFETY_MODULE_KEY,
        )
        return service._repository


def _updated_activation(attempt: ActivationAttempt, **changes: object) -> ActivationAttempt:
    values = attempt.model_dump(mode="python")
    values["version"] = attempt.version + 1
    values.update(changes)
    return ActivationAttempt.model_validate(values)


async def _stop_candidate(host: HomeAssistantWaterSafetyHost) -> None:
    try:
        await host.async_stop()
    except BaseException:
        LOGGER.exception("Failed to stop an uncommitted Water Safety candidate runtime")


async def _record_failed_activation(
    repository: HomeAssistantSetupRepository,
    attempt: ActivationAttempt,
    *,
    failure_code: str,
) -> None:
    """Best-effort terminal evidence; never mask the activation failure."""

    try:
        current = await repository.get_activation_attempt(attempt.attempt_id)
        if current.state in {
            ActivationState.COMMITTED,
            ActivationState.ROLLED_BACK,
            ActivationState.FAILED,
        }:
            return
        failed = _updated_activation(
            current,
            state=ActivationState.FAILED,
            applying_at=current.applying_at or current.prepared_at,
            completed_at=datetime.now(UTC),
            failure_evidence={
                "failure_code": failure_code,
                "active_authority_unchanged": True,
            },
        )
        await repository.transition_activation_attempt(
            failed,
            expected_state=current.state,
            expected_version=current.version,
        )
    except BaseException:
        LOGGER.exception("Failed to persist terminal Water Safety activation evidence")


async def _recover_interrupted_water_activations(
    repository: HomeAssistantSetupRepository,
) -> None:
    """Close interrupted attempts from durable scoped authority evidence."""

    for attempt in await repository.list_non_terminal_attempts():
        if attempt.module_key != WATER_SAFETY_MODULE_KEY:
            continue
        active = await repository.get_active_reference(attempt.scope_key)
        committed_durably = (
            active is not None
            and active.canonical_revision_id == attempt.candidate_revision_id
            and active.semantic_configuration_fingerprint == attempt.candidate_semantic_fingerprint
            and active.committing_operation_id == attempt.attempt_id
            and attempt.candidate_runtime_ready is not None
        )
        recovered = _updated_activation(
            attempt,
            state=(ActivationState.COMMITTED if committed_durably else ActivationState.FAILED),
            applying_at=attempt.applying_at or attempt.prepared_at,
            completed_at=datetime.now(UTC),
            interruption_recovered_at=datetime.now(UTC),
            failure_evidence=(
                attempt.failure_evidence
                if committed_durably
                else {
                    "failure_code": "activation_interrupted",
                    "active_authority_unchanged": True,
                }
            ),
        )
        await repository.transition_activation_attempt(
            recovered,
            expected_state=attempt.state,
            expected_version=attempt.version,
        )

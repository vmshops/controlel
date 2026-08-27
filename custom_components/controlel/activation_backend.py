"""Safe serialized activation and restart recovery for canonical Heating."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from controlel.application.setup import (
    ActivationAttempt,
    ActiveReference,
    CandidateRuntimeReady,
    LoadedRuntimeConfiguration,
    SetupConflictError,
)
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    is_explicit_legacy_v3_conversion,
)

from .canonical_runtime import (
    RuntimeConfigurationSelection,
    async_compile_canonical_runtime,
    clear_staged_candidate_runtime,
    stage_candidate_runtime,
)
from .setup_backend import SetupBackend, async_get_setup_backend

LOGGER = logging.getLogger(__name__)


async def async_activate_canonical_revision(
    hass: Any,
    entry: Any,
    *,
    revision_id: str,
    semantic_configuration_fingerprint: str,
    expected_active_revision_id: str | None,
    expected_active_generation: int,
    attempt_id: str,
) -> ActivationAttempt:
    """Activate one inactive revision using prepare, handover, CAS, and rollback."""

    backend = await async_get_setup_backend(hass, entry)
    async with backend.activation_lock:
        candidate_revision = await backend.repository.get_canonical_revision(revision_id)
        if candidate_revision.semantic_configuration_fingerprint != semantic_configuration_fingerprint:
            raise SetupConflictError("activation candidate fingerprint does not match the persisted revision")
        current = _entry_active_reference(entry)
        if (
            current is None
            and (entry.data or entry.options)
            and not is_explicit_legacy_v3_conversion(candidate_revision)
        ):
            raise SetupConflictError(
                "legacy config-entry settings must be explicitly converted before canonical activation"
            )
        _require_expected_reference(
            current,
            expected_revision_id=expected_active_revision_id,
            expected_generation=expected_active_generation,
        )
        if current is not None and current.scope_key != (
            candidate_revision.environment_id,
            candidate_revision.module_key,
            candidate_revision.module_instance_id,
        ):
            raise SetupConflictError("activation candidate belongs to another configuration scope")
        if current is not None and current.canonical_revision_id == revision_id:
            raise SetupConflictError("activation candidate is already active")

        selection = await async_compile_canonical_runtime(
            hass,
            candidate_revision,
            activation_attempt_id=attempt_id,
        )
        prepared_at = datetime.now(UTC)
        attempt = await backend.activation.prepare(
            revision_id,
            attempt_id=attempt_id,
            prepared_at=prepared_at,
        )
        if (
            attempt.previous_revision_id != expected_active_revision_id
            or attempt.expected_active_generation != expected_active_generation
        ):
            await backend.activation.recover_interrupted(
                attempt_id,
                recovered_at=datetime.now(UTC),
                rollback_succeeded=attempt.previous_revision_id is None,
            )
            raise SetupConflictError("active reference changed while activation was prepared")
        await backend.activation.begin_applying(attempt_id, applying_at=datetime.now(UTC))

        stage_candidate_runtime(hass, entry.entry_id, selection)
        try:
            await _require_reload_success(hass, entry.entry_id)
            runtime_data = entry.runtime_data
            if runtime_data.loaded_configuration != selection.loaded_configuration:
                raise RuntimeError("candidate runtime did not load the prepared canonical revision")
            host = runtime_data.host
            if host is None or not host.frontend_api_setup_ready:
                raise RuntimeError("candidate runtime did not reach the Home Assistant readiness boundary")
            ready = CandidateRuntimeReady(
                runtime=_required_stamp(selection),
                ready_at=datetime.now(UTC),
                host_adapter="home_assistant",
                readiness_evidence={
                    "host_initialized": True,
                    "platforms_loaded": True,
                    "serialized_entry_reload": True,
                },
            )
            await backend.activation.record_candidate_runtime_ready(
                attempt_id,
                candidate_ready=ready,
            )
            try:
                committed = await backend.activation.commit(attempt_id, committed_at=datetime.now(UTC))
            except Exception:
                active_after_commit_error = _entry_active_reference(entry)
                if _is_durable_commit(active_after_commit_error, attempt_id, selection):
                    committed = await backend.activation.recover_interrupted(
                        attempt_id,
                        recovered_at=datetime.now(UTC),
                        rollback_succeeded=False,
                    )
                else:
                    raise
            return committed
        except Exception as error:
            active_after_error = _entry_active_reference(entry)
            if _is_durable_commit(active_after_error, attempt_id, selection):
                raise
            clear_staged_candidate_runtime(hass, entry.entry_id)
            rollback_succeeded, rollback_stamp = await _async_restore_authoritative_runtime(hass, entry, attempt)
            try:
                await backend.activation.record_failed_application(
                    attempt_id,
                    completed_at=datetime.now(UTC),
                    failure_code="canonical_runtime_handover_failed",
                    rollback_succeeded=rollback_succeeded,
                    rollback_runtime_stamp=rollback_stamp,
                )
            except Exception:
                LOGGER.exception("Failed to persist canonical activation rollback evidence")
            raise SetupConflictError("canonical runtime activation failed; prior authority was retained") from error
        finally:
            clear_staged_candidate_runtime(hass, entry.entry_id)


async def async_recover_interrupted_activation(
    hass: Any,
    entry: Any,
    backend: SetupBackend,
    selection: RuntimeConfigurationSelection,
) -> tuple[ActivationAttempt, ...]:
    """Finalize non-terminal attempts only after authoritative runtime readiness."""

    if selection.is_activation_candidate or backend.activation_lock.locked():
        return ()
    attempts = await backend.repository.list_non_terminal_attempts()
    recovered = []
    active = _entry_active_reference(entry)
    for attempt in attempts:
        if not _attempt_belongs_to_loaded_authority(attempt, active, selection.loaded_configuration):
            continue
        durable_commit = (
            active is not None
            and active.committing_operation_id == attempt.attempt_id
            and active.canonical_revision_id == attempt.candidate_revision_id
        )
        rollback_stamp = None
        rollback_succeeded = False
        if not durable_commit:
            if attempt.previous_revision_id is None and selection.loaded_configuration is None and active is None:
                rollback_succeeded = True
            elif (
                selection.loaded_configuration is not None
                and selection.loaded_configuration.canonical_revision_id == attempt.previous_revision_id
            ):
                rollback_succeeded = True
                rollback_stamp = selection.loaded_configuration
        recovered.append(
            await backend.activation.recover_interrupted(
                attempt.attempt_id,
                recovered_at=datetime.now(UTC),
                rollback_succeeded=rollback_succeeded,
                rollback_runtime_stamp=rollback_stamp,
            )
        )
    return tuple(recovered)


async def _async_restore_authoritative_runtime(
    hass: Any,
    entry: Any,
    attempt: ActivationAttempt,
) -> tuple[bool, LoadedRuntimeConfiguration | None]:
    try:
        await _require_reload_success(hass, entry.entry_id)
    except Exception:
        LOGGER.exception("Failed to restore authoritative runtime after canonical activation failure")
        await _async_quiesce_non_authoritative_runtime(entry)
        return False, None
    runtime_data = entry.runtime_data
    stamp = runtime_data.loaded_configuration
    active = _entry_active_reference(entry)
    if attempt.previous_revision_id is None:
        restored = active is None and stamp is None
        if not restored:
            await _async_quiesce_non_authoritative_runtime(entry)
        return restored, None
    if (
        active is not None
        and active.canonical_revision_id == attempt.previous_revision_id
        and active.semantic_configuration_fingerprint == attempt.previous_semantic_fingerprint
        and stamp is not None
        and stamp.canonical_revision_id == attempt.previous_revision_id
        and stamp.semantic_configuration_fingerprint == attempt.previous_semantic_fingerprint
        and (stamp.environment_id, stamp.module_key, stamp.module_instance_id) == attempt.scope_key
    ):
        return True, stamp
    await _async_quiesce_non_authoritative_runtime(entry)
    return False, None


async def _async_quiesce_non_authoritative_runtime(entry: Any) -> None:
    """Stop a loaded runtime when its stamp does not match durable authority."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return
    stamp = getattr(runtime_data, "loaded_configuration", None)
    active = _entry_active_reference(entry)
    authority_matches = (active is None and stamp is None) or (
        active is not None
        and stamp is not None
        and active.canonical_revision_id == stamp.canonical_revision_id
        and active.semantic_configuration_fingerprint == stamp.semantic_configuration_fingerprint
        and active.scope_key == (stamp.environment_id, stamp.module_key, stamp.module_instance_id)
    )
    if authority_matches:
        return
    host = getattr(runtime_data, "host", None)
    if host is None:
        return
    try:
        await host.async_stop()
    except Exception:
        LOGGER.exception("Failed to quiesce non-authoritative canonical runtime")
    finally:
        runtime_data.host = None


async def _require_reload_success(hass: Any, entry_id: str) -> None:
    if not await hass.config_entries.async_reload(entry_id):
        raise RuntimeError("Home Assistant config-entry reload did not complete")


def _entry_active_reference(entry: Any) -> ActiveReference | None:
    raw = entry.data.get(ACTIVE_REFERENCE_KEY)
    if raw is None:
        return None
    return ActiveReference.model_validate(raw)


def _require_expected_reference(
    current: ActiveReference | None,
    *,
    expected_revision_id: str | None,
    expected_generation: int,
) -> None:
    current_revision_id = None if current is None else current.canonical_revision_id
    current_generation = 0 if current is None else current.generation
    if current_revision_id != expected_revision_id or current_generation != expected_generation:
        raise SetupConflictError("active reference does not match activation precondition")


def _required_stamp(selection: RuntimeConfigurationSelection) -> LoadedRuntimeConfiguration:
    if selection.loaded_configuration is None:
        raise RuntimeError("canonical activation candidate has no loaded-runtime stamp")
    return selection.loaded_configuration


def _is_durable_commit(
    active: ActiveReference | None,
    attempt_id: str,
    selection: RuntimeConfigurationSelection,
) -> bool:
    stamp = selection.loaded_configuration
    return (
        active is not None
        and stamp is not None
        and active.committing_operation_id == attempt_id
        and active.canonical_revision_id == stamp.canonical_revision_id
        and active.semantic_configuration_fingerprint == stamp.semantic_configuration_fingerprint
    )


def _attempt_belongs_to_loaded_authority(
    attempt: ActivationAttempt,
    active: ActiveReference | None,
    stamp: LoadedRuntimeConfiguration | None,
) -> bool:
    if active is not None:
        return bool(attempt.scope_key == active.scope_key)
    if stamp is not None:
        return bool(attempt.scope_key == (stamp.environment_id, stamp.module_key, stamp.module_instance_id))
    return attempt.previous_revision_id is None

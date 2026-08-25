"""Explicit, evidence-driven activation transaction coordination."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from controlel.application.setup.model import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    CandidateRuntimeReady,
    CanonicalConfigurationRevision,
    LoadedRuntimeConfiguration,
)
from controlel.application.setup.repository import (
    ActivationAttemptRepository,
    ConfigurationAuthorityRepository,
    SetupConflictError,
)


class ActivationCoordinator:
    """Coordinate authority changes around a host-owned runtime replacement."""

    def __init__(
        self,
        configurations: ConfigurationAuthorityRepository,
        attempts: ActivationAttemptRepository,
        *,
        supported_module_schema_versions: Mapping[str, int],
    ) -> None:
        self._configurations = configurations
        self._attempts = attempts
        self._supported_module_schema_versions = dict(supported_module_schema_versions)

    def prepare(self, revision_id: str, *, attempt_id: str, prepared_at: datetime) -> ActivationAttempt:
        candidate = self._configurations.get_canonical_revision(revision_id)
        self._require_supported_module_contract(candidate)
        scope = (candidate.environment_id, candidate.module_key, candidate.module_instance_id)
        active = self._configurations.get_active_reference(scope)
        attempt = ActivationAttempt(
            attempt_id=attempt_id,
            environment_id=candidate.environment_id,
            module_key=candidate.module_key,
            module_instance_id=candidate.module_instance_id,
            state=ActivationState.PREPARED,
            candidate_revision_id=candidate.revision_id,
            candidate_semantic_fingerprint=candidate.semantic_configuration_fingerprint,
            previous_revision_id=None if active is None else active.canonical_revision_id,
            previous_semantic_fingerprint=(None if active is None else active.semantic_configuration_fingerprint),
            last_known_good_revision_id=None if active is None else active.canonical_revision_id,
            last_known_good_semantic_fingerprint=(
                None if active is None else active.semantic_configuration_fingerprint
            ),
            expected_active_generation=0 if active is None else active.generation,
            prepared_at=prepared_at,
        )
        self._attempts.reserve_activation_attempt(attempt)
        return attempt

    def begin_applying(self, attempt_id: str, *, applying_at: datetime) -> ActivationAttempt:
        attempt = self._attempts.get_activation_attempt(attempt_id)
        if attempt.state is not ActivationState.PREPARED:
            raise SetupConflictError("only PREPARED activation may begin applying")
        applying = _updated(attempt, state=ActivationState.APPLYING, applying_at=applying_at)
        self._persist_transition(attempt, applying)
        return applying

    def record_candidate_runtime_ready(
        self,
        attempt_id: str,
        *,
        candidate_ready: CandidateRuntimeReady,
    ) -> ActivationAttempt:
        attempt = self._attempts.get_activation_attempt(attempt_id)
        if attempt.state is not ActivationState.APPLYING:
            raise SetupConflictError("candidate runtime readiness requires APPLYING activation")
        _validate_candidate_ready(attempt, candidate_ready)
        ready = _updated(attempt, candidate_runtime_ready=candidate_ready)
        self._persist_transition(attempt, ready)
        return ready

    def commit(
        self,
        attempt_id: str,
        *,
        committed_at: datetime,
    ) -> ActivationAttempt:
        attempt = self._attempts.get_activation_attempt(attempt_id)
        if attempt.state is not ActivationState.APPLYING:
            raise SetupConflictError("only APPLYING activation may commit")
        if attempt.candidate_runtime_ready is None:
            raise SetupConflictError("candidate runtime readiness must be persisted before commit")
        candidate = self._configurations.get_canonical_revision(attempt.candidate_revision_id)
        self._require_supported_module_contract(candidate)
        _validate_candidate_ready(attempt, attempt.candidate_runtime_ready)
        active_reference = ActiveReference(
            environment_id=attempt.environment_id,
            module_key=attempt.module_key,
            module_instance_id=attempt.module_instance_id,
            canonical_revision_id=attempt.candidate_revision_id,
            semantic_configuration_fingerprint=attempt.candidate_semantic_fingerprint,
            generation=attempt.expected_active_generation + 1,
            committing_operation_id=attempt.attempt_id,
        )
        self._configurations.compare_and_swap_active_reference(
            scope=attempt.scope_key,
            expected_revision_id=attempt.previous_revision_id,
            expected_generation=attempt.expected_active_generation,
            replacement=active_reference,
        )
        committed = _updated(
            attempt,
            state=ActivationState.COMMITTED,
            completed_at=committed_at,
        )
        self._persist_transition(attempt, committed)
        return committed

    def record_failed_application(
        self,
        attempt_id: str,
        *,
        completed_at: datetime,
        failure_code: str,
        rollback_succeeded: bool,
        rollback_runtime_stamp: LoadedRuntimeConfiguration | None = None,
    ) -> ActivationAttempt:
        attempt = self._attempts.get_activation_attempt(attempt_id)
        if attempt.state is not ActivationState.APPLYING:
            raise SetupConflictError("only APPLYING activation may record application failure")
        if rollback_succeeded and attempt.previous_revision_id is not None:
            if rollback_runtime_stamp is None:
                raise SetupConflictError("successful rollback requires the previous runtime stamp")
            _validate_rollback_runtime(attempt, rollback_runtime_stamp)
        terminal = _updated(
            attempt,
            state=ActivationState.ROLLED_BACK if rollback_succeeded else ActivationState.FAILED,
            completed_at=completed_at,
            rollback_runtime_stamp=rollback_runtime_stamp,
            failure_evidence={"failure_code": failure_code, "rollback_succeeded": rollback_succeeded},
        )
        self._persist_transition(attempt, terminal)
        return terminal

    def recover_interrupted(
        self,
        attempt_id: str,
        *,
        recovered_at: datetime,
        rollback_succeeded: bool,
        rollback_runtime_stamp: LoadedRuntimeConfiguration | None = None,
    ) -> ActivationAttempt:
        attempt = self._attempts.get_activation_attempt(attempt_id)
        if attempt.state not in {ActivationState.PREPARED, ActivationState.APPLYING}:
            return attempt
        active = self._configurations.get_active_reference(attempt.scope_key)
        commit_was_durable = (
            active is not None
            and active.canonical_revision_id == attempt.candidate_revision_id
            and active.semantic_configuration_fingerprint == attempt.candidate_semantic_fingerprint
            and active.committing_operation_id == attempt.attempt_id
        )
        if commit_was_durable:
            if attempt.candidate_runtime_ready is None:
                raise SetupConflictError("committed activation marker has no persisted candidate runtime evidence")
            _validate_candidate_ready(attempt, attempt.candidate_runtime_ready)
            recovered = _updated(
                attempt,
                state=ActivationState.COMMITTED,
                applying_at=attempt.applying_at or attempt.prepared_at,
                completed_at=recovered_at,
                interruption_recovered_at=recovered_at,
            )
        else:
            if rollback_succeeded and attempt.previous_revision_id is not None:
                if rollback_runtime_stamp is None:
                    raise SetupConflictError("interruption rollback requires the previous runtime stamp")
                _validate_rollback_runtime(attempt, rollback_runtime_stamp)
            recovered = _updated(
                attempt,
                state=ActivationState.ROLLED_BACK if rollback_succeeded else ActivationState.FAILED,
                applying_at=attempt.applying_at or attempt.prepared_at,
                completed_at=recovered_at,
                interruption_recovered_at=recovered_at,
                rollback_runtime_stamp=rollback_runtime_stamp,
                failure_evidence={
                    "failure_code": "activation_interrupted",
                    "commit_marker_found": False,
                    "rollback_succeeded": rollback_succeeded,
                },
            )
        self._persist_transition(attempt, recovered)
        return recovered

    def _persist_transition(self, previous: ActivationAttempt, replacement: ActivationAttempt) -> None:
        self._attempts.transition_activation_attempt(
            replacement,
            expected_state=previous.state,
            expected_version=previous.version,
        )

    def _require_supported_module_contract(self, candidate: CanonicalConfigurationRevision) -> None:
        required_version = self._supported_module_schema_versions.get(candidate.module_key)
        if required_version is None:
            raise SetupConflictError(f"activation module contract is not registered: {candidate.module_key}")
        if candidate.module_schema_version != required_version:
            raise SetupConflictError(
                "activation candidate uses an unsupported module schema version: "
                f"{candidate.module_key} requires {required_version}, got {candidate.module_schema_version}"
            )


def _updated(attempt: ActivationAttempt, **changes: object) -> ActivationAttempt:
    values = attempt.model_dump(mode="python")
    values["version"] = attempt.version + 1
    values.update(changes)
    return ActivationAttempt.model_validate(values)


def _validate_candidate_ready(
    attempt: ActivationAttempt,
    candidate_ready: CandidateRuntimeReady,
) -> None:
    runtime = candidate_ready.runtime
    if not _runtime_matches(
        attempt,
        runtime,
        revision_id=attempt.candidate_revision_id,
        fingerprint=attempt.candidate_semantic_fingerprint,
    ):
        raise SetupConflictError("candidate runtime readiness does not match activation candidate and scope")


def _validate_rollback_runtime(
    attempt: ActivationAttempt,
    runtime: LoadedRuntimeConfiguration,
) -> None:
    revision_id = attempt.last_known_good_revision_id or attempt.previous_revision_id
    fingerprint = attempt.last_known_good_semantic_fingerprint or attempt.previous_semantic_fingerprint
    if revision_id is None or fingerprint is None:
        raise SetupConflictError("rollback runtime has no previous or last-known-good authority")
    if not _runtime_matches(attempt, runtime, revision_id=revision_id, fingerprint=fingerprint):
        raise SetupConflictError("rollback runtime stamp does not match last-known-good revision and scope")


def _runtime_matches(
    attempt: ActivationAttempt,
    runtime: LoadedRuntimeConfiguration,
    *,
    revision_id: str,
    fingerprint: str,
) -> bool:
    return (
        runtime.canonical_revision_id == revision_id
        and runtime.semantic_configuration_fingerprint == fingerprint
        and runtime.environment_id == attempt.environment_id
        and runtime.module_key == attempt.module_key
        and runtime.module_instance_id == attempt.module_instance_id
    )

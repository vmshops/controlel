from datetime import timedelta

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION,
    HeatingSetupAdapter,
)
from controlel.application.setup import (
    ActivationCoordinator,
    ActivationState,
    ActiveReference,
    CandidateRuntimeReady,
    CanonicalConfigurationRevision,
    InMemorySetupRepository,
    LoadedRuntimeConfiguration,
    RuntimeConfigurationOrigin,
    SetupConflictError,
)
from controlel.application.setup.json_data import normalize_json

from .conftest import NOW, complete_draft


def _loaded(canonical):
    return LoadedRuntimeConfiguration(
        canonical_revision_id=canonical.revision_id,
        semantic_configuration_fingerprint=canonical.semantic_configuration_fingerprint,
        environment_id=canonical.environment_id,
        module_key=canonical.module_key,
        module_instance_id=canonical.module_instance_id,
    )


def _ready(canonical, *, ready_at):
    return CandidateRuntimeReady(
        runtime=_loaded(canonical),
        ready_at=ready_at,
        host_adapter="test_host",
        readiness_evidence={"startup_recovery_completed": True},
    )


def _coordinator(repository: InMemorySetupRepository) -> ActivationCoordinator:
    return ActivationCoordinator(
        repository,
        repository,
        supported_module_schema_versions={"heating": HEATING_SETUP_SCHEMA_VERSION},
    )


def _second_canonical(canonical):
    draft = complete_draft(draft_id="draft-2")
    changed_settings = dict(draft.settings)
    changed_settings["target_temperature_celsius"] = 22.0
    changed = draft.next_revision(updated_at=NOW + timedelta(minutes=1), settings=changed_settings)
    adapter = HeatingSetupAdapter()
    report = adapter.validate(changed, report_id="report-2", evaluated_at=NOW + timedelta(minutes=1))
    return adapter.canonicalize(
        changed,
        report,
        configuration_id=canonical.configuration_id,
        revision_id="canonical-2",
        revision=2,
        parent_revision_id=canonical.revision_id,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW + timedelta(minutes=1),
        actor="user:owner",
        source="setup_api",
        change_kind="UPDATE",
        reason="comfort_change",
        core_version="0.11.0",
        integration_version="0.11.0",
    )


def _activate_first(repository, canonical):
    repository.add_canonical_revision(canonical)
    coordinator = _coordinator(repository)
    attempt = coordinator.prepare(canonical.revision_id, attempt_id="activate-1", prepared_at=NOW)
    assert repository.get_active_reference(attempt.scope_key) is None
    applying = coordinator.begin_applying(attempt.attempt_id, applying_at=NOW + timedelta(seconds=1))
    assert repository.get_active_reference(applying.scope_key) is None
    coordinator.record_candidate_runtime_ready(
        attempt.attempt_id,
        candidate_ready=_ready(canonical, ready_at=NOW + timedelta(seconds=2)),
    )
    committed = coordinator.commit(
        attempt.attempt_id,
        committed_at=NOW + timedelta(seconds=3),
    )
    return coordinator, committed


def test_activation_success_selects_candidate_only_at_commit(canonical_revision) -> None:
    repository = InMemorySetupRepository()

    _, committed = _activate_first(repository, canonical_revision)

    active = repository.get_active_reference(committed.scope_key)
    assert committed.state is ActivationState.COMMITTED
    assert active is not None
    assert active.canonical_revision_id == canonical_revision.revision_id
    assert active.semantic_configuration_fingerprint == canonical_revision.semantic_configuration_fingerprint
    assert active.committing_operation_id == committed.attempt_id


def test_policy_less_heating_schema_v1_cannot_enter_activation(canonical_revision) -> None:
    document = normalize_json(canonical_revision.canonical_data())
    assert isinstance(document, dict)
    document.pop("document_hash")
    document.pop("semantic_configuration_fingerprint")
    document["module_schema_version"] = POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION
    payload = document["module_payload"]
    assert isinstance(payload, dict)
    payload.pop("diagnostic_policy")
    payload.pop("notification_policy")
    policy_less = CanonicalConfigurationRevision.model_validate(document)
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(policy_less)
    coordinator = _coordinator(repository)

    with pytest.raises(SetupConflictError, match="heating requires 2, got 1"):
        coordinator.prepare(policy_less.revision_id, attempt_id="activate-v1", prepared_at=NOW)

    assert repository.list_non_terminal_attempts() == ()
    scope = (policy_less.environment_id, policy_less.module_key, policy_less.module_instance_id)
    assert repository.get_active_reference(scope) is None


def test_failed_activation_preserves_previous_authoritative_revision(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    coordinator, first = _activate_first(repository, canonical_revision)
    candidate = _second_canonical(canonical_revision)
    repository.add_canonical_revision(candidate)
    prepared = coordinator.prepare(
        candidate.revision_id,
        attempt_id="activate-2",
        prepared_at=NOW + timedelta(minutes=2),
    )
    coordinator.begin_applying(prepared.attempt_id, applying_at=NOW + timedelta(minutes=2, seconds=1))

    terminal = coordinator.record_failed_application(
        prepared.attempt_id,
        completed_at=NOW + timedelta(minutes=2, seconds=2),
        failure_code="candidate_start_failed",
        rollback_succeeded=True,
        rollback_runtime_stamp=first.candidate_runtime_ready.runtime,
    )

    active = repository.get_active_reference(terminal.scope_key)
    assert terminal.state is ActivationState.ROLLED_BACK
    assert active is not None
    assert active.canonical_revision_id == canonical_revision.revision_id


def test_rollback_failure_never_marks_candidate_active(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    coordinator, _ = _activate_first(repository, canonical_revision)
    candidate = _second_canonical(canonical_revision)
    repository.add_canonical_revision(candidate)
    prepared = coordinator.prepare(
        candidate.revision_id,
        attempt_id="activate-2",
        prepared_at=NOW + timedelta(minutes=2),
    )
    coordinator.begin_applying(prepared.attempt_id, applying_at=NOW + timedelta(minutes=2, seconds=1))

    failed = coordinator.record_failed_application(
        prepared.attempt_id,
        completed_at=NOW + timedelta(minutes=2, seconds=2),
        failure_code="candidate_and_rollback_failed",
        rollback_succeeded=False,
    )

    active = repository.get_active_reference(failed.scope_key)
    assert failed.state is ActivationState.FAILED
    assert active is not None
    assert active.canonical_revision_id == canonical_revision.revision_id
    assert active.canonical_revision_id != candidate.revision_id


def test_interrupted_apply_without_commit_marker_rolls_back(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    coordinator, first = _activate_first(repository, canonical_revision)
    candidate = _second_canonical(canonical_revision)
    repository.add_canonical_revision(candidate)
    prepared = coordinator.prepare(
        candidate.revision_id,
        attempt_id="activate-2",
        prepared_at=NOW + timedelta(minutes=2),
    )
    coordinator.begin_applying(prepared.attempt_id, applying_at=NOW + timedelta(minutes=2, seconds=1))

    recovered = coordinator.recover_interrupted(
        prepared.attempt_id,
        recovered_at=NOW + timedelta(minutes=3),
        rollback_succeeded=True,
        rollback_runtime_stamp=first.candidate_runtime_ready.runtime,
    )

    assert recovered.state is ActivationState.ROLLED_BACK
    assert recovered.interruption_recovered_at == NOW + timedelta(minutes=3)
    assert repository.get_active_reference(recovered.scope_key).canonical_revision_id == canonical_revision.revision_id


def test_interrupted_apply_with_matching_commit_marker_finishes_commit(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    coordinator, _ = _activate_first(repository, canonical_revision)
    candidate = _second_canonical(canonical_revision)
    repository.add_canonical_revision(candidate)
    prepared = coordinator.prepare(
        candidate.revision_id,
        attempt_id="activate-2",
        prepared_at=NOW + timedelta(minutes=2),
    )
    applying = coordinator.begin_applying(prepared.attempt_id, applying_at=NOW + timedelta(minutes=2, seconds=1))
    coordinator.record_candidate_runtime_ready(
        applying.attempt_id,
        candidate_ready=_ready(candidate, ready_at=NOW + timedelta(minutes=2, seconds=2)),
    )
    repository.compare_and_swap_active_reference(
        scope=applying.scope_key,
        expected_revision_id=canonical_revision.revision_id,
        expected_generation=1,
        replacement=ActiveReference(
            environment_id=applying.environment_id,
            module_key=applying.module_key,
            module_instance_id=applying.module_instance_id,
            canonical_revision_id=candidate.revision_id,
            semantic_configuration_fingerprint=candidate.semantic_configuration_fingerprint,
            generation=2,
            committing_operation_id=applying.attempt_id,
        ),
    )

    recovered = coordinator.recover_interrupted(
        applying.attempt_id,
        recovered_at=NOW + timedelta(minutes=3),
        rollback_succeeded=False,
    )

    assert recovered.state is ActivationState.COMMITTED
    assert repository.get_active_reference(recovered.scope_key).canonical_revision_id == candidate.revision_id


def test_loaded_runtime_stamp_requires_revision_and_fingerprint() -> None:
    stamp = LoadedRuntimeConfiguration(
        canonical_revision_id="revision",
        semantic_configuration_fingerprint="0" * 64,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
    )
    assert stamp.canonical_revision_id == "revision"


def test_commit_requires_separately_persisted_host_readiness(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical_revision)
    coordinator = _coordinator(repository)
    attempt = coordinator.prepare(canonical_revision.revision_id, attempt_id="activate", prepared_at=NOW)
    coordinator.begin_applying(attempt.attempt_id, applying_at=NOW + timedelta(seconds=1))

    with pytest.raises(SetupConflictError, match="readiness must be persisted"):
        coordinator.commit(attempt.attempt_id, committed_at=NOW + timedelta(seconds=2))

    assert repository.get_active_reference(attempt.scope_key) is None


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("canonical_revision_id", "other-revision"),
        ("semantic_configuration_fingerprint", "f" * 64),
        ("environment_id", "other-home"),
        ("module_key", "lighting"),
        ("module_instance_id", "other-instance"),
    ],
)
def test_candidate_readiness_requires_complete_matching_runtime_stamp(
    canonical_revision,
    changed_field,
    changed_value,
) -> None:
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical_revision)
    coordinator = _coordinator(repository)
    attempt = coordinator.prepare(canonical_revision.revision_id, attempt_id="activate", prepared_at=NOW)
    coordinator.begin_applying(attempt.attempt_id, applying_at=NOW + timedelta(seconds=1))
    runtime_values = _loaded(canonical_revision).model_dump(mode="python")
    runtime_values[changed_field] = changed_value
    ready = CandidateRuntimeReady(
        runtime=LoadedRuntimeConfiguration.model_validate(runtime_values),
        ready_at=NOW + timedelta(seconds=2),
        host_adapter="test_host",
        readiness_evidence={"startup_recovery_completed": True},
    )

    with pytest.raises(SetupConflictError, match="does not match activation candidate and scope"):
        coordinator.record_candidate_runtime_ready(attempt.attempt_id, candidate_ready=ready)


def test_rollback_requires_matching_revision_fingerprint_and_scope(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    coordinator, _ = _activate_first(repository, canonical_revision)
    candidate = _second_canonical(canonical_revision)
    repository.add_canonical_revision(candidate)
    attempt = coordinator.prepare(
        candidate.revision_id,
        attempt_id="activate-2",
        prepared_at=NOW + timedelta(minutes=2),
    )
    coordinator.begin_applying(attempt.attempt_id, applying_at=NOW + timedelta(minutes=2, seconds=1))
    wrong = _loaded(canonical_revision).model_copy(update={"semantic_configuration_fingerprint": "f" * 64})

    with pytest.raises(SetupConflictError, match="does not match last-known-good"):
        coordinator.record_failed_application(
            attempt.attempt_id,
            completed_at=NOW + timedelta(minutes=2, seconds=2),
            failure_code="candidate_start_failed",
            rollback_succeeded=True,
            rollback_runtime_stamp=wrong,
        )


def test_loaded_runtime_evidence_rejects_shadow_origin() -> None:
    values = {
        "canonical_revision_id": "revision",
        "semantic_configuration_fingerprint": "0" * 64,
        "environment_id": "home",
        "origin": RuntimeConfigurationOrigin.SHADOW_SIMULATION,
        "module_key": "heating",
        "module_instance_id": "main-heating",
    }

    with pytest.raises(ValueError):
        LoadedRuntimeConfiguration.model_validate(values)


def test_activation_reservation_and_transitions_reject_stale_writes(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical_revision)
    coordinator = _coordinator(repository)
    prepared = coordinator.prepare(canonical_revision.revision_id, attempt_id="activate-1", prepared_at=NOW)

    with pytest.raises(SetupConflictError, match="already in progress"):
        coordinator.prepare(canonical_revision.revision_id, attempt_id="activate-2", prepared_at=NOW)

    applying = coordinator.begin_applying(prepared.attempt_id, applying_at=NOW + timedelta(seconds=1))
    with pytest.raises(SetupConflictError, match="changed before transition"):
        repository.transition_activation_attempt(
            applying.model_copy(update={"version": applying.version + 1}),
            expected_state=ActivationState.PREPARED,
            expected_version=prepared.version,
        )

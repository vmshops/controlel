from datetime import UTC, datetime

import pytest

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_SENSOR_ROLE,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
)
from controlel.application.setup import (
    ActivationCoordinator,
    ActivationState,
    BindingSelection,
    CandidateRuntimeReady,
    DraftRevision,
    IdentityQuality,
    InMemorySetupRepository,
    LoadedRuntimeConfiguration,
    ProviderReference,
    SelectionOrigin,
)

NOW = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
NOTIFY_ROLE = "water_safety.notification.family"
SIREN_ROLE = "water_safety.siren.hall"


def _reference(native_id: str, *, stable: bool = True, locator: str | None = None) -> ProviderReference:
    return ProviderReference(
        provider="test_provider",
        provider_instance_id="home",
        object_kind="provider.object",
        native_id=native_id if stable else None,
        identity_quality=IdentityQuality.STABLE if stable else IdentityQuality.EPHEMERAL,
        current_locator=locator or f"current/{native_id}",
        area_id="utility-room",
    )


def _binding(role: str, native_id: str, *, stable: bool = True) -> BindingSelection:
    return BindingSelection(
        role=role,
        reference=_reference(native_id, stable=stable),
        selection_origin=SelectionOrigin.MANUAL,
        user_confirmed=True,
    )


def _draft(*, sensor_stable: bool = True, schema_version: int = 1) -> DraftRevision:
    return DraftRevision(
        draft_id="water-draft",
        revision=1,
        environment_id="home",
        module_key="water_safety",
        module_instance_id="utility-water",
        module_schema_version=schema_version,
        created_at=NOW,
        updated_at=NOW,
        settings={
            "behavior_contract_version": 1,
            "zone_id": "utility",
            "zone_name": "Utility",
            "area_id": "utility-room",
            "area_name": "Utility room",
            "sensor_id": "utility-moisture",
            "critical_sensor": False,
            "unavailable_grace_seconds": 30.0,
            "fault_repeat_interval_seconds": 300.0,
            "notification_target_roles": [NOTIFY_ROLE],
            "siren_target_roles": [SIREN_ROLE],
            "messages": {"wet": "Water detected", "recovery": "Area is dry", "fault": "Sensor fault"},
        },
        bindings=(
            _binding(WATER_SAFETY_SENSOR_ROLE, "sensor-native", stable=sensor_stable),
            _binding(NOTIFY_ROLE, "notify-native"),
            _binding(SIREN_ROLE, "siren-native"),
        ),
    )


def test_water_draft_validates_and_canonicalizes_with_explicit_v1_meaning() -> None:
    draft = _draft()
    adapter = WaterSafetySetupAdapter()

    report = adapter.validate(draft, report_id="water-report", evaluated_at=NOW)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision-1",
        revision=1,
        provider="test_provider",
        provider_instance_id="home",
        created_at=NOW,
        actor="user:owner",
        source="setup_api",
        change_kind="CREATE",
        reason="initial_water_safety",
        core_version="0.14.0",
    )

    assert report.activation_ready
    assert canonical.module_key == "water_safety"
    assert canonical.module_schema_version == 1
    assert canonical.module_payload["behavior_contract_version"] == 1
    assert canonical.logical_identities == {
        "area_id": "utility-room",
        "sensor_id": "utility-moisture",
        "zone_id": "utility",
    }
    assert canonical.module_payload["notification_target_roles"] == (NOTIFY_ROLE,)
    assert canonical.module_payload["shutoff_valve_target_roles"] == ()


def test_water_validation_requires_stable_references_without_entity_locator_assumptions() -> None:
    draft = _draft(sensor_stable=False)

    report = WaterSafetySetupAdapter().validate(draft, report_id="unstable", evaluated_at=NOW)

    assert not report.activation_ready
    assert any(issue.code == "water_safety.stable_reference_required" for issue in report.issues)
    assert all("entity_id" not in issue.code for issue in report.issues)


def test_water_validation_rejects_missing_targets_extra_settings_and_unknown_schema() -> None:
    adapter = WaterSafetySetupAdapter()
    complete = _draft()
    missing = complete.model_copy(update={"bindings": complete.bindings[:1]})
    extra_settings = dict(complete.settings)
    extra_settings["future_meaning"] = True
    extra = complete.next_revision(updated_at=NOW, settings=extra_settings)

    missing_report = adapter.validate(missing, report_id="missing", evaluated_at=NOW)
    extra_report = adapter.validate(extra, report_id="extra", evaluated_at=NOW)
    schema_report = adapter.validate(_draft(schema_version=2), report_id="schema", evaluated_at=NOW)

    assert not missing_report.activation_ready
    assert {issue.module_role for issue in missing_report.issues} >= {NOTIFY_ROLE, SIREN_ROLE}
    assert not extra_report.activation_ready
    assert any(issue.path == ("future_meaning",) for issue in extra_report.issues)
    assert not schema_report.activation_ready
    assert any(issue.code == "water_safety.unsupported_module_contract" for issue in schema_report.issues)


def test_canonicalization_rejects_a_different_validator_policy_version() -> None:
    draft = _draft()
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=NOW)
    old_policy_report = report.model_copy(update={"validator_policy_version": 2})

    with pytest.raises(ValueError, match="validator policy"):
        adapter.canonicalize(
            draft,
            old_policy_report,
            configuration_id="water-config",
            revision_id="water-revision",
            revision=1,
            provider="test_provider",
            provider_instance_id="home",
            created_at=NOW,
            actor="user",
            source="test",
            change_kind="CREATE",
            reason="test",
            core_version="0.14.0",
        )


def test_water_uses_shared_draft_validate_canonicalize_activate_authority() -> None:
    draft = _draft()
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=NOW)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="test_provider",
        provider_instance_id="home",
        created_at=NOW,
        actor="user",
        source="test",
        change_kind="CREATE",
        reason="test",
        core_version="0.14.0",
    )
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical)
    coordinator = ActivationCoordinator(
        repository,
        repository,
        supported_module_schema_versions={"water_safety": WATER_SAFETY_SETUP_SCHEMA_VERSION},
    )
    prepared = coordinator.prepare(canonical.revision_id, attempt_id="activate-water", prepared_at=NOW)
    coordinator.begin_applying(prepared.attempt_id, applying_at=NOW)
    coordinator.record_candidate_runtime_ready(
        prepared.attempt_id,
        candidate_ready=CandidateRuntimeReady(
            runtime=LoadedRuntimeConfiguration(
                canonical_revision_id=canonical.revision_id,
                semantic_configuration_fingerprint=canonical.semantic_configuration_fingerprint,
                environment_id=canonical.environment_id,
                module_key=canonical.module_key,
                module_instance_id=canonical.module_instance_id,
            ),
            ready_at=NOW,
            host_adapter="test_host",
            readiness_evidence={"current_sensor_evaluated": True},
        ),
    )
    committed = coordinator.commit(prepared.attempt_id, committed_at=NOW)

    active = repository.get_active_reference(committed.scope_key)
    assert committed.state is ActivationState.COMMITTED
    assert active is not None
    assert active.canonical_revision_id == canonical.revision_id

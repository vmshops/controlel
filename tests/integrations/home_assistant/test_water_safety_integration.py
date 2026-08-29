"""End-to-end Water Safety integration tests across setup, activation, and runtime."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

if importlib.util.find_spec("controlel.application.water_safety") is None:
    pytest.skip("requires candidate Water Safety core", allow_module_level=True)

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_SENSOR_ROLE,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
)
from controlel.application.setup import (
    ActivationCoordinator,
    BindingSelection,
    CandidateRuntimeReady,
    DraftRevision,
    IdentityQuality,
    InMemorySetupRepository,
    LoadedRuntimeConfiguration,
    ProviderReference,
    SelectionOrigin,
    derive_real_runtime_configuration,
)
from controlel.application.water_safety import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterOutputOutcome,
    WaterSafetyEvent,
    WaterSafetyRuntime,
)
from controlel.domain.water_safety import (
    MoistureCondition,
    MoistureObservation,
    WaterSafetyAssessmentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
)

T0 = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
NOTIFY = "water_safety.notification.home"
SIREN = "water_safety.siren.hall"


@dataclass
class RecordingOutput:
    commands: list[WaterOutputCommand] = field(default_factory=list)

    def request(self, command: WaterOutputCommand) -> WaterOutputCommandResult:
        self.commands.append(command)
        return WaterOutputCommandResult(
            command_id=command.command_id,
            occurred_at=command.requested_at,
            outcome=WaterOutputOutcome.ACCEPTED,
        )


@dataclass
class RecordingState:
    snapshots: list[WaterSafetySnapshot] = field(default_factory=list)

    def save(self, snapshot: WaterSafetySnapshot) -> None:
        self.snapshots.append(snapshot)


@dataclass
class RecordingEvidence:
    events: list[WaterSafetyEvent] = field(default_factory=list)

    def record(self, event: WaterSafetyEvent) -> None:
        self.events.append(event)


def _reference(native_id: str, locator: str) -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="home",
        object_kind="home_assistant.entity",
        native_id=native_id,
        identity_quality=IdentityQuality.STABLE,
        current_locator=locator,
    )


def _notify_ref(service: str) -> ProviderReference:
    locator = f"notify.{service}"
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="home",
        object_kind="home_assistant.endpoint",
        native_id=locator,
        identity_quality=IdentityQuality.STABLE,
        current_locator=locator,
    )


def _draft(*, grace: float = 30.0, repeat: float | None = 120.0, critical: bool = False) -> DraftRevision:
    bindings = (
        BindingSelection(
            role=WATER_SAFETY_SENSOR_ROLE,
            reference=_reference("moisture-entity", "binary_sensor.utility_moisture"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
        BindingSelection(
            role=NOTIFY,
            reference=_notify_ref("mobile_app_phone"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
        BindingSelection(
            role=SIREN,
            reference=_reference("siren-entity", "switch.hall_siren"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
    )
    return DraftRevision(
        draft_id="water-draft",
        revision=1,
        environment_id="home",
        module_key="water_safety",
        module_instance_id="utility-water",
        module_schema_version=1,
        created_at=T0,
        updated_at=T0,
        settings={
            "behavior_contract_version": 1,
            "zone_id": "utility",
            "zone_name": "Utility",
            "area_id": "utility-room",
            "area_name": "Utility room",
            "sensor_id": "utility-moisture",
            "critical_sensor": critical,
            "unavailable_grace_seconds": grace,
            "fault_repeat_interval_seconds": repeat,
            "notification_target_roles": [NOTIFY],
            "siren_target_roles": [SIREN],
            "messages": {},
        },
        bindings=bindings,
    )


def _effective(draft: DraftRevision | None = None):
    draft = draft or _draft()
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=T0)
    assert report.activation_ready
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="home",
        created_at=T0,
        actor="test",
        source="test",
        change_kind="CREATE",
        reason="test",
        core_version="0.17.0",
    )
    resolved = {binding.role: binding.reference for binding in draft.bindings}
    return derive_real_runtime_configuration(canonical, resolved), canonical


def _observation(condition: MoistureCondition, at: datetime) -> MoistureObservation:
    return MoistureObservation(
        sensor_id="utility-moisture",
        condition=condition,
        observed_at=at,
        provider_state=condition.value.lower(),
    )


def _runtime(
    output: RecordingOutput,
    *,
    state: RecordingState | None = None,
    evidence: RecordingEvidence | None = None,
    restored: WaterSafetySnapshot | None = None,
):
    effective, _ = _effective()
    return WaterSafetyRuntime(
        effective,
        output,
        state_port=state,
        evidence_port=evidence,
        restored_snapshot=restored,
    )


def _actions(output: RecordingOutput) -> list[WaterOutputAction]:
    return [command.action for command in output.commands]


def test_configure_validate_canonicalize_and_activate_authority() -> None:
    draft = _draft()
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=T0)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="home",
        created_at=T0,
        actor="user",
        source="setup",
        change_kind="CREATE",
        reason="initial",
        core_version="0.16.0",
    )
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical)
    coordinator = ActivationCoordinator(
        repository,
        repository,
        supported_module_schema_versions={"water_safety": WATER_SAFETY_SETUP_SCHEMA_VERSION},
    )
    prepared = coordinator.prepare(canonical.revision_id, attempt_id="activate", prepared_at=T0)
    coordinator.begin_applying(prepared.attempt_id, applying_at=T0)
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
            ready_at=T0,
            host_adapter="test_host",
            readiness_evidence={"current_sensor_evaluated": True},
        ),
    )
    committed = coordinator.commit(prepared.attempt_id, committed_at=T0)
    active = repository.get_active_reference(committed.scope_key)
    assert active is not None
    assert active.canonical_revision_id == canonical.revision_id


def test_dry_start_is_ok() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    result = runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    assert result.state is WaterSafetyState.OK
    assert _actions(output) == []


def test_wet_triggers_notify_and_siren() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    result = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    assert result.state is WaterSafetyState.WET
    assert WaterOutputAction.NOTIFY_WET in _actions(output)
    assert WaterOutputAction.REQUEST_SIREN_ON in _actions(output)


def test_persistent_wet_does_not_duplicate_incident() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    first_count = len(output.commands)
    runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=5)))
    assert len(output.commands) == first_count


def test_silence_stops_sirens_but_keeps_wet_incident() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    output.commands.clear()
    result = runtime.silence(silenced_at=T0 + timedelta(seconds=10))
    assert result.state is WaterSafetyState.WET
    assert _actions(output) == [WaterOutputAction.REQUEST_SIREN_OFF]


def test_dry_recovery_notifies_and_turns_sirens_off() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    output.commands.clear()
    result = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(seconds=20)))
    assert result.state is WaterSafetyState.OK
    assert WaterOutputAction.NOTIFY_RECOVERY in _actions(output)
    assert WaterOutputAction.REQUEST_SIREN_OFF in _actions(output)


def test_unavailable_grace_is_indeterminate_before_fault() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    result = runtime.observe(_observation(MoistureCondition.UNAVAILABLE, T0 + timedelta(seconds=1)))
    assert result.assessment_status is WaterSafetyAssessmentStatus.INDETERMINATE_GRACE
    assert result.state is WaterSafetyState.OK
    assert WaterOutputAction.NOTIFY_SENSOR_FAULT not in _actions(output)


def test_sensor_fault_and_repeat_for_critical_sensor() -> None:
    output = RecordingOutput()
    effective, _ = _effective(_draft(grace=0, repeat=60, critical=True))
    runtime = WaterSafetyRuntime(effective, output)
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNAVAILABLE, T0 + timedelta(seconds=1)))
    assert runtime.state is WaterSafetyState.SENSOR_FAULT
    output.commands.clear()
    runtime.tick(T0 + timedelta(seconds=61))
    assert WaterOutputAction.NOTIFY_SENSOR_FAULT in _actions(output)


def test_disable_while_wet_preserves_incident_evidence() -> None:
    output = RecordingOutput()
    evidence = RecordingEvidence()
    runtime = _runtime(output, evidence=evidence)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    incident_id = runtime.snapshot.active_incident.incident_id if runtime.snapshot.active_incident else None
    result = runtime.disable(disabled_at=T0 + timedelta(seconds=5))
    assert result.state is WaterSafetyState.DISABLED
    assert runtime.snapshot.active_incident is not None
    assert runtime.snapshot.active_incident.incident_id == incident_id


def test_reenable_while_still_wet_reasserts_outputs() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    runtime.disable(disabled_at=T0 + timedelta(seconds=1))
    output.commands.clear()
    wet_at = T0 + timedelta(seconds=2)
    result = runtime.enable(_observation(MoistureCondition.WET, wet_at), enabled_at=wet_at)
    assert result.state is WaterSafetyState.WET
    assert WaterOutputAction.REQUEST_SIREN_ON in _actions(output)


def test_restart_restores_wet_state() -> None:
    output = RecordingOutput()
    state = RecordingState()
    runtime = _runtime(output, state=state)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    restored = state.snapshots[-1]
    restarted = _runtime(RecordingOutput(), restored=restored)
    restart_at = T0 + timedelta(seconds=30)
    restarted.start(_observation(MoistureCondition.WET, restart_at), started_at=restart_at)
    assert restarted.state is WaterSafetyState.WET
    assert restarted.snapshot.active_incident is not None


def test_cross_surface_config_semantics_match_canonical_payload() -> None:
    draft = _draft(grace=45, critical=True)
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=T0)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="home",
        created_at=T0,
        actor="user",
        source="setup",
        change_kind="CREATE",
        reason="initial",
        core_version="0.17.0",
    )
    effective, _ = _effective(draft)
    payload = effective.module_payload
    assert payload["unavailable_grace_seconds"] == 45
    assert payload["critical_sensor"] is True
    assert canonical.logical_identities["sensor_id"] == payload["sensor_id"]
    assert canonical.logical_identities["area_id"] == payload["area_id"]

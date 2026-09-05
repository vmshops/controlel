from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_SENSOR_ROLE,
    WaterSafetySetupAdapter,
)
from controlel.application.services.water_safety_projector import WaterSafetyDiagnosticsProjector
from controlel.application.setup import (
    BindingSelection,
    DraftRevision,
    IdentityQuality,
    ProviderReference,
    SelectionOrigin,
    derive_real_runtime_configuration,
)
from controlel.application.water_safety import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterOutputKind,
    WaterOutputOutcome,
    WaterSafetyEvent,
    WaterSafetyEventCode,
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
NOTIFY_HOME = "water_safety.notification.home"
NOTIFY_OWNER = "water_safety.notification.owner"
SIREN_HALL = "water_safety.siren.hall"
SIREN_CELLAR = "water_safety.siren.cellar"
VALVE_MAIN = "water_safety.shutoff_valve.main"
VALVE_BACKUP = "water_safety.shutoff_valve.backup"


@dataclass
class RecordingOutput:
    commands: list[WaterOutputCommand] = field(default_factory=list)
    failing: set[tuple[str, WaterOutputAction]] = field(default_factory=set)

    def request(self, command: WaterOutputCommand) -> WaterOutputCommandResult:
        self.commands.append(command)
        failed = (command.target_role, command.action) in self.failing
        return WaterOutputCommandResult(
            command_id=command.command_id,
            occurred_at=command.requested_at,
            outcome=WaterOutputOutcome.FAILED if failed else WaterOutputOutcome.ACCEPTED,
            failure_code="test_failure" if failed else None,
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
        provider="generic_provider",
        provider_instance_id="home",
        object_kind="generic.object",
        native_id=native_id,
        identity_quality=IdentityQuality.STABLE,
        current_locator=locator,
        area_id="utility-room",
    )


def _effective(
    *,
    critical: bool = False,
    grace: float = 30.0,
    repeat: float | None = 120.0,
    siren_roles: tuple[str, ...] = (SIREN_HALL,),
    valve_roles: tuple[str, ...] = (),
):
    siren_roles = tuple(sorted(siren_roles))
    valve_roles = tuple(sorted(valve_roles))
    notification_roles = (NOTIFY_HOME, NOTIFY_OWNER)
    references = {
        WATER_SAFETY_SENSOR_ROLE: _reference("moisture-1", "sensor/current-name"),
        NOTIFY_HOME: _reference("notify-home", "notify/current-home"),
        NOTIFY_OWNER: _reference("notify-owner", "notify/current-owner"),
        **{
            role: _reference(f"siren-{index}", f"siren/current-{index}")
            for index, role in enumerate(siren_roles, start=1)
        },
        **{
            role: _reference(f"valve-{index}", f"valve/current-{index}")
            for index, role in enumerate(valve_roles, start=1)
        },
    }
    bindings = tuple(
        BindingSelection(
            role=role,
            reference=reference,
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        )
        for role, reference in sorted(references.items())
    )
    draft = DraftRevision(
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
            "notification_target_roles": notification_roles,
            "siren_target_roles": siren_roles,
            "shutoff_valve_target_roles": valve_roles,
            "messages": {
                "wet": "Custom wet",
                "recovery": "Custom recovery",
                "fault": "Custom fault",
            },
        },
        bindings=bindings,
    )
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=T0)
    assert report.activation_ready
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="generic_provider",
        provider_instance_id="home",
        created_at=T0,
        actor="test",
        source="test",
        change_kind="CREATE",
        reason="test",
        core_version="0.14.0",
    )
    resolved = {
        role: reference.model_copy(update={"current_locator": f"renamed/{index}"})
        for index, (role, reference) in enumerate(sorted(references.items()), start=1)
    }
    return derive_real_runtime_configuration(canonical, resolved)


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
    effective=None,
    state: RecordingState | None = None,
    evidence: RecordingEvidence | None = None,
    restored: WaterSafetySnapshot | None = None,
) -> WaterSafetyRuntime:
    return WaterSafetyRuntime(
        effective or _effective(),
        output,
        state_port=state,
        evidence_port=evidence,
        restored_snapshot=restored,
    )


def _actions(output: RecordingOutput) -> list[WaterOutputAction]:
    return [command.action for command in output.commands]


def test_dry_start_is_ok_and_an_unchanged_sensor_does_not_become_stale() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)

    started = runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    later = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(days=2)))

    assert started.state is WaterSafetyState.OK
    assert later.state is WaterSafetyState.OK
    assert runtime.next_deadline is None
    assert output.commands == []


def test_wet_persistent_wet_and_recovery_have_one_truthful_incident_lifecycle() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)

    wet = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    incident_id = wet.snapshot.active_incident.incident_id
    wet_commands = tuple(output.commands)
    persistent = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(minutes=5)))
    recovered = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(minutes=6)))

    assert wet.state is WaterSafetyState.WET
    assert _actions(output)[:3] == [
        WaterOutputAction.REQUEST_SIREN_ON,
        WaterOutputAction.NOTIFY_WET,
        WaterOutputAction.NOTIFY_WET,
    ]
    assert all(command.custom_message == "Custom wet" for command in wet_commands if command.message_code)
    assert persistent.snapshot.active_incident.incident_id == incident_id
    assert len(output.commands) == len(wet_commands) + 3
    assert recovered.state is WaterSafetyState.OK
    assert recovered.snapshot.last_incident.incident_id == incident_id
    assert recovered.snapshot.last_incident.recovered_at == T0 + timedelta(minutes=6)
    assert _actions(output)[-3:] == [
        WaterOutputAction.REQUEST_SIREN_OFF,
        WaterOutputAction.NOTIFY_RECOVERY,
        WaterOutputAction.NOTIFY_RECOVERY,
    ]


def test_unavailable_and_unknown_share_one_grace_and_never_become_dry() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(grace=30.0))
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    incident_id = runtime.snapshot.active_incident.incident_id

    unavailable = runtime.observe(_observation(MoistureCondition.UNAVAILABLE, T0 + timedelta(seconds=5)))
    original_deadline = unavailable.snapshot.fault_deadline
    unknown = runtime.observe(_observation(MoistureCondition.UNKNOWN, T0 + timedelta(seconds=20)))
    before = runtime.tick(T0 + timedelta(seconds=34))
    fault = runtime.tick(T0 + timedelta(seconds=35))

    assert unavailable.state is WaterSafetyState.WET
    assert unknown.state is WaterSafetyState.WET
    assert unknown.snapshot.fault_deadline == original_deadline
    assert before.state is WaterSafetyState.WET
    assert fault.state is WaterSafetyState.SENSOR_FAULT
    assert fault.snapshot.active_incident.incident_id == incident_id
    assert WaterOutputAction.NOTIFY_RECOVERY not in _actions(output)
    assert _actions(output).count(WaterOutputAction.NOTIFY_SENSOR_FAULT) == 0


def test_critical_sensor_unavailable_before_grace_is_indeterminate_without_alarm() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(critical=True, grace=30.0, repeat=60.0))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)

    pending = runtime.observe(_observation(MoistureCondition.UNAVAILABLE, T0 + timedelta(seconds=1)))
    before = runtime.tick(T0 + timedelta(seconds=30, milliseconds=999))

    assert pending.state is WaterSafetyState.OK
    assert pending.assessment_status is WaterSafetyAssessmentStatus.INDETERMINATE_GRACE
    assert before.assessment_status is WaterSafetyAssessmentStatus.INDETERMINATE_GRACE
    assert pending.snapshot.latest_observation.condition is MoistureCondition.UNAVAILABLE
    assert pending.snapshot.last_confirmed_observation.condition is MoistureCondition.DRY
    assert _actions(output).count(WaterOutputAction.NOTIFY_SENSOR_FAULT) == 0


def test_critical_sensor_faults_exactly_at_configured_grace() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(critical=True, grace=30.0, repeat=60.0))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNKNOWN, T0 + timedelta(seconds=1)))

    fault = runtime.tick(T0 + timedelta(seconds=31))

    assert fault.state is WaterSafetyState.SENSOR_FAULT
    assert fault.assessment_status is WaterSafetyAssessmentStatus.CONFIRMED
    assert fault.snapshot.fault_deadline is None
    assert _actions(output).count(WaterOutputAction.NOTIFY_SENSOR_FAULT) == 2
    assert fault.snapshot.next_fault_notification_at == T0 + timedelta(seconds=91)


def test_critical_sensor_faults_after_configured_grace_and_repeats_from_delivery_time() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(critical=True, grace=30.0, repeat=60.0))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNKNOWN, T0 + timedelta(seconds=1)))

    late_fault = runtime.tick(T0 + timedelta(seconds=40))
    late_repeat = runtime.tick(T0 + timedelta(seconds=110))

    assert late_fault.state is WaterSafetyState.SENSOR_FAULT
    assert _actions(output).count(WaterOutputAction.NOTIFY_SENSOR_FAULT) == 4
    assert all(
        command.custom_message == "Custom fault"
        for command in output.commands
        if command.action is WaterOutputAction.NOTIFY_SENSOR_FAULT
    )
    assert any(command.repeated for command in output.commands)
    assert late_repeat.snapshot.next_fault_notification_at == T0 + timedelta(seconds=170)


def test_critical_sensor_recovery_before_grace_cancels_pending_fault() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(critical=True, grace=30.0, repeat=60.0))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNKNOWN, T0 + timedelta(seconds=1)))

    recovered = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(seconds=20)))
    after_original_deadline = runtime.tick(T0 + timedelta(seconds=31))

    assert recovered.state is WaterSafetyState.OK
    assert recovered.assessment_status is WaterSafetyAssessmentStatus.CONFIRMED
    assert recovered.snapshot.fault_deadline is None
    assert after_original_deadline.state is WaterSafetyState.OK
    assert _actions(output).count(WaterOutputAction.NOTIFY_SENSOR_FAULT) == 0
    assert all(event.code is not WaterSafetyEventCode.SENSOR_FAULT_STARTED for event in recovered.events)
    assert any(event.code is WaterSafetyEventCode.SENSOR_GRACE_CANCELLED for event in recovered.events)


def test_critical_sensor_recovery_after_fault_closes_fault_and_cancels_repeats() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(critical=True, grace=30.0, repeat=60.0))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNAVAILABLE, T0 + timedelta(seconds=1)))
    runtime.tick(T0 + timedelta(seconds=31))

    recovered = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(seconds=32)))
    command_count = len(output.commands)
    after_repeat_deadline = runtime.tick(T0 + timedelta(seconds=100))

    assert recovered.state is WaterSafetyState.OK
    assert recovered.assessment_status is WaterSafetyAssessmentStatus.CONFIRMED
    assert recovered.snapshot.next_fault_notification_at is None
    assert any(event.code is WaterSafetyEventCode.SENSOR_FAULT_RECOVERED for event in recovered.events)
    assert after_repeat_deadline.output_results == ()
    assert len(output.commands) == command_count


def test_sirens_and_fault_repeats_are_independently_optional() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(repeat=None, siren_roles=()))
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.UNKNOWN, T0 + timedelta(seconds=1)))
    fault = runtime.tick(T0 + timedelta(seconds=31))
    command_count = len(output.commands)
    later = runtime.tick(T0 + timedelta(days=1))

    assert fault.state is WaterSafetyState.SENSOR_FAULT
    assert runtime.owned_outputs() == ()
    assert fault.snapshot.next_fault_notification_at is None
    assert later.output_results == ()
    assert len(output.commands) == command_count


def test_silence_requests_sirens_off_but_incident_remains_wet() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    incident_id = runtime.snapshot.active_incident.incident_id

    silenced = runtime.silence(silenced_at=T0 + timedelta(seconds=1))
    runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=2)))

    assert silenced.state is WaterSafetyState.WET
    assert silenced.snapshot.active_incident.incident_id == incident_id
    assert silenced.snapshot.active_incident.silenced_at == T0 + timedelta(seconds=1)
    assert _actions(output).count(WaterOutputAction.REQUEST_SIREN_ON) == 1
    assert _actions(output).count(WaterOutputAction.REQUEST_SIREN_OFF) == 1


def test_disable_while_wet_attempts_every_cleanup_and_records_partial_failure() -> None:
    output = RecordingOutput(failing={(SIREN_CELLAR, WaterOutputAction.REQUEST_SIREN_OFF)})
    runtime = _runtime(output, effective=_effective(siren_roles=(SIREN_HALL, SIREN_CELLAR)))
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    command_count = len(output.commands)

    disabled = runtime.disable(disabled_at=T0 + timedelta(seconds=1))
    runtime.tick(T0 + timedelta(days=1))
    runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(days=1)))

    cleanup = disabled.output_results
    disabled_event = next(event for event in disabled.events if event.code is WaterSafetyEventCode.MODULE_DISABLED)
    assert disabled.state is WaterSafetyState.DISABLED
    assert disabled.snapshot.active_incident is not None
    assert runtime.next_deadline is None
    assert len(cleanup) == 2
    assert {result.outcome for result in cleanup} == {WaterOutputOutcome.ACCEPTED, WaterOutputOutcome.FAILED}
    assert dict(disabled_event.details) == {"cleanup_failed": 1, "cleanup_requested": 2}
    assert len(output.commands) == command_count + 2
    assert all(owned.last_requested_action is WaterOutputAction.REQUEST_SIREN_OFF for owned in runtime.owned_outputs())


def test_wet_partial_siren_failure_does_not_block_other_sirens_or_notifications() -> None:
    output = RecordingOutput(failing={(SIREN_CELLAR, WaterOutputAction.REQUEST_SIREN_ON)})
    runtime = _runtime(output, effective=_effective(siren_roles=(SIREN_HALL, SIREN_CELLAR)))
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)

    wet = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    siren_commands = [command for command in output.commands if command.output_kind is WaterOutputKind.SIREN]
    notification_commands = [
        command for command in output.commands if command.output_kind is WaterOutputKind.NOTIFICATION
    ]

    assert wet.state is WaterSafetyState.WET
    assert len(siren_commands) == 2
    assert len(notification_commands) == 2
    assert {result.outcome for result in wet.output_results} == {
        WaterOutputOutcome.ACCEPTED,
        WaterOutputOutcome.FAILED,
    }
    assert all(
        dict(event.details) == {"physical_state_confirmed": False}
        for event in wet.events
        if event.code is WaterSafetyEventCode.OUTPUT_REQUESTED
    )

    command_count = len(output.commands)
    repeated = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(minutes=5)))
    assert repeated.output_results == ()
    assert len(output.commands) == command_count


def test_wet_closes_all_valves_once_and_partial_failure_does_not_block_other_outputs() -> None:
    output = RecordingOutput(failing={(VALVE_BACKUP, WaterOutputAction.REQUEST_VALVE_CLOSE)})
    runtime = _runtime(
        output,
        effective=_effective(
            siren_roles=(SIREN_HALL,),
            valve_roles=(VALVE_MAIN, VALVE_BACKUP),
        ),
    )
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)

    wet = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    valve_commands = [command for command in output.commands if command.output_kind is WaterOutputKind.SHUTOFF_VALVE]

    assert wet.state is WaterSafetyState.WET
    assert [command.action for command in valve_commands] == [
        WaterOutputAction.REQUEST_VALVE_CLOSE,
        WaterOutputAction.REQUEST_VALVE_CLOSE,
    ]
    assert {result.outcome for result in wet.output_results} == {
        WaterOutputOutcome.ACCEPTED,
        WaterOutputOutcome.FAILED,
    }
    assert any(command.output_kind is WaterOutputKind.SIREN for command in output.commands)
    assert any(command.output_kind is WaterOutputKind.NOTIFICATION for command in output.commands)
    assert all(
        event.command is None or dict(event.details) == {"physical_state_confirmed": False} for event in wet.events
    )

    command_count = len(output.commands)
    repeated = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(minutes=5)))
    recovered = runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(minutes=6)))

    assert repeated.output_results == ()
    assert len([command for command in output.commands if command.output_kind is WaterOutputKind.SHUTOFF_VALVE]) == 2
    assert recovered.state is WaterSafetyState.OK
    assert all(
        command.action is not WaterOutputAction.REQUEST_VALVE_CLOSE for command in output.commands[command_count:]
    )
    owned_valves = [output for output in runtime.owned_outputs() if output.output_kind is WaterOutputKind.SHUTOFF_VALVE]
    assert len(owned_valves) == 2
    assert all(output.last_requested_action is WaterOutputAction.REQUEST_VALVE_CLOSE for output in owned_valves)
    projected = WaterSafetyDiagnosticsProjector().project(
        runtime.diagnostics(),
        area_name="Utility room",
        zone_name="Utility",
    )
    assert projected.owned_siren_count == 1


def test_activation_and_restart_while_wet_deterministically_reassert_close_without_reopen() -> None:
    effective = _effective(siren_roles=(), valve_roles=(VALVE_MAIN,))
    first_output = RecordingOutput()
    first = _runtime(first_output, effective=effective)

    activated = first.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    incident_id = activated.snapshot.active_incident.incident_id
    assert _actions(first_output) == [
        WaterOutputAction.REQUEST_VALVE_CLOSE,
        WaterOutputAction.NOTIFY_WET,
        WaterOutputAction.NOTIFY_WET,
    ]

    restarted_output = RecordingOutput()
    restarted = _runtime(restarted_output, effective=effective, restored=first.snapshot)
    restarted_result = restarted.start(
        _observation(MoistureCondition.WET, T0 + timedelta(seconds=10)),
        started_at=T0 + timedelta(seconds=10),
    )

    assert restarted_result.snapshot.active_incident.incident_id == incident_id
    assert _actions(restarted_output) == [WaterOutputAction.REQUEST_VALVE_CLOSE]
    recovered = restarted.observe(_observation(MoistureCondition.DRY, T0 + timedelta(seconds=20)))
    assert recovered.state is WaterSafetyState.OK
    assert WaterOutputAction.REQUEST_VALVE_CLOSE not in _actions(restarted_output)[1:]


def test_reenable_silenced_wet_incident_reasserts_valve_close_without_restarting_siren() -> None:
    output = RecordingOutput()
    runtime = _runtime(output, effective=_effective(valve_roles=(VALVE_MAIN,)))
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    runtime.silence(silenced_at=T0 + timedelta(seconds=1))
    runtime.disable(disabled_at=T0 + timedelta(seconds=2))

    enabled = runtime.enable(
        _observation(MoistureCondition.WET, T0 + timedelta(seconds=3)),
        enabled_at=T0 + timedelta(seconds=3),
    )

    assert enabled.state is WaterSafetyState.WET
    assert _actions(output).count(WaterOutputAction.REQUEST_VALVE_CLOSE) == 2
    assert _actions(output).count(WaterOutputAction.REQUEST_SIREN_ON) == 1


def test_reenable_while_still_wet_reuses_incident_and_reasserts_unsilenced_siren() -> None:
    output = RecordingOutput()
    runtime = _runtime(output)
    runtime.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    incident_id = runtime.snapshot.active_incident.incident_id
    runtime.disable(disabled_at=T0 + timedelta(seconds=1))

    enabled = runtime.enable(
        _observation(MoistureCondition.WET, T0 + timedelta(seconds=2)),
        enabled_at=T0 + timedelta(seconds=2),
    )

    assert enabled.state is WaterSafetyState.WET
    assert enabled.snapshot.active_incident.incident_id == incident_id
    assert _actions(output).count(WaterOutputAction.REQUEST_SIREN_ON) == 2
    assert _actions(output).count(WaterOutputAction.NOTIFY_WET) == 2


def test_restart_preserves_incident_and_reasserts_output_without_duplicate_wet_notice() -> None:
    first_output = RecordingOutput()
    effective = _effective()
    first = _runtime(first_output, effective=effective)
    first.start(_observation(MoistureCondition.WET, T0), started_at=T0)
    snapshot = first.snapshot
    incident_id = snapshot.active_incident.incident_id
    restarted_output = RecordingOutput()

    restarted = _runtime(restarted_output, effective=effective, restored=snapshot)
    result = restarted.start(
        _observation(MoistureCondition.WET, T0 + timedelta(seconds=10)),
        started_at=T0 + timedelta(seconds=10),
    )

    assert result.state is WaterSafetyState.WET
    assert result.snapshot.active_incident.incident_id == incident_id
    assert _actions(restarted_output) == [WaterOutputAction.REQUEST_SIREN_ON]


def test_restart_rejects_state_from_a_different_canonical_authority() -> None:
    output = RecordingOutput()
    effective = _effective()
    first = _runtime(output, effective=effective)
    first.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    wrong = replace(first.snapshot, canonical_revision_id="different")

    with pytest.raises(ValueError, match="canonical runtime authority"):
        _runtime(RecordingOutput(), effective=effective, restored=wrong)


def test_stable_identity_survives_locator_changes_and_hooks_receive_state_and_evidence() -> None:
    output = RecordingOutput()
    state = RecordingState()
    evidence = RecordingEvidence()
    effective = _effective()
    sensor_binding = next(binding for binding in effective.bindings if binding.role == WATER_SAFETY_SENSOR_ROLE)
    runtime = _runtime(output, effective=effective, state=state, evidence=evidence)

    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    diagnostics = runtime.diagnostics()

    assert sensor_binding.reference.native_id == "moisture-1"
    assert sensor_binding.reference.current_locator.startswith("renamed/")
    assert state.snapshots[-1] == runtime.snapshot
    assert evidence.events
    assert diagnostics.state is WaterSafetyState.WET
    assert diagnostics.canonical_revision_id == "water-revision"
    assert diagnostics.owned_outputs[0].owner.module_key == "water_safety"
    assert diagnostics.owned_outputs[0].last_requested_action is WaterOutputAction.REQUEST_SIREN_ON


@pytest.mark.parametrize(
    "failed_code",
    [
        None,
        WaterSafetyEventCode.RUNTIME_STARTED,
        WaterSafetyEventCode.OBSERVATION_ACCEPTED,
        WaterSafetyEventCode.WET_INCIDENT_STARTED,
        WaterSafetyEventCode.WET_INCIDENT_RECOVERED,
        WaterSafetyEventCode.OUTPUT_REQUESTED,
    ],
)
def test_evidence_failure_never_blocks_wet_outputs_or_later_incidents(failed_code, caplog) -> None:
    class FailingEvidence(RecordingEvidence):
        def record(self, event):
            if failed_code is None or event.code is failed_code:
                raise OSError("history disk unavailable")
            super().record(event)

    evidence = FailingEvidence()
    output = RecordingOutput(failing={(VALVE_MAIN, WaterOutputAction.REQUEST_VALVE_CLOSE)})
    state = RecordingState()
    runtime = _runtime(output, effective=_effective(valve_roles=(VALVE_MAIN,)), state=state, evidence=evidence)
    runtime.start(_observation(MoistureCondition.DRY, T0), started_at=T0)
    wet = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=1)))
    assert wet.state is WaterSafetyState.WET
    assert wet.snapshot.active_incident is not None
    assert state.snapshots[-1] == wet.snapshot
    assert _actions(output) == [
        WaterOutputAction.REQUEST_VALVE_CLOSE,
        WaterOutputAction.REQUEST_SIREN_ON,
        WaterOutputAction.NOTIFY_WET,
        WaterOutputAction.NOTIFY_WET,
    ]
    assert [result.outcome for result in wet.output_results] == [
        WaterOutputOutcome.FAILED,
        WaterOutputOutcome.ACCEPTED,
        WaterOutputOutcome.ACCEPTED,
        WaterOutputOutcome.ACCEPTED,
    ]
    incident = wet.snapshot.active_incident.incident_id
    runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=2)))
    assert runtime.snapshot.active_incident.incident_id == incident
    assert len(output.commands) == 4
    runtime.observe(_observation(MoistureCondition.DRY, T0 + timedelta(seconds=3)))
    assert runtime.snapshot.active_incident is None
    later = runtime.observe(_observation(MoistureCondition.WET, T0 + timedelta(seconds=4)))
    assert later.snapshot.active_incident.incident_id != incident
    assert len(later.output_results) == 4
    assert all(
        command.action is WaterOutputAction.REQUEST_VALVE_CLOSE
        for command in output.commands
        if command.output_kind is WaterOutputKind.SHUTOFF_VALVE
    )
    assert "Water Safety evidence persistence failed" in caplog.text
    assert "history disk unavailable" in caplog.text
    assert "event_id=utility-water:event:" in caplog.text
    if failed_code is None:
        assert evidence.events == []
    else:
        assert all(event.code is not failed_code for event in evidence.events)

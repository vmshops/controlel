from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailure
from controlel.application.runtime.failsafe_runtime import FailsafeRuntime
from controlel.application.runtime.runtime_supervisor import CommandAuthorityError, RuntimeSupervisor
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.source_control_policy import SourceControlOutcome, SourceControlPolicy
from controlel.application.state.source_control_state import SourceCommandOutcome
from controlel.application.state.source_reconciliation_state import (
    SourceReconciliationReason,
    SourceReconciliationState,
    SourceReconciliationStatus,
)
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import OperatingMode, SafeHeatingProfile, SafeHeatingTemperatureEvidence
from controlel.domain.operational_events import OperationalEventCode
from controlel.domain.runtime_supervision import RestartPolicy, SupervisorPhase
from controlel.domain.source_control import ReportedSourceEvidence, ReportedSourceState, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SENSOR = SensorId("fallback")


class Clock:
    current = NOW

    def now(self):
        return self.current


class Source:
    def __init__(self):
        self.commands = []

    def execute(self, command):
        self.commands.append(command)


class FailingSource(Source):
    def execute(self, command):
        self.commands.append(command)
        raise RuntimeError("source dispatch failed")


class Task:
    def __init__(self, when, callback):
        self.when, self.callback, self.cancelled = when, callback, False

    def cancel(self):
        self.cancelled = True

    def invoke(self):
        self.callback()


class Scheduler:
    def __init__(self):
        self.tasks = []

    def schedule_at(self, when, callback):
        task = Task(when, callback)
        self.tasks.append(task)
        return task


def evidence(value=19.0, quality=ObservationQuality.VALID):
    return SafeHeatingTemperatureEvidence(sensor_id=SENSOR, value=value, quality=quality, observed_at=NOW)


def command(action=HeatingAction.ENABLE_HEATING):
    return HeatSourceCommand(command_type=CommandFamily.HEATING, action=action)


def failsafe_factory(*, minimum_on=timedelta(0), minimum_off=timedelta(0)):
    def create(port):
        return FailsafeRuntime(
            port,
            SafeHeatingProfile(21, 0.3, 0.1, SENSOR),
            minimum_on_time=minimum_on,
            minimum_off_time=minimum_off,
        )

    return create


def test_fatal_quarantines_generation_and_selects_safe_heating_with_valid_evidence():
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock)
    stale_port = supervisor.normal_port()
    supervisor.update_trusted_evidence(evidence())

    supervisor.report_fatal(ValueError("details stay in logs"))

    assert supervisor.state.failsafe_mode is OperatingMode.SAFE_HEATING
    assert supervisor.state.command_authority.value == "failsafe"
    with pytest.raises(CommandAuthorityError):
        stale_port.execute(command())
    supervisor.failsafe_port().execute(command(HeatingAction.DISABLE_HEATING))
    assert [item.action for item in source.commands] == [HeatingAction.DISABLE_HEATING]


def test_scheduled_fatal_stops_owned_runtime_and_normalizes_diagnostics_without_message():
    supervisor = RuntimeSupervisor(Source(), Clock())

    class Runtime:
        stopped = False

        def stop(self):
            self.stopped = True

    runtime = Runtime()
    supervisor.attach_normal_runtime(runtime)
    supervisor.scheduled_failure_sink().report(ScheduledRuntimeFailure(NOW, ValueError("secret detail")))

    diagnostics = supervisor.diagnostics()
    assert runtime.stopped is True
    assert diagnostics.last_fatal_cause_code == "invalid_runtime_state"
    assert "secret detail" not in repr(diagnostics)


def test_fatal_without_trusted_evidence_selects_emergency_off():
    supervisor = RuntimeSupervisor(Source(), Clock())
    supervisor.report_fatal(RuntimeError("fatal"))
    assert supervisor.state.failsafe_mode is OperatingMode.EMERGENCY_OFF


def test_restart_budget_is_rate_limited_exhausts_and_explicit_reset_reopens_campaign():
    clock = Clock()
    supervisor = RuntimeSupervisor(
        Source(),
        clock,
        restart_policy=RestartPolicy(attempt_limit=2, retry_interval=timedelta(minutes=5)),
    )
    supervisor.report_fatal(RuntimeError("fatal"))
    clock.current += timedelta(minutes=5)

    def factory(port, handover):
        raise RuntimeError("same fatal")

    assert supervisor.request_restart(factory) is None
    assert supervisor.state.restart_attempt_count == 1
    assert supervisor.request_restart(factory) is None
    clock.current += timedelta(minutes=5)
    assert supervisor.request_restart(factory) is None
    assert supervisor.state.phase is SupervisorPhase.RESTART_EXHAUSTED
    assert supervisor.state.restart_budget_exhausted is True

    supervisor.reset_restart_campaign()
    assert supervisor.state.restart_attempt_count == 0
    assert supervisor.state.restart_budget_exhausted is False


def test_successful_restart_handover_restores_only_normal_authority():
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock)
    old_normal = supervisor.normal_port()
    supervisor.report_fatal(RuntimeError("fatal"))
    old_failsafe = supervisor.failsafe_port()
    clock.current += timedelta(minutes=5)

    candidate = supervisor.request_restart(lambda port, handover: port)

    assert candidate is not None
    assert supervisor.state.phase is SupervisorPhase.NORMAL
    with pytest.raises(CommandAuthorityError):
        old_normal.execute(command())
    with pytest.raises(CommandAuthorityError):
        old_failsafe.execute(command())
    candidate.execute(command())
    assert [item.action for item in source.commands] == [HeatingAction.ENABLE_HEATING]


def test_failsafe_uses_shared_source_protection_and_manual_recovery_is_bounded():
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock)
    supervisor.report_fatal(RuntimeError("fatal"))
    runtime = FailsafeRuntime(
        supervisor.failsafe_port(),
        SafeHeatingProfile(21, 0.3, 0.1, SENSOR),
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )

    emergency = runtime.evaluate(now=NOW, evidence=None)
    manual = runtime.evaluate(now=NOW + timedelta(minutes=1), evidence=None, manual_recovery=True)
    supervisor.activate_manual_recovery()

    assert emergency.mode is OperatingMode.EMERGENCY_OFF
    assert manual.mode is OperatingMode.MANUAL_RECOVERY_HEAT
    assert manual.dispatched is False
    assert manual.next_evaluation_at == NOW + timedelta(minutes=5)
    assert supervisor.state.manual_recovery_deadline == NOW + timedelta(hours=2)


def test_fatal_automatically_drives_emergency_off_and_installs_one_restart_callback():
    source, clock, scheduler = Source(), Clock(), Scheduler()

    def failsafe_factory(port):
        return FailsafeRuntime(
            port,
            SafeHeatingProfile(21, 0.3, 0.1, SENSOR),
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        )

    attempts = []

    def restart(port, handover):
        attempts.append(handover)
        raise RuntimeError("restart failed")

    supervisor = RuntimeSupervisor(
        source, clock, scheduler=scheduler, failsafe_factory=failsafe_factory, restart_factory=restart
    )
    supervisor.report_fatal(RuntimeError("fatal"))

    assert [item.action for item in source.commands] == [HeatingAction.DISABLE_HEATING]
    assert len([task for task in scheduler.tasks if not task.cancelled]) == 1
    task = scheduler.tasks[-1]
    task.invoke()
    assert attempts == []
    clock.current = task.when
    task.invoke()
    assert len(attempts) == 1
    assert supervisor.state.restart_attempt_count == 1


def test_manual_expiry_reevaluates_safe_heating_and_stale_activation_is_ignored():
    source, clock, scheduler = Source(), Clock(), Scheduler()

    def failsafe_factory(port):
        return FailsafeRuntime(
            port,
            SafeHeatingProfile(21, 0.3, 0.1, SENSOR),
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        )

    supervisor = RuntimeSupervisor(source, clock, scheduler=scheduler, failsafe_factory=failsafe_factory)
    supervisor.update_trusted_evidence(evidence())
    supervisor.report_fatal(RuntimeError("fatal"))
    supervisor.activate_manual_recovery()
    old = scheduler.tasks[-1]
    clock.current += timedelta(minutes=1)
    supervisor.activate_manual_recovery()
    old.invoke()
    assert supervisor.state.failsafe_mode is OperatingMode.MANUAL_RECOVERY_HEAT
    current = scheduler.tasks[-1]
    clock.current = current.when
    current.invoke()
    assert supervisor.state.failsafe_mode is OperatingMode.SAFE_HEATING


def test_fatal_automatically_drives_safe_heat_and_handover_receives_truthful_state():
    source, clock = Source(), Clock()

    def failsafe_factory(port):
        return FailsafeRuntime(
            port,
            SafeHeatingProfile(21, 0.3, 0.1, SENSOR),
            minimum_on_time=timedelta(minutes=10),
            minimum_off_time=timedelta(minutes=5),
        )

    supervisor = RuntimeSupervisor(source, clock, failsafe_factory=failsafe_factory)
    supervisor.update_trusted_evidence(evidence(19))
    supervisor.report_fatal(RuntimeError("fatal"))
    captured = []

    def candidate(port, handover):
        captured.append(handover)
        return port

    clock.current += timedelta(minutes=5)
    normal_port = supervisor.request_restart(candidate)

    assert [item.action for item in source.commands] == [HeatingAction.ENABLE_HEATING]
    assert captured[0].reported_source is None
    assert captured[0].source_control_state.last_successful_enable_dispatch == NOW
    assert normal_port is not None
    with pytest.raises(CommandAuthorityError):
        supervisor.failsafe_port().execute(command())


def test_failed_failsafe_dispatch_is_recorded_and_does_not_prevent_restart_scheduling():
    source, clock, scheduler = FailingSource(), Clock(), Scheduler()
    supervisor = RuntimeSupervisor(
        source,
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
        restart_factory=lambda port, handover: port,
    )

    supervisor.report_fatal(RuntimeError("normal failed"))

    assert supervisor.state.fatal_cause_code == "failsafe_dispatch_failed"
    assert supervisor._failsafe.source_control_state.last_command_outcome is SourceCommandOutcome.FAILED
    assert len(scheduler.tasks) == 1
    supervisor.update_trusted_evidence(evidence(19))
    assert len(source.commands) == 2
    assert supervisor._failsafe.source_control_state.last_command_outcome is SourceCommandOutcome.FAILED


def test_restart_callbacks_exhaust_after_three_attempts_without_a_tight_loop():
    clock, scheduler, attempts = Clock(), Scheduler(), []

    def restart(port, handover):
        attempts.append(clock.now())
        raise RuntimeError("candidate startup failed")

    supervisor = RuntimeSupervisor(
        Source(),
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
        restart_factory=restart,
    )
    supervisor.report_fatal(RuntimeError("normal failed"))

    for expected_attempt in range(1, 4):
        task = scheduler.tasks[-1]
        clock.current = task.when
        task.invoke()
        assert supervisor.state.restart_attempt_count == expected_attempt

    assert attempts == [NOW + timedelta(minutes=5 * attempt) for attempt in range(1, 4)]
    assert supervisor.state.phase is SupervisorPhase.RESTART_EXHAUSTED
    assert supervisor.state.restart_budget_exhausted is True
    assert supervisor._restart_handle is None
    assert len(scheduler.tasks) == 3


def test_fatal_failsafe_restart_lifecycle_is_ordered_correlated_and_redacted():
    clock = Clock()
    recorder = OperationalEventRecorder()
    supervisor = RuntimeSupervisor(
        Source(),
        clock,
        operational_event_recorder=recorder,
        failsafe_factory=failsafe_factory(),
    )

    supervisor.report_fatal(RuntimeError("secret runtime details"))
    clock.current += timedelta(minutes=5)
    supervisor.request_restart(lambda port, handover: port)

    events = recorder.stream.snapshot().events
    codes = [event.event_code for event in events]
    assert codes == [
        OperationalEventCode.RUNTIME_FATAL,
        OperationalEventCode.COMMAND_AUTHORITY_CHANGED,
        OperationalEventCode.FAILSAFE_ENTERED,
        OperationalEventCode.SOURCE_DISABLE_REQUESTED,
        OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
        OperationalEventCode.RESTART_ATTEMPT_STARTED,
        OperationalEventCode.COMMAND_AUTHORITY_CHANGED,
        OperationalEventCode.FAILSAFE_EXITED,
        OperationalEventCode.RUNTIME_RECOVERED,
    ]
    lifecycle_events = [event for event in events if event.category.value in {"runtime", "supervision"}]
    assert {event.correlation_id for event in lifecycle_events} == {"supervision:00000002"}
    assert "secret runtime details" not in repr(events)


def test_restart_failures_and_exhaustion_keep_one_supervision_campaign_correlation():
    clock, scheduler = Clock(), Scheduler()
    recorder = OperationalEventRecorder()

    def fail_restart(port, handover):
        raise RuntimeError("candidate failed")

    supervisor = RuntimeSupervisor(
        Source(),
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
        restart_factory=fail_restart,
        operational_event_recorder=recorder,
    )
    supervisor.report_fatal(RuntimeError("normal failed"))
    for _ in range(3):
        task = scheduler.tasks[-1]
        clock.current = task.when
        task.invoke()

    campaign_events = [
        event for event in recorder.stream.snapshot().events if event.category.value in {"runtime", "supervision"}
    ]
    assert OperationalEventCode.RESTART_BUDGET_EXHAUSTED in {event.event_code for event in campaign_events}
    assert {event.correlation_id for event in campaign_events} == {"supervision:00000002"}


def test_second_independent_fatal_campaign_gets_a_new_correlation():
    clock = Clock()
    recorder = OperationalEventRecorder()
    supervisor = RuntimeSupervisor(
        Source(),
        clock,
        failsafe_factory=failsafe_factory(),
        operational_event_recorder=recorder,
    )

    supervisor.report_fatal(RuntimeError("first"))
    clock.current += timedelta(minutes=5)
    supervisor.request_restart(lambda port, handover: port)
    supervisor.report_fatal(RuntimeError("second"))

    fatal_events = [
        event for event in recorder.stream.snapshot().events if event.event_code is OperationalEventCode.RUNTIME_FATAL
    ]
    assert [event.correlation_id for event in fatal_events] == [
        "supervision:00000002",
        "supervision:00000003",
    ]


@pytest.mark.parametrize(
    ("trusted_evidence", "expected_action"),
    (
        (evidence(19), HeatingAction.ENABLE_HEATING),
        (None, HeatingAction.DISABLE_HEATING),
    ),
)
def test_failsafe_command_request_and_dispatch_use_shared_stream(trusted_evidence, expected_action):
    recorder = OperationalEventRecorder()
    supervisor = RuntimeSupervisor(
        Source(),
        Clock(),
        failsafe_factory=failsafe_factory(),
        operational_event_recorder=recorder,
    )
    supervisor.update_trusted_evidence(trusted_evidence)

    supervisor.report_fatal(RuntimeError("normal failed"))

    events = recorder.stream.snapshot().events
    request_code = (
        OperationalEventCode.SOURCE_ENABLE_REQUESTED
        if expected_action is HeatingAction.ENABLE_HEATING
        else OperationalEventCode.SOURCE_DISABLE_REQUESTED
    )
    command_events = [
        event
        for event in events
        if event.event_code
        in {
            OperationalEventCode.SOURCE_ENABLE_REQUESTED,
            OperationalEventCode.SOURCE_DISABLE_REQUESTED,
            OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
            OperationalEventCode.SOURCE_COMMAND_FAILED,
        }
    ]
    assert supervisor.operational_event_stream is recorder.stream
    assert [event.event_code for event in command_events] == [
        request_code,
        OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
    ]
    assert {event.requested_command for event in command_events} == {expected_action.value}
    assert len({event.correlation_id for event in command_events}) == 1
    assert {event.activity_id for event in command_events} == {"supervision:00000002"}
    assert command_events[0].activity_id != command_events[0].correlation_id


def test_failsafe_command_failure_is_recorded_without_fabricating_dispatch():
    recorder = OperationalEventRecorder()
    supervisor = RuntimeSupervisor(
        FailingSource(),
        Clock(),
        failsafe_factory=failsafe_factory(),
        operational_event_recorder=recorder,
    )

    supervisor.report_fatal(RuntimeError("normal failed"))

    command_events = [event for event in recorder.stream.snapshot().events if event.category.value == "source_control"]
    assert [event.event_code for event in command_events] == [
        OperationalEventCode.SOURCE_DISABLE_REQUESTED,
        OperationalEventCode.SOURCE_COMMAND_FAILED,
    ]
    assert [event.command_outcome for event in command_events] == ["requested", "failed"]
    assert len({event.correlation_id for event in command_events}) == 1
    assert {event.activity_id for event in command_events} == {"supervision:00000002"}
    assert "source dispatch failed" not in repr(command_events)


def test_failsafe_event_recorder_failure_cannot_block_source_command():
    class FailingCommandRecorder(OperationalEventRecorder):
        def command_requested(self, *args, **kwargs):
            raise RuntimeError("event recording failed")

        def command_dispatched(self, *args, **kwargs):
            raise RuntimeError("event recording failed")

    source = Source()
    supervisor = RuntimeSupervisor(
        source,
        Clock(),
        failsafe_factory=failsafe_factory(),
        operational_event_recorder=FailingCommandRecorder(),
    )

    supervisor.report_fatal(RuntimeError("normal failed"))

    assert [item.action for item in source.commands] == [HeatingAction.DISABLE_HEATING]
    assert supervisor.state.command_authority.value == "failsafe"


def test_stale_restart_callbacks_cannot_cross_reset_or_successful_handover():
    source, clock, scheduler = Source(), Clock(), Scheduler()
    attempts = []

    def restart(port, handover):
        attempts.append(clock.now())
        return port

    supervisor = RuntimeSupervisor(
        source,
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
        restart_factory=restart,
    )
    supervisor.report_fatal(RuntimeError("normal failed"))
    old_campaign = scheduler.tasks[-1]
    supervisor.reset_restart_campaign()
    fresh_campaign = scheduler.tasks[-1]

    clock.current = fresh_campaign.when
    old_campaign.invoke()
    assert attempts == []
    fresh_campaign.invoke()
    assert len(attempts) == 1
    assert supervisor.state.phase is SupervisorPhase.NORMAL
    fresh_campaign.invoke()
    assert len(attempts) == 1


def test_candidate_cannot_dispatch_until_truthful_handover_is_complete():
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock, failsafe_factory=failsafe_factory())
    supervisor.report_fatal(RuntimeError("normal failed"))
    clock.current += timedelta(minutes=5)

    def candidate(port, handover):
        with pytest.raises(CommandAuthorityError):
            port.execute(command())
        assert handover.reported_source is None
        return port

    port = supervisor.request_restart(candidate)
    port.execute(command())

    assert [item.action for item in source.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


@pytest.mark.parametrize(
    ("reported_state", "trusted", "expected_action"),
    [
        (ReportedSourceState.ENABLED, True, HeatingAction.ENABLE_HEATING),
        (ReportedSourceState.DISABLED, False, HeatingAction.DISABLE_HEATING),
    ],
)
def test_reported_state_and_matching_failsafe_intent_survive_handover_without_duplicate_command(
    reported_state,
    trusted,
    expected_action,
):
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock, failsafe_factory=failsafe_factory())
    reported = ReportedSourceEvidence(reported_state, NOW, NOW)
    supervisor.ingest_reported_source(reported)
    if trusted:
        supervisor.update_trusted_evidence(evidence(19))
    supervisor.report_fatal(RuntimeError("normal failed"))
    clock.current += timedelta(minutes=5)
    captured = []

    supervisor.request_restart(lambda port, handover: captured.append(handover) or port)

    assert captured[0].reported_source == reported
    assert captured[0].source_control_state.last_dispatched_command is expected_action
    assert [item.action for item in source.commands] == [expected_action]


def test_handover_preserves_minimum_on_and_off_protection_boundaries():
    for trusted, requested, expected_boundary in (
        (True, HeatingAction.DISABLE_HEATING, "minimum_on"),
        (False, HeatingAction.ENABLE_HEATING, "minimum_off"),
    ):
        source, clock = Source(), Clock()
        supervisor = RuntimeSupervisor(
            source,
            clock,
            failsafe_factory=failsafe_factory(
                minimum_on=timedelta(minutes=10),
                minimum_off=timedelta(minutes=10),
            ),
        )
        if trusted:
            supervisor.update_trusted_evidence(evidence(19))
        supervisor.report_fatal(RuntimeError("normal failed"))
        clock.current += timedelta(minutes=5)
        assessments = []

        def candidate(port, handover):
            policy = SourceControlPolicy(
                minimum_on_time=timedelta(minutes=10),
                minimum_off_time=timedelta(minutes=10),
            )
            assessments.append(
                policy.evaluate(
                    desired_command=requested,
                    now=clock.now(),
                    current_state=handover.source_control_state,
                )
            )
            return port

        supervisor.request_restart(candidate)

        assert assessments[0].outcome is SourceControlOutcome.DEFER
        assert assessments[0].active_lockout.value == expected_boundary


def test_unknown_transition_history_and_reconciliation_state_transfer_without_inference():
    source, clock = Source(), Clock()
    supervisor = RuntimeSupervisor(source, clock, failsafe_factory=failsafe_factory())
    reported = ReportedSourceEvidence(ReportedSourceState.UNKNOWN, NOW)
    supervisor.ingest_reported_source(reported)
    supervisor.report_fatal(RuntimeError("normal failed"))
    reconciliation = SourceReconciliationState(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=None,
        reported=reported,
        status=SourceReconciliationStatus.REPORTED_INDETERMINATE,
        reason=SourceReconciliationReason.REPORTED_STATE_UNKNOWN,
        drift_detected_at=None,
        conservative_hold_deadline=None,
        corrective_intent=None,
        next_reevaluation_at=None,
        last_evaluated_at=NOW,
    )
    supervisor._failsafe.source_reconciliation_state = reconciliation
    clock.current += timedelta(minutes=5)
    captured = []

    supervisor.request_restart(lambda port, handover: captured.append(handover) or port)

    handover = captured[0]
    assert handover.reported_source == reported
    assert handover.reported_source.transition_at is None
    assert handover.source_ownership is SourceOwnership.CONTROLEL_OWNED
    assert handover.reconciliation_state == reconciliation
    assert handover.source_control_state.last_successful_enable_dispatch is None


def test_manual_recovery_expiry_without_evidence_automatically_disables_source():
    source, clock, scheduler = Source(), Clock(), Scheduler()
    supervisor = RuntimeSupervisor(
        source,
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
    )
    supervisor.report_fatal(RuntimeError("normal failed"))
    supervisor.activate_manual_recovery()
    expiry = scheduler.tasks[-1]

    clock.current = expiry.when
    expiry.invoke()

    assert supervisor.state.failsafe_mode is OperatingMode.EMERGENCY_OFF
    assert supervisor.state.manual_recovery_deadline is None
    assert [item.action for item in source.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_successful_normal_restart_invalidates_manual_recovery_expiry():
    source, clock, scheduler = Source(), Clock(), Scheduler()
    supervisor = RuntimeSupervisor(
        source,
        clock,
        scheduler=scheduler,
        failsafe_factory=failsafe_factory(),
    )
    supervisor.report_fatal(RuntimeError("normal failed"))
    supervisor.activate_manual_recovery()
    expiry = scheduler.tasks[-1]
    clock.current += timedelta(minutes=5)
    supervisor.request_restart(lambda port, handover: port)

    clock.current = expiry.when
    expiry.invoke()

    assert supervisor.state.phase is SupervisorPhase.NORMAL
    assert supervisor.state.manual_recovery_deadline is None
    assert [item.action for item in source.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]

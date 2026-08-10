import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime as CoreControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.shadow_heating_performance_monitor import ShadowHeatingPerformanceMonitor
from controlel.application.services.source_control_policy import SourceControlPolicy
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatSourceObservation,
    ObservedValue,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel import ControlRuntime as HomeAssistantControlRuntime
from custom_components.controlel.config import (
    DiagnosticConfiguration,
    HomeAssistantSensorBinding,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import HomeAssistantScheduledFailureSink
from custom_components.controlel.host import (
    HomeAssistantControlelHost,
    _source_control_snapshot_changes,
)
from custom_components.controlel.measurement_ingestion import (
    HomeAssistantMeasurementMapper,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def _disabled_source_state(policy: SourceControlPolicy):
    initial = policy.initial_state(NOW)
    assessment = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW,
        current_state=initial,
    )
    return policy.record_dispatched(
        assessment,
        dispatched_at=NOW,
        safety_command=False,
    )


def test_core_0_4_precise_passive_boundary_has_no_active_lockout_claim() -> None:
    boundary = NOW + timedelta(minutes=5)
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    state = _disabled_source_state(policy)

    changes = _source_control_snapshot_changes(state)

    assert changes["source_control_state"].value == "heating_not_requested"
    assert changes["earliest_next_enable_time"] == boundary
    assert changes["active_lockout_type"] is None
    assert changes["active_lockout_deadline"] is None
    assert changes["deferred_command"] is None
    assert changes["last_successful_disable_dispatch"] == NOW


def test_core_0_4_precise_deferred_enable_and_cancellation_are_projected() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    passive = _disabled_source_state(policy)
    requested_at = NOW + timedelta(seconds=1)
    deferred = policy.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=requested_at,
        current_state=passive,
    ).state

    changes = _source_control_snapshot_changes(deferred)

    assert changes["source_control_state"].value == "heating_requested_waiting_minimum_off"
    assert changes["active_lockout_type"].value == "minimum_off"
    assert changes["active_lockout_deadline"] == passive.earliest_next_enable_time
    assert changes["deferred_command"] == "enable_heating"
    assert changes["deferred_since"] == requested_at
    assert changes["deferred_deadline"] == passive.earliest_next_enable_time

    cancelled = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at + timedelta(seconds=1),
        current_state=deferred,
    ).state
    cancelled_changes = _source_control_snapshot_changes(cancelled)

    assert cancelled_changes["source_control_state"].value == "heating_not_requested"
    assert cancelled_changes["earliest_next_enable_time"] == passive.earliest_next_enable_time
    assert cancelled_changes["active_lockout_type"] is None
    assert cancelled_changes["active_lockout_deadline"] is None
    assert cancelled_changes["deferred_command"] is None
    assert cancelled_changes["deferred_deadline"] is None


def test_core_0_4_precise_deferred_disable_and_safety_bypass_are_projected() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    initial = policy.initial_state(NOW)
    enable = policy.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW,
        current_state=initial,
    )
    enabled = policy.record_dispatched(enable, dispatched_at=NOW, safety_command=False)
    requested_at = NOW + timedelta(seconds=1)
    deferred = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at,
        current_state=enabled,
    ).state

    changes = _source_control_snapshot_changes(deferred)

    assert changes["source_control_state"].value == "heating_not_requested_waiting_minimum_on"
    assert changes["active_lockout_type"].value == "minimum_on"
    assert changes["active_lockout_deadline"] == enabled.earliest_next_disable_time
    assert changes["deferred_command"] == "disable_heating"
    assert changes["last_successful_enable_dispatch"] == NOW

    safety = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at,
        current_state=enabled,
        safety_command=True,
    )
    safety_state = policy.record_dispatched(
        safety,
        dispatched_at=requested_at,
        safety_command=True,
    )
    safety_changes = _source_control_snapshot_changes(safety_state)

    assert safety_changes["source_control_state"].value == "safety_override"
    assert safety_changes["safety_bypassed_lockout"] is True
    assert safety_changes["active_lockout_type"] is None
    assert safety_changes["deferred_command"] is None
    assert safety_changes["last_successful_enable_dispatch"] == NOW
    assert safety_changes["last_successful_disable_dispatch"] == requested_at


def host_config():
    return SimpleNamespace(
        zone_name="Room",
        zone_id=ZoneId("room"),
        sensor_name="Room temperature",
        sensor_id=SensorId("room_temperature"),
        temperature_entity_id="sensor.room",
        target_temperature=Temperature(21),
        heating_turn_on_differential=0.3,
        heating_turn_off_differential=0.1,
        heat_demand_confirmation_duration=timedelta(minutes=2),
        primary_measurement_max_age=timedelta(minutes=5),
        indeterminate_grace_period=timedelta(minutes=1),
        minimum_heating_on_time=timedelta(minutes=10),
        minimum_heating_off_time=timedelta(minutes=5),
        indeterminate_timeout_action=SimpleNamespace(value="disable_heating"),
        diagnostic_configuration=DiagnosticConfiguration(
            profile="basic",
            debug_duration=timedelta(hours=1),
            configured_debug_duration=timedelta(hours=1),
            profile_before_debug="detailed",
        ),
    )


@dataclass
class FakeState:
    state: str
    last_updated: datetime
    entity_id: str = "sensor.room"

    @property
    def attributes(self):
        return {"unit_of_measurement": "°C"}


class FakeHass:
    def async_create_task(self, target, name=None):
        return asyncio.create_task(target, name=name)


class FakeRuntime:
    def __init__(self):
        self.operations: list[tuple[str, object]] = []
        self.worker_threads: list[int] = []
        self.process_entered = Event()
        self.process_release = Event()
        self.process_release.set()
        self.start_entered = Event()
        self.start_release = Event()
        self.start_release.set()

    def process_temperature(self, measurement):
        self.worker_threads.append(get_ident())
        self.operations.append(("measurement", measurement.value.value))
        self.process_entered.set()
        self.process_release.wait()
        return RuntimeProcessingResult(
            status=RuntimeProcessingStatus.NO_DECISION,
            reason=TemperatureNoDecisionReason.SECONDARY_MEASUREMENT,
        )

    def start(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("start", None))
        self.start_entered.set()
        self.start_release.wait()
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def reevaluate_heat_demand(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("reevaluate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def mark_measurement_indeterminate(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("indeterminate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def stop(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("stop", None))


def completed_shadow_episode(offset: int = 0) -> HeatingEpisode:
    started_at = NOW + timedelta(minutes=offset)
    ended_at = started_at + timedelta(minutes=1)
    samples = tuple(
        HeatingEpisodeSample(
            captured_at=timestamp,
            zone_temperature=ObservedValue.valid(temperature, timestamp),
            target_temperature=21.0,
            actuator_observations=(),
            source_observation=HeatSourceObservation(captured_at=timestamp),
        )
        for timestamp, temperature in ((started_at, 19.0), (ended_at, 19.5))
    )
    return HeatingEpisode(
        zone_id=ZoneId("room"),
        started_at=started_at,
        ended_at=ended_at,
        termination_reason=HeatingEpisodeTerminationReason.DEMAND_CLEARED,
        initial_target_temperature=21.0,
        current_target_temperature=21.0,
        initial_temperature=19.0,
        current_temperature=19.5,
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=started_at),
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED, changed_at=ended_at),
        ),
        total_sample_count=2,
        samples_truncated=False,
        samples=samples,
    )


class ShadowAssessmentRuntime(FakeRuntime):
    def __init__(self, monitor: ShadowHeatingPerformanceMonitor) -> None:
        super().__init__()
        self.heating_performance_monitor = monitor
        self._episode_offset = 0

    def process_temperature(self, measurement):
        result = super().process_temperature(measurement)
        self.heating_performance_monitor.submit_episode(completed_shadow_episode(self._episode_offset))
        self._episode_offset += 2
        return result


class BlockingShadowAssessor:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self._delegate = HeatingPerformanceAssessor()

    def assess(self, episode):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("shadow assessment was not released")
        return self._delegate.assess(episode)


class FailingShadowAssessor:
    def assess(self, episode):
        raise RuntimeError(f"shadow failure for {episode.zone_id.value}")


def create_shadow_test_host(runtime: FakeRuntime) -> HomeAssistantControlelHost:
    hass = FakeHass()
    failure_sink = HomeAssistantScheduledFailureSink(
        hass,
        HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
        "entry",
        logging.getLogger(__name__),
        create_issue=lambda *args, **kwargs: None,
        delete_issue=lambda *args: None,
        warning_severity="warning",
        error_severity="error",
    )
    host = HomeAssistantControlelHost(
        hass=hass,
        runtime=runtime,
        executor=HomeAssistantRuntimeExecutor(),
        measurement_mapper=HomeAssistantMeasurementMapper(
            HomeAssistantSensorBinding("sensor.room", SensorId("room_temperature"))
        ),
        failure_sink=failure_sink,
        config=host_config(),
        core_version="0.5.0",
        logger=logging.getLogger(__name__),
        state_subscriber=lambda hass, entity_id, listener: lambda: None,
        state_getter=lambda entity_id: None,
        shutdown_subscriber=lambda hass, listener: lambda: None,
        interval_subscriber=lambda hass, listener, interval: lambda: None,
    )
    failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
    return host


def test_home_assistant_runtime_start_does_not_evaluate_empty_core_state(monkeypatch):
    def fail_if_called(runtime):
        raise AssertionError("core startup evaluation must not run before a real HA state")

    monkeypatch.setattr(CoreControlRuntime, "start", fail_if_called)
    runtime = object.__new__(HomeAssistantControlRuntime)

    assert runtime.start() is None


def test_production_host_drains_completed_episode_after_control_returns() -> None:
    async def scenario():
        monitor = ShadowHeatingPerformanceMonitor()
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        result = await host.async_process_state(FakeState("19", NOW))
        for _ in range(100):
            if monitor.assessments:
                break
            await asyncio.sleep(0.001)

        await host.async_stop()
        return result, monitor.assessments, len(host._shadow_assessment_tasks)

    result, assessments, remaining_shadow_tasks = asyncio.run(scenario())

    assert result is not None
    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert len(assessments) == 1
    assert assessments[0].zone_id == ZoneId("room")
    assert remaining_shadow_tasks == 0


def test_blocked_production_assessor_does_not_block_next_control_event() -> None:
    async def scenario():
        assessor = BlockingShadowAssessor()
        monitor = ShadowHeatingPerformanceMonitor(assessor=assessor)
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        first = await host.async_process_state(FakeState("19", NOW))
        while not assessor.entered.is_set():
            await asyncio.sleep(0)
        second = await asyncio.wait_for(
            host.async_process_state(FakeState("19.5", NOW + timedelta(seconds=1))),
            timeout=1,
        )
        operations_before_release = tuple(runtime.operations)
        assessor.release.set()
        await host.async_stop()
        return first, second, operations_before_release, monitor.assessments

    first, second, operations, assessments = asyncio.run(scenario())

    assert first is not None and second is not None
    assert [operation[0] for operation in operations] == ["start", "measurement", "measurement"]
    assert len(assessments) == 2


def test_production_assessor_failure_cannot_change_completed_control_result() -> None:
    async def scenario():
        monitor = ShadowHeatingPerformanceMonitor(assessor=FailingShadowAssessor())
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        result = await host.async_process_state(FakeState("19", NOW))
        for _ in range(100):
            if monitor.errors:
                break
            await asyncio.sleep(0.001)
        await host.async_stop()
        return result, tuple(runtime.operations), monitor.errors

    result, operations, errors = asyncio.run(scenario())

    assert result is not None
    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert operations[:2] == (("start", None), ("measurement", 19.0))
    assert errors == {ZoneId("room"): "RuntimeError: shadow failure for room"}


def test_start_precedes_snapshot_buffer_drain_live_events_and_stop():
    async def scenario():
        event_loop_thread = get_ident()
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        runtime.process_release.clear()
        runtime.start_release.clear()
        listener_holder = {}
        unsubscribed: list[None] = []

        def subscribe(hass, entity_id, listener):
            listener_holder["listener"] = listener
            return lambda: unsubscribed.append(None)

        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=subscribe,
            state_getter=lambda entity_id: FakeState("19", NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)

        initialize = asyncio.create_task(host.async_initialize())
        while not runtime.start_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("20", NOW.replace(second=1)))
        runtime.start_release.set()

        while not runtime.process_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("21", NOW.replace(second=2)))
        runtime.process_release.set()
        await initialize

        listener_holder["listener"](FakeState("22", NOW.replace(second=3)))
        while len(runtime.operations) < 5:
            await asyncio.sleep(0)

        duplicate = FakeState("22", NOW.replace(second=3))
        listener_holder["listener"](duplicate)
        await asyncio.sleep(0.01)

        await host.async_stop()
        await host.async_stop()
        listener_holder["listener"](FakeState("23", NOW.replace(second=4)))
        await asyncio.sleep(0)
        return (
            runtime,
            host,
            unsubscribed,
            event_loop_thread,
        )

    runtime, host, unsubscribed, event_loop_thread = asyncio.run(scenario())

    assert runtime.operations == [
        ("start", None),
        ("measurement", 19.0),
        ("measurement", 20.0),
        ("measurement", 21.0),
        ("measurement", 22.0),
        ("stop", None),
    ]
    assert len(set(runtime.worker_threads)) == 1
    assert runtime.worker_threads[0] != event_loop_thread
    assert unsubscribed == [None]
    assert host.accepting is False
    assert host.stopped is True


@pytest.mark.parametrize("state_value", ["unavailable", "unknown"])
def test_start_precedes_explicit_indeterminate_snapshot_initialization(state_value):
    async def scenario():
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=lambda hass, entity_id, listener: lambda: None,
            state_getter=lambda entity_id: FakeState(state_value, NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
        await host.async_initialize()
        await host.async_stop()
        return runtime.operations

    assert asyncio.run(scenario()) == [
        ("start", None),
        ("indeterminate", None),
        ("stop", None),
    ]


def test_absent_snapshot_waits_for_one_buffered_real_state_without_indeterminate():
    async def scenario():
        hass = FakeHass()
        runtime = FakeRuntime()
        runtime.start_release.clear()
        listener_holder = {}

        def subscribe(hass, entity_id, listener):
            listener_holder["listener"] = listener
            return lambda: None

        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=HomeAssistantRuntimeExecutor(),
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding("sensor.room", SensorId("room_temperature"))
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=subscribe,
            state_getter=lambda entity_id: None,
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)

        initialize = asyncio.create_task(host.async_initialize())
        while not runtime.start_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("20", NOW))
        runtime.start_release.set()
        await initialize
        await host.async_stop()
        return runtime.operations

    assert asyncio.run(scenario()) == [
        ("start", None),
        ("measurement", 20.0),
        ("stop", None),
    ]

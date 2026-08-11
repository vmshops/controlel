from datetime import UTC, datetime, timedelta
from inspect import signature
from threading import Event, Thread

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.runtime_processing_result import RuntimeProcessingStatus
from controlel.application.services.heating_diagnostics_projector import HeatingDiagnosticsProjector
from controlel.application.services.heating_episode_observer import HeatingEpisodeObserver
from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.shadow_heating_performance_monitor import ShadowHeatingPerformanceMonitor
from controlel.application.services.source_control_policy import SourceControlOutcome
from controlel.application.services.zone_heat_delivery_controller import ZoneHeatDeliveryController
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import ZoneHeatDemandInput, ZoneHeatDemandInputReason
from controlel.domain.entities.zone import Zone
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorConfiguration,
    HeatDeliveryActuatorId,
    HeatDeliveryAssistPolicy,
    HeatDeliveryCapabilities,
    HeatDeliveryMode,
    HeatDeliveryOwnership,
    HeatingEpisodeTerminationReason,
    ObservationQuality,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NoOpScheduledTask:
    def cancel(self) -> None:
        pass


class NoOpScheduler:
    def schedule_at(self, when, callback):
        return NoOpScheduledTask()


class NoOpScheduledFailureSink:
    def report(self, failure) -> None:
        pass


class NoOpHeatSource:
    def __init__(self):
        self.commands: list[HeatSourceCommand] = []

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)


def create_runtime() -> tuple[ControlRuntime, NoOpHeatSource]:
    sensor_id = SensorId(value="living_room_temperature")
    zone_id = ZoneId(value="living_room")
    sensors = SensorRepository()
    sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name="Temperature"))
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=zone_id,
            primary_sensor_id=sensor_id,
            primary_measurement_max_age=timedelta(minutes=5),
            name="Living room",
            target_temperature=Temperature(22),
        )
    )
    port = NoOpHeatSource()
    return (
        ControlRuntime(
            sensors,
            zones,
            port,
            FixedClock(),
            NoOpScheduler(),
            NoOpScheduledFailureSink(),
            timedelta(0),
            timedelta(minutes=1),
            HeatingAction.DISABLE_HEATING,
        ),
        port,
    )


def test_control_runtime_processes_temperature_and_keeps_runtime_measurement():
    runtime, port = create_runtime()
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
        timestamp=NOW,
    )

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert runtime.state_store.get_latest(measurement.sensor_id) is measurement
    assert port.commands == [result.heat_demand_evaluation.command]


def test_runtime_stop_bounds_episode_and_fresh_runtime_does_not_restore_it() -> None:
    runtime, port = create_runtime()
    runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="living_room_temperature"),
            value=Temperature(19),
            timestamp=NOW,
        )
    )

    runtime.stop()
    reloaded_runtime, _ = create_runtime()

    assert runtime.heating_episode_observer.active_episodes == ()
    assert (
        runtime.heating_episode_observer.completed_episodes[0].termination_reason
        is HeatingEpisodeTerminationReason.RUNTIME_STOPPED
    )
    assert reloaded_runtime.heating_episode_observer.active_episodes == ()
    assert reloaded_runtime.heating_episode_observer.completed_episodes == ()
    assert len(port.commands) == 1


def test_control_runtime_constructor_uses_shared_source_contract_only():
    parameters = signature(ControlRuntime).parameters

    assert list(parameters) == [
        "sensor_repository",
        "zone_repository",
        "heat_source_port",
        "clock",
        "scheduler",
        "scheduled_failure_sink",
        "max_future_skew",
        "indeterminate_grace_period",
        "indeterminate_timeout_action",
        "heating_turn_on_differential",
        "heating_turn_off_differential",
        "heat_demand_confirmation_duration",
        "minimum_heating_on_time",
        "minimum_heating_off_time",
        "demand_arbitrator",
        "heat_delivery_controller",
    ]
    assert "actuator_routes" not in parameters
    assert "actuator" not in parameters
    assert "target_temperature" not in parameters


class RecordingHeatDeliveryPort:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command) -> None:
        self.commands.append(command)


class SelectivelyFailingObserver(HeatingEpisodeObserver):
    def __init__(self, failed_zone_id: ZoneId) -> None:
        super().__init__()
        self.failed_zone_id = failed_zone_id
        self.called_zone_ids: list[ZoneId] = []

    def observe(self, **kwargs):
        zone_id = kwargs["zone_id"]
        self.called_zone_ids.append(zone_id)
        if zone_id == self.failed_zone_id:
            raise RuntimeError("observation failed")
        return super().observe(**kwargs)


class FailingPerformanceAssessor:
    def assess(self, episode):
        raise RuntimeError(f"assessment failed for {episode.zone_id.value}")


class FailingDiagnosticsProjector:
    def project(self, **kwargs):
        raise RuntimeError("diagnostic projection failed")


class BlockingPerformanceAssessor:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self._delegate = HeatingPerformanceAssessor()

    def assess(self, episode):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("assessment was not released")
        return self._delegate.assess(episode)


def create_heat_delivery_runtime(
    *,
    indeterminate_grace_period: timedelta = timedelta(minutes=1),
    minimum_heating_on_time: timedelta = timedelta(0),
    minimum_heating_off_time: timedelta = timedelta(0),
) -> tuple[
    ControlRuntime,
    NoOpHeatSource,
    RecordingHeatDeliveryPort,
    SensorId,
    ZoneId,
]:
    sensor_id = SensorId("bedroom_temperature")
    zone_id = ZoneId("bedroom")
    sensors = SensorRepository()
    sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name="Bedroom temperature"))
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=zone_id,
            primary_sensor_id=sensor_id,
            primary_measurement_max_age=timedelta(minutes=5),
            name="Bedroom",
            target_temperature=Temperature(22),
        )
    )
    source = NoOpHeatSource()
    actuator = HeatDeliveryActuatorId("bedroom_trv")
    delivery_port = RecordingHeatDeliveryPort()
    controller = ZoneHeatDeliveryController(
        (
            HeatDeliveryActuatorConfiguration(
                actuator_id=actuator,
                zone_id=zone_id,
                capabilities=HeatDeliveryCapabilities(can_set_target_temperature=True),
                mode=HeatDeliveryMode.SETPOINT_ASSIST,
                ownership=HeatDeliveryOwnership.CONTROLEL_OWNED,
                assist_policy=HeatDeliveryAssistPolicy.ALWAYS_ASSIST_WHILE_HEATING,
                assist_target_temperature=30,
            ),
        ),
        {actuator: delivery_port},
    )
    runtime = ControlRuntime(
        sensors,
        zones,
        source,
        FixedClock(),
        NoOpScheduler(),
        NoOpScheduledFailureSink(),
        timedelta(0),
        indeterminate_grace_period,
        HeatingAction.DISABLE_HEATING,
        minimum_heating_on_time=minimum_heating_on_time,
        minimum_heating_off_time=minimum_heating_off_time,
        heat_delivery_controller=controller,
    )
    return runtime, source, delivery_port, sensor_id, zone_id


def test_observer_exception_does_not_change_heating_control() -> None:
    runtime, source, delivery_port, sensor_id, zone_id = create_heat_delivery_runtime()
    observer = SelectivelyFailingObserver(zone_id)
    runtime.heating_episode_observer = observer

    result = runtime.process_temperature(Measurement(sensor_id=sensor_id, value=Temperature(20), timestamp=NOW))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert observer.called_zone_ids == [zone_id]
    assert runtime.heating_episode_observation_errors == {zone_id: "RuntimeError: observation failed"}
    assert runtime.heating_episode_observation_error == "bedroom: RuntimeError: observation failed"
    assert [command.value for command in delivery_port.commands] == [30]
    assert source.commands == [result.heat_demand_evaluation.command]
    assert result.heat_demand_evaluation.source_control_assessment is runtime.source_control_assessment
    assert runtime.source_control_assessment.outcome is SourceControlOutcome.DISPATCH


def test_one_zone_observation_failure_does_not_skip_remaining_zones() -> None:
    runtime, source = create_runtime()
    failed_zone_id = ZoneId("living_room")
    remaining_zone_id = ZoneId("bedroom")
    runtime.zone_repository.add(
        Zone(
            zone_id=remaining_zone_id,
            primary_sensor_id=SensorId("bedroom_temperature"),
            primary_measurement_max_age=timedelta(minutes=5),
            name="Bedroom",
            target_temperature=Temperature(22),
        )
    )
    observer = SelectivelyFailingObserver(failed_zone_id)
    runtime.heating_episode_observer = observer
    zone_inputs = tuple(
        ZoneHeatDemandInput(
            zone_id=zone_id,
            demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
            reason=ZoneHeatDemandInputReason.ELIGIBLE,
            evidence=ZoneDemand(
                zone_id=zone_id,
                requires_heat=True,
                source_sensor_id=SensorId(f"{zone_id.value}_temperature"),
                observed_at=NOW,
            ),
        )
        for zone_id in (failed_zone_id, remaining_zone_id)
    )

    runtime._observe_heating_episodes(zone_inputs, captured_at=NOW)

    assert observer.called_zone_ids == [failed_zone_id, remaining_zone_id]
    assert runtime.heating_episode_observation_errors == {failed_zone_id: "RuntimeError: observation failed"}
    assert [episode.zone_id for episode in observer.active_episodes] == [remaining_zone_id]
    assert source.commands == []


def run_heat_delivery_cycle(runtime: ControlRuntime, sensor_id: SensorId):
    heating = runtime.process_temperature(Measurement(sensor_id=sensor_id, value=Temperature(20), timestamp=NOW))
    clearing = runtime.process_temperature(Measurement(sensor_id=sensor_id, value=Temperature(23), timestamp=NOW))
    return heating, clearing


def control_trace(runtime, source, delivery_port, evaluations):
    return (
        tuple(
            (
                evaluation.trigger,
                evaluation.status,
                evaluation.building_heat_demand,
                evaluation.safety_assessment,
                evaluation.next_evaluation_at,
                evaluation.hysteresis_assessment,
                evaluation.confirmation_assessment,
                evaluation.source_control_assessment,
                None if evaluation.command is None else (evaluation.command.command_type, evaluation.command.action),
            )
            for evaluation in evaluations
        ),
        tuple((command.command_type, command.action) for command in source.commands),
        tuple(
            (
                command.actuator_id,
                command.zone_id,
                command.kind,
                command.value,
                command.requested_at,
            )
            for command in delivery_port.commands
        ),
        runtime.source_control_state,
        runtime.zone_heat_demand_confirmation_states,
    )


def run_non_interference_scenario(
    *,
    monitor,
    temperatures,
    indeterminate_grace_period=timedelta(minutes=1),
    minimum_heating_on_time=timedelta(0),
    minimum_heating_off_time=timedelta(0),
    mark_indeterminate=False,
    reevaluate=False,
    diagnostics_projector=None,
):
    runtime, source, delivery_port, sensor_id, _ = create_heat_delivery_runtime(
        indeterminate_grace_period=indeterminate_grace_period,
        minimum_heating_on_time=minimum_heating_on_time,
        minimum_heating_off_time=minimum_heating_off_time,
    )
    runtime.heating_performance_monitor = monitor
    evaluations = []
    for temperature in temperatures:
        result = runtime.process_temperature(
            Measurement(sensor_id=sensor_id, value=Temperature(temperature), timestamp=NOW)
        )
        evaluations.append(result.heat_demand_evaluation)
        project_runtime_diagnostics(runtime, diagnostics_projector)
    if reevaluate:
        evaluations.append(runtime.reevaluate_heat_demand())
        project_runtime_diagnostics(runtime, diagnostics_projector)
    if mark_indeterminate:
        evaluations.append(runtime.mark_measurement_indeterminate())
        project_runtime_diagnostics(runtime, diagnostics_projector)
    return control_trace(runtime, source, delivery_port, evaluations)


def project_runtime_diagnostics(runtime, projector) -> None:
    if projector is None:
        return
    try:
        projector.project(
            zone_ids=tuple(zone.zone_id for zone in runtime.zone_repository.list_all()),
            active_episodes=runtime.heating_episode_observer.active_episodes,
            completed_episodes=runtime.heating_episode_observer.completed_episodes,
            monitor=runtime.heating_performance_monitor.diagnostic_snapshot(),
            observation_errors=tuple(runtime.heating_episode_observation_error_evidence.values()),
        )
    except Exception:
        pass


def test_shadow_assessment_enabled_disabled_and_failed_have_identical_commands() -> None:
    traces = []
    runtimes = []
    monitors = (
        ShadowHeatingPerformanceMonitor(enabled=True),
        ShadowHeatingPerformanceMonitor(enabled=False),
        ShadowHeatingPerformanceMonitor(assessor=FailingPerformanceAssessor()),
    )
    for monitor in monitors:
        runtime, source, delivery_port, sensor_id, _ = create_heat_delivery_runtime()
        runtime.heating_performance_monitor = monitor
        results = run_heat_delivery_cycle(runtime, sensor_id)
        traces.append(
            (
                tuple((command.command_type, command.action) for command in source.commands),
                tuple(
                    (
                        command.actuator_id,
                        command.zone_id,
                        command.kind,
                        command.value,
                        command.requested_at,
                    )
                    for command in delivery_port.commands
                ),
                tuple(result.status for result in results),
            )
        )
        runtimes.append(runtime)

    assert traces[0] == traces[1] == traces[2]
    assert monitors[0].pending_episode_count == 1
    assert monitors[1].pending_episode_count == 0
    assert monitors[2].pending_episode_count == 1
    for monitor in monitors:
        monitor.assess_pending()
    assert len(monitors[0].assessments) == 1
    assert monitors[1].assessments == ()
    assert monitors[2].errors == {ZoneId("bedroom"): "RuntimeError: assessment failed for bedroom"}
    assert all(runtime.heating_episode_observation_error is None for runtime in runtimes)


def test_shadow_assessment_enabled_and_disabled_have_identical_full_control_contracts() -> None:
    scenarios = (
        {"temperatures": (20, 23), "reevaluate": True},
        {
            "temperatures": (20, 23),
            "minimum_heating_on_time": timedelta(minutes=5),
        },
        {
            "temperatures": (23, 20),
            "minimum_heating_off_time": timedelta(minutes=5),
        },
        {
            "temperatures": (20,),
            "indeterminate_grace_period": timedelta(0),
            "minimum_heating_on_time": timedelta(minutes=5),
            "mark_indeterminate": True,
        },
    )

    for scenario in scenarios:
        enabled_trace = run_non_interference_scenario(
            monitor=ShadowHeatingPerformanceMonitor(enabled=True),
            diagnostics_projector=HeatingDiagnosticsProjector(),
            **scenario,
        )
        disabled_trace = run_non_interference_scenario(
            monitor=ShadowHeatingPerformanceMonitor(enabled=False),
            **scenario,
        )
        failed_trace = run_non_interference_scenario(
            monitor=ShadowHeatingPerformanceMonitor(enabled=True),
            diagnostics_projector=FailingDiagnosticsProjector(),
            **scenario,
        )

        assert enabled_trace == disabled_trace == failed_trace


def test_blocking_assessment_begins_only_after_control_commands_execute() -> None:
    runtime, source, delivery_port, sensor_id, _ = create_heat_delivery_runtime()
    blocking_assessor = BlockingPerformanceAssessor()
    monitor = ShadowHeatingPerformanceMonitor(assessor=blocking_assessor)
    runtime.heating_performance_monitor = monitor
    run_heat_delivery_cycle(runtime, sensor_id)
    results = []
    errors = []

    def assess_pending() -> None:
        try:
            results.extend(monitor.assess_pending())
        except Exception as error:
            errors.append(error)

    worker = Thread(target=assess_pending)
    worker.start()
    assert blocking_assessor.entered.wait(timeout=5)

    source_command_count = len(source.commands)
    actuator_command_count = len(delivery_port.commands)
    reevaluation = runtime.reevaluate_heat_demand()

    assert [command.value for command in delivery_port.commands] == [30, 22]
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert len(source.commands) == source_command_count
    assert len(delivery_port.commands) == actuator_command_count
    assert reevaluation.command.action is HeatingAction.DISABLE_HEATING

    blocking_assessor.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []
    assert len(results) == 1


def test_runtime_branches_confirmed_zone_demand_to_heat_delivery_without_changing_source() -> None:
    runtime, source, delivery_port, sensor_id, _ = create_heat_delivery_runtime()

    result = runtime.process_temperature(Measurement(sensor_id=sensor_id, value=Temperature(20), timestamp=NOW))
    runtime.reevaluate_heat_demand()

    assert [command.value for command in delivery_port.commands] == [30]
    assert len(source.commands) == 1
    assert source.commands[0] == result.heat_demand_evaluation.command
    episode = runtime.heating_episode_observer.active_episodes[0]
    assert episode.initial_temperature == 20
    assert len(episode.samples) == 2
    assert episode.samples[-1].source_observation.reported_heat_available.quality is ObservationQuality.UNKNOWN

    no_heat_result = runtime.process_temperature(Measurement(sensor_id=sensor_id, value=Temperature(23), timestamp=NOW))

    assert no_heat_result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert [command.value for command in delivery_port.commands] == [30, 22]
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert runtime.heating_episode_observer.active_episodes == ()
    assert (
        runtime.heating_episode_observer.completed_episodes[0].termination_reason
        is HeatingEpisodeTerminationReason.DEMAND_CLEARED
    )

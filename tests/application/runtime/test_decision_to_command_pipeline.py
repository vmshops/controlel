from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration.zone_target_resolver import (
    SensorConfigurationNotFoundError,
)
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.entities.zone import Zone
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
DEFAULT_MAX_AGE = timedelta(minutes=5)


class FixedClock:
    def __init__(self, current_time: datetime = NOW):
        self.current_time = current_time

    def now(self) -> datetime:
        return self.current_time


class RecordingActuator(ActuatorPort):
    def __init__(self):
        self.commands: list[Command] = []

    def execute(self, command: Command) -> None:
        self.commands.append(command)


class ActuatorFailure(Exception):
    pass


class FailingActuator(ActuatorPort):
    def __init__(self, error: Exception):
        self.error = error
        self.commands = []

    def execute(self, command: Command) -> None:
        self.commands.append(command)
        raise self.error


class UnsupportedDecisionControlLoop:
    def process(self, context) -> DecisionCreatedEvent:
        return DecisionCreatedEvent(
            decision=Decision(
                sensor_id=context.sensor_id,
                zone_id=context.zone_id,
                action=DecisionAction.OBSERVE_ONLY,
            ),
        )


def create_measurement(
    value: float,
    timestamp: datetime | None = None,
    sensor_id: str = "living_room_temperature",
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value=sensor_id),
        value=Temperature(value),
        timestamp=timestamp or NOW,
    )


def create_runtime(
    actuator: ActuatorPort,
    configurations: dict[str, tuple[str, float]] | None = None,
    maximum_ages: dict[str, timedelta] | None = None,
    max_future_skew: timedelta = timedelta(0),
    clock: FixedClock | None = None,
) -> ControlRuntime:
    configurations = configurations or {
        "living_room_temperature": ("living_room", 22),
    }
    maximum_ages = maximum_ages or {}
    sensors = SensorRepository()
    zones = ZoneRepository()
    for sensor_id, (zone_id, target) in configurations.items():
        sensors.add(
            Sensor(
                sensor_id=SensorId(value=sensor_id),
                zone_id=ZoneId(value=zone_id),
                name=sensor_id,
            )
        )
        zones.add(
            Zone(
                zone_id=ZoneId(value=zone_id),
                primary_sensor_id=SensorId(value=sensor_id),
                primary_measurement_max_age=maximum_ages.get(
                    zone_id,
                    DEFAULT_MAX_AGE,
                ),
                name=zone_id,
                target_temperature=Temperature(target),
            )
        )

    return ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        actuator=actuator,
        clock=clock or FixedClock(),
        max_future_skew=max_future_skew,
    )


def create_shared_zone_runtime(actuator: ActuatorPort) -> ControlRuntime:
    sensors = SensorRepository()
    for sensor_id in ("living_room_primary", "living_room_secondary"):
        sensors.add(
            Sensor(
                sensor_id=SensorId(value=sensor_id),
                zone_id=ZoneId(value="living_room"),
                name=sensor_id,
            )
        )
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_sensor_id=SensorId(value="living_room_primary"),
            primary_measurement_max_age=DEFAULT_MAX_AGE,
            name="Living room",
            target_temperature=Temperature(22),
        )
    )
    return ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        actuator=actuator,
        clock=FixedClock(),
        max_future_skew=timedelta(0),
    )


def test_low_temperature_produces_enable_heating_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    result = runtime.process_temperature(create_measurement(19))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    decision_event = result.decision_event
    assert decision_event.decision.action is DecisionAction.ENABLE_HEATING
    assert decision_event.decision.sensor_id == SensorId(value="living_room_temperature")
    assert decision_event.decision.zone_id == ZoneId(value="living_room")
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]
    assert actuator.commands[0].command_type is CommandFamily.HEATING
    assert result.command is actuator.commands[0]
    assert actuator.commands[0].zone_id == ZoneId(value="living_room")
    state = runtime.control_state_repository.get(ZoneId(value="living_room"))
    assert state.applied_action is HeatingAction.ENABLE_HEATING
    assert state.command_id == actuator.commands[0].id


def test_high_temperature_produces_disable_heating_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    result = runtime.process_temperature(create_measurement(23))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    decision_event = result.decision_event
    assert decision_event.decision.action is DecisionAction.DISABLE_HEATING
    assert decision_event.decision.sensor_id == SensorId(value="living_room_temperature")
    assert decision_event.decision.zone_id == ZoneId(value="living_room")
    assert [command.action for command in actuator.commands] == [HeatingAction.DISABLE_HEATING]
    assert actuator.commands[0].command_type is CommandFamily.HEATING
    assert result.command is actuator.commands[0]
    assert actuator.commands[0].zone_id == ZoneId(value="living_room")
    assert (
        runtime.control_state_repository.get(ZoneId(value="living_room")).applied_action
        is HeatingAction.DISABLE_HEATING
    )


def test_two_zones_dispatch_differently_targeted_commands_to_same_actuator():
    actuator = RecordingActuator()
    runtime = create_runtime(
        actuator,
        {
            "living_room_temperature": ("living_room", 22),
            "bedroom_temperature": ("bedroom", 22),
        },
    )

    living_room_event = runtime.process_temperature(create_measurement(19, sensor_id="living_room_temperature"))
    bedroom_event = runtime.process_temperature(create_measurement(19, sensor_id="bedroom_temperature"))

    assert living_room_event.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert bedroom_event.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert living_room_event.decision_event.decision.sensor_id == SensorId(value="living_room_temperature")
    assert bedroom_event.decision_event.decision.sensor_id == SensorId(value="bedroom_temperature")
    assert [command.zone_id for command in actuator.commands] == [
        ZoneId(value="living_room"),
        ZoneId(value="bedroom"),
    ]
    assert runtime.control_state_repository.get(ZoneId(value="living_room")).command_id == actuator.commands[0].id
    assert runtime.control_state_repository.get(ZoneId(value="bedroom")).command_id == actuator.commands[1].id


def test_secondary_measurement_is_observable_without_decision_or_command():
    actuator = RecordingActuator()
    runtime = create_shared_zone_runtime(actuator)
    published_measurements = []
    published_decisions = []
    runtime.event_bus.subscribe(
        TemperatureMeasuredEvent,
        lambda event: published_measurements.append(event.measurement),
    )
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)
    secondary = create_measurement(30, sensor_id="living_room_secondary")

    result = runtime.process_temperature(secondary)

    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_MISSING
    assert runtime.state_store.get_latest(secondary.sensor_id) is secondary
    assert published_measurements == [secondary]
    assert published_decisions == []
    assert actuator.commands == []


def test_secondary_does_not_regulate_when_primary_state_exists():
    actuator = RecordingActuator()
    runtime = create_shared_zone_runtime(actuator)
    primary = create_measurement(19, sensor_id="living_room_primary")
    secondary = create_measurement(30, sensor_id="living_room_secondary")

    primary_result = runtime.process_temperature(primary)
    secondary_result = runtime.process_temperature(secondary)

    assert primary_result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert primary_result.decision_event.decision.sensor_id == primary.sensor_id
    assert primary_result.decision_event.decision.zone_id == ZoneId(value="living_room")
    assert secondary_result.status is RuntimeProcessingStatus.NO_DECISION
    assert secondary_result.reason is TemperatureNoDecisionReason.SECONDARY_MEASUREMENT
    assert [command.zone_id for command in actuator.commands] == [ZoneId(value="living_room")]
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]


def test_stale_measurement_produces_no_additional_decision_or_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    current_timestamp = NOW
    current = create_measurement(19, current_timestamp)
    stale = create_measurement(18, current_timestamp - timedelta(seconds=1))
    published_measurements = []
    runtime.event_bus.subscribe(
        TemperatureMeasuredEvent,
        lambda event: published_measurements.append(event.measurement),
    )
    runtime.process_temperature(current)

    stale_result = runtime.process_temperature(stale)

    assert stale_result.status is RuntimeProcessingStatus.NO_DECISION
    assert stale_result.reason is TemperatureNoDecisionReason.OUT_OF_ORDER
    assert len(actuator.commands) == 1
    assert runtime.state_store.get_latest(current.sensor_id) == current
    assert published_measurements == [current, stale]


def test_cutoff_boundary_measurement_is_accepted_end_to_end():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    measurement = create_measurement(19, NOW - DEFAULT_MAX_AGE)

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.decision_event.decision.zone_id == ZoneId(value="living_room")
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]


def test_expired_primary_is_admitted_stored_and_observable_without_control_effects():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    measurement = create_measurement(
        19,
        NOW - DEFAULT_MAX_AGE - timedelta(microseconds=1),
    )
    published_measurements = []
    published_decisions = []
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, published_measurements.append)
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED
    assert runtime.state_store.get_latest(measurement.sensor_id) is measurement
    assert [event.measurement for event in published_measurements] == [measurement]
    assert published_decisions == []
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


def test_beyond_future_boundary_is_observable_but_has_no_state_or_control_effects():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator, max_future_skew=timedelta(minutes=1))
    measurement = create_measurement(
        19,
        NOW + timedelta(minutes=1, microseconds=1),
    )
    published_measurements = []
    published_decisions = []
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, published_measurements.append)
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert result.reason is TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED
    assert runtime.state_store.get_latest(measurement.sensor_id) is None
    assert [event.measurement for event in published_measurements] == [measurement]
    assert published_decisions == []
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


@pytest.mark.parametrize(
    "timestamp",
    [NOW + timedelta(seconds=30), NOW + timedelta(minutes=1)],
    ids=["within-tolerance", "exact-boundary"],
)
def test_admitted_future_is_stored_and_observable_but_temporarily_ineligible(timestamp):
    actuator = RecordingActuator()
    runtime = create_runtime(actuator, max_future_skew=timedelta(minutes=1))
    measurement = create_measurement(19, timestamp)
    published_measurements = []
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, published_measurements.append)

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_FUTURE_DATED
    assert runtime.state_store.get_latest(measurement.sensor_id) is measurement
    assert [event.measurement for event in published_measurements] == [measurement]
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


def test_valid_input_processes_normally_after_rejected_poisoning_attempt():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator, max_future_skew=timedelta(0))
    rejected = create_measurement(30, NOW + timedelta(microseconds=1))
    valid = create_measurement(19, NOW)

    rejected_result = runtime.process_temperature(rejected)
    valid_result = runtime.process_temperature(valid)

    assert rejected_result.status is RuntimeProcessingStatus.NO_DECISION
    assert rejected_result.reason is TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED
    assert valid_result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert runtime.state_store.get_latest(valid.sensor_id) is valid
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]


def test_existing_state_remains_unchanged_after_rejected_poisoning_attempt():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator, max_future_skew=timedelta(0))
    valid = create_measurement(19, NOW)
    runtime.process_temperature(valid)
    applied_state = runtime.control_state_repository.get(ZoneId(value="living_room"))
    rejected = create_measurement(30, NOW + timedelta(microseconds=1))

    result = runtime.process_temperature(rejected)

    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert result.reason is TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED
    assert runtime.state_store.get_latest(valid.sensor_id) is valid
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is applied_state
    assert len(actuator.commands) == 1


def test_zones_apply_independent_primary_measurement_max_ages():
    actuator = RecordingActuator()
    runtime = create_runtime(
        actuator,
        {
            "living_room_temperature": ("living_room", 22),
            "bedroom_temperature": ("bedroom", 22),
        },
        {
            "living_room": timedelta(minutes=5),
            "bedroom": timedelta(minutes=1),
        },
    )
    timestamp = NOW - timedelta(minutes=2)

    living_room_result = runtime.process_temperature(create_measurement(19, timestamp, "living_room_temperature"))
    bedroom_result = runtime.process_temperature(create_measurement(19, timestamp, "bedroom_temperature"))

    assert living_room_result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert bedroom_result.status is RuntimeProcessingStatus.NO_DECISION
    assert bedroom_result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED
    assert [command.zone_id for command in actuator.commands] == [ZoneId(value="living_room")]
    assert runtime.control_state_repository.get(ZoneId(value="bedroom")) is None


def test_missing_configuration_stops_before_decision_or_command():
    actuator = RecordingActuator()
    runtime = ControlRuntime(
        sensor_repository=SensorRepository(),
        zone_repository=ZoneRepository(),
        actuator=actuator,
        clock=FixedClock(),
        max_future_skew=timedelta(0),
    )
    published_decisions = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)
    measurement = create_measurement(19)

    with pytest.raises(SensorConfigurationNotFoundError):
        runtime.process_temperature(measurement)

    assert runtime.state_store.get_latest(measurement.sensor_id) == measurement
    assert published_decisions == []
    assert actuator.commands == []


def test_unsupported_decision_does_not_invoke_actuator():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    runtime.temperature_handler.control_loop = UnsupportedDecisionControlLoop()

    result = runtime.process_temperature(create_measurement(19))

    assert result.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND
    assert result.decision_event.decision.action is DecisionAction.OBSERVE_ONLY
    assert result.command is None
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


def test_decision_created_event_is_published_and_returned():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    published_events = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_events.append)

    result = runtime.process_temperature(create_measurement(19))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert published_events == [result.decision_event]


def test_temperature_handler_runs_before_observer_notification():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    original = create_measurement(19)
    conflicting = Measurement(
        sensor_id=original.sensor_id,
        value=Temperature(30),
        timestamp=original.timestamp,
    )
    observed_stored_measurements = []

    def conflicting_observer(event):
        observed_stored_measurements.append(runtime.state_store.get_latest(event.measurement.sensor_id))
        event.measurement = conflicting
        return "conflicting observer result"

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, conflicting_observer)

    result = runtime.process_temperature(original)

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.decision_event.decision.action is DecisionAction.ENABLE_HEATING
    assert observed_stored_measurements == [original]
    assert runtime.state_store.get_latest(original.sensor_id) == original
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]


def test_repeated_decisions_are_published_but_identical_applied_action_executes_once():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    published_decisions = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)

    first = runtime.process_temperature(create_measurement(19))
    second = runtime.process_temperature(create_measurement(19))

    assert first.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert second.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert published_decisions == [first.decision_event, second.decision_event]
    assert first.command is actuator.commands[0]
    assert second.command is not actuator.commands[0]
    assert [command.action for command in actuator.commands] == [HeatingAction.ENABLE_HEATING]
    assert second.command.action is HeatingAction.ENABLE_HEATING
    assert second.command.command_type is CommandFamily.HEATING
    state = runtime.control_state_repository.get(ZoneId(value="living_room"))
    assert state.command_id == actuator.commands[0].id


def test_changed_action_executes_and_replaces_applied_state():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    runtime.process_temperature(create_measurement(19))
    result = runtime.process_temperature(create_measurement(23))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.command is actuator.commands[1]
    assert [command.action for command in actuator.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    state = runtime.control_state_repository.get(ZoneId(value="living_room"))
    assert state.applied_action is HeatingAction.DISABLE_HEATING
    assert state.command_id == actuator.commands[1].id


def test_invalid_clock_contract_propagates_without_runtime_result():
    actuator = RecordingActuator()
    runtime = create_runtime(
        actuator,
        clock=FixedClock(datetime(2026, 1, 1, 12)),
    )
    measurement = create_measurement(19)

    with pytest.raises(
        ValueError,
        match=r"Clock\.now\(\) must return a timezone-aware datetime",
    ):
        runtime.process_temperature(measurement)

    assert runtime.state_store.get_latest(measurement.sensor_id) is None
    assert actuator.commands == []


def test_temperature_observer_failure_propagates_before_command_processing():
    error = RuntimeError("temperature observer failed")
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    def failing_observer(event):
        raise error

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, failing_observer)

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(create_measurement(19))

    assert raised.value is error
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


def test_decision_observer_failure_propagates_before_command_processing():
    error = RuntimeError("decision observer failed")
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    def failing_observer(event):
        raise error

    runtime.event_bus.subscribe(DecisionCreatedEvent, failing_observer)

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(create_measurement(19))

    assert raised.value is error
    assert actuator.commands == []
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None


def test_actuator_failure_does_not_record_requested_action():
    error = ActuatorFailure("execution failed")
    actuator = FailingActuator(error)
    runtime = create_runtime(actuator)
    published_decisions = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_decisions.append)

    with pytest.raises(ActuatorFailure) as raised:
        runtime.process_temperature(create_measurement(19))

    assert raised.value is error
    assert len(actuator.commands) == 1
    assert len(published_decisions) == 1
    assert runtime.control_state_repository.get(ZoneId(value="living_room")) is None

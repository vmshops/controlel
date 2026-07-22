from datetime import UTC, datetime, timedelta

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.decisions.decision import Decision
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


class RecordingActuator(ActuatorPort):
    def __init__(self):
        self.commands: list[Command] = []

    def execute(self, command: Command) -> None:
        self.commands.append(command)


class UnsupportedDecisionControlLoop:
    def process(self, context) -> DecisionCreatedEvent:
        return DecisionCreatedEvent(
            decision=Decision(action="observe_only"),
        )


def create_measurement(
    value: float,
    timestamp: datetime | None = None,
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(value),
        timestamp=timestamp or datetime.now(UTC),
    )


def create_runtime(actuator: ActuatorPort) -> ControlRuntime:
    sensors = SensorRepository()
    sensors.add(
        Sensor(
            sensor_id=SensorId(value="living_room_temperature"),
            zone_id=ZoneId(value="living_room"),
            name="Living room temperature",
        )
    )
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=ZoneId(value="living_room"),
            name="Living room",
            target_temperature=Temperature(22),
        )
    )

    return ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        actuator=actuator,
    )


def test_low_temperature_produces_enable_heating_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    decision_event = runtime.process_temperature(create_measurement(19))

    assert decision_event is not None
    assert decision_event.decision.action == "enable_heating"
    assert [command.action for command in actuator.commands] == ["enable_heating"]


def test_high_temperature_produces_disable_heating_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    decision_event = runtime.process_temperature(create_measurement(23))

    assert decision_event is not None
    assert decision_event.decision.action == "disable_heating"
    assert [command.action for command in actuator.commands] == ["disable_heating"]


def test_stale_measurement_produces_no_additional_decision_or_command():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    current_timestamp = datetime.now(UTC)
    current = create_measurement(19, current_timestamp)
    stale = create_measurement(18, current_timestamp - timedelta(seconds=1))
    published_measurements = []
    runtime.event_bus.subscribe(
        TemperatureMeasuredEvent,
        lambda event: published_measurements.append(event.measurement),
    )
    runtime.process_temperature(current)

    stale_result = runtime.process_temperature(stale)

    assert stale_result is None
    assert len(actuator.commands) == 1
    assert runtime.state_store.get_latest(current.sensor_id) == current
    assert published_measurements == [current, stale]


def test_unsupported_decision_does_not_invoke_actuator():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    runtime.temperature_handler.control_loop = UnsupportedDecisionControlLoop()

    decision_event = runtime.process_temperature(create_measurement(19))

    assert decision_event is not None
    assert decision_event.decision.action == "observe_only"
    assert actuator.commands == []


def test_decision_created_event_is_published_and_returned():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)
    published_events = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, published_events.append)

    result = runtime.process_temperature(create_measurement(19))

    assert isinstance(result, DecisionCreatedEvent)
    assert published_events == [result]


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

    assert result is not None
    assert result.decision.action == "enable_heating"
    assert observed_stored_measurements == [original]
    assert runtime.state_store.get_latest(original.sensor_id) == original
    assert [command.action for command in actuator.commands] == ["enable_heating"]


def test_repeated_accepted_measurements_produce_repeated_commands():
    actuator = RecordingActuator()
    runtime = create_runtime(actuator)

    runtime.process_temperature(create_measurement(19))
    runtime.process_temperature(create_measurement(19))

    assert [command.action for command in actuator.commands] == [
        "enable_heating",
        "enable_heating",
    ]

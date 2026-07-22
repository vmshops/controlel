from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


class NoOpActuator(ActuatorPort):
    def execute(self, command: Command) -> None:
        pass


def test_control_runtime_processes_temperature():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
    )

    runtime = ControlRuntime(
        target_temperature=Temperature(22),
        actuator=NoOpActuator(),
    )

    result = runtime.process_temperature(measurement)

    assert result.decision.action == "enable_heating"
    assert runtime.state_store.get_latest(measurement.sensor_id) == measurement


def test_control_runtime_keeps_measurements_for_multiple_sensors():
    living_room = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
    )
    bedroom = Measurement(
        sensor_id=SensorId(value="bedroom_temperature"),
        value=Temperature(20),
    )
    runtime = ControlRuntime(
        target_temperature=Temperature(22),
        actuator=NoOpActuator(),
    )

    runtime.process_temperature(living_room)
    runtime.process_temperature(bedroom)

    assert runtime.state_store.list_latest() == [living_room, bedroom]


def test_temperature_observer_return_values_cannot_replace_decision_result():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
    )
    runtime = ControlRuntime(
        target_temperature=Temperature(22),
        actuator=NoOpActuator(),
    )
    notified = []

    def first_observer(event):
        notified.append("first")
        return None

    def second_observer(event):
        notified.append("second")
        return "not a decision event"

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, first_observer)
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, second_observer)

    result = runtime.process_temperature(measurement)

    assert result is not None
    assert result.decision.action == "enable_heating"
    assert notified == ["first", "second"]

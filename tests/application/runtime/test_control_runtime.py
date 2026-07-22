from datetime import UTC, datetime, timedelta
from inspect import signature

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.entities.zone import Zone
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


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NoOpActuator(ActuatorPort):
    def execute(self, command: Command) -> None:
        pass


def create_runtime(sensor_targets: dict[str, float]) -> ControlRuntime:
    sensors = SensorRepository()
    zones = ZoneRepository()

    for sensor_id, target in sensor_targets.items():
        zone_id = ZoneId(value=f"{sensor_id}_zone")
        sensors.add(
            Sensor(
                sensor_id=SensorId(value=sensor_id),
                zone_id=zone_id,
                name=f"{sensor_id} display name",
            )
        )
        zones.add(
            Zone(
                zone_id=zone_id,
                primary_sensor_id=SensorId(value=sensor_id),
                primary_measurement_max_age=timedelta(minutes=5),
                name=f"{sensor_id} zone",
                target_temperature=Temperature(target),
            )
        )

    return ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        actuator=NoOpActuator(),
        clock=FixedClock(),
    )


def test_control_runtime_processes_temperature():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
        timestamp=NOW,
    )
    runtime = create_runtime({"living_room_temperature": 22})

    result = runtime.process_temperature(measurement)

    assert result.decision.action == "enable_heating"
    assert runtime.state_store.get_latest(measurement.sensor_id) == measurement
    assert runtime.control_state_repository.get(result.decision.zone_id).applied_action == "enable_heating"


def test_control_runtime_keeps_measurements_for_multiple_sensors():
    living_room = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
        timestamp=NOW,
    )
    bedroom = Measurement(
        sensor_id=SensorId(value="bedroom_temperature"),
        value=Temperature(20),
        timestamp=NOW,
    )
    runtime = create_runtime(
        {
            "living_room_temperature": 22,
            "bedroom_temperature": 22,
        }
    )

    runtime.process_temperature(living_room)
    runtime.process_temperature(bedroom)

    assert runtime.state_store.list_latest() == [living_room, bedroom]


def test_equal_temperatures_in_different_zones_use_different_targets():
    runtime = create_runtime(
        {
            "living_room_temperature": 22,
            "bedroom_temperature": 18,
        }
    )

    living_room_result = runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="living_room_temperature"),
            value=Temperature(20),
            timestamp=NOW,
        )
    )
    bedroom_result = runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="bedroom_temperature"),
            value=Temperature(20),
            timestamp=NOW,
        )
    )

    assert living_room_result.decision.action == "enable_heating"
    assert bedroom_result.decision.action == "disable_heating"


def test_temperature_observer_return_values_cannot_replace_decision_result():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
        timestamp=NOW,
    )
    runtime = create_runtime({"living_room_temperature": 22})
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


def test_control_runtime_no_longer_accepts_static_target_temperature():
    assert "target_temperature" not in signature(ControlRuntime).parameters


def test_control_runtime_requires_explicit_clock():
    parameter = signature(ControlRuntime).parameters["clock"]

    assert parameter.default is parameter.empty

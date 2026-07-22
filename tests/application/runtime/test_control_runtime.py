from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


def test_control_runtime_processes_temperature():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(19),
    )

    runtime = ControlRuntime(target_temperature=Temperature(22))

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
    runtime = ControlRuntime(target_temperature=Temperature(22))

    runtime.process_temperature(living_room)
    runtime.process_temperature(bedroom)

    assert runtime.state_store.list_latest() == [living_room, bedroom]

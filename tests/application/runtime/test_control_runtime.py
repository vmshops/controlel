from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


def test_control_runtime_processes_temperature():
    measurement = Measurement(
        value=Temperature(19),
        target=Temperature(22),
    )

    runtime = ControlRuntime()

    result = runtime.process_temperature(measurement)

    assert result is not None

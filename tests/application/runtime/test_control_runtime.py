from datetime import UTC, datetime, timedelta
from inspect import signature

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.runtime_processing_result import RuntimeProcessingStatus
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.entities.zone import Zone
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
    ]
    assert "actuator_routes" not in parameters
    assert "actuator" not in parameters
    assert "target_temperature" not in parameters

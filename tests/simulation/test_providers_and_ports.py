from datetime import UTC, datetime

import pytest

from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import ReportedSourceState
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId
from controlel.simulation import SimulationRecorder, SimulationRun, VirtualClock
from controlel.simulation.adapters.heating_ports import RecordingHeatSourcePort
from controlel.simulation.adapters.heating_providers import (
    VirtualEvidenceUnavailable,
    VirtualSourceStateProvider,
    VirtualTemperatureSensor,
)


def test_virtual_temperature_and_source_providers_retain_only_explicit_evidence() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    sensor_id = SensorId("room")
    sensor = Sensor(sensor_id=sensor_id, zone_id=ZoneId("zone"), name="Room")
    temperature = VirtualTemperatureSensor(sensor_id)
    source = VirtualSourceStateProvider()

    with pytest.raises(VirtualEvidenceUnavailable):
        temperature.measure(sensor)

    supplied = temperature.observe(19.5, observed_at=now)
    reported = source.observe(ReportedSourceState.UNKNOWN, observed_at=now)

    assert temperature.measure(sensor) == supplied
    assert reported.state is ReportedSourceState.UNKNOWN
    assert source.evidence == reported


def test_successful_recording_command_does_not_create_reported_source_state() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    run = SimulationRun(run_id="run", environment_id="shadow", scenario_id="scenario", started_at=now)
    recorder = SimulationRecorder(run)
    port = RecordingHeatSourcePort(VirtualClock(now), recorder)
    source = VirtualSourceStateProvider()

    port.execute(
        HeatSourceCommand(
            command_type=CommandFamily.HEATING,
            action=HeatingAction.ENABLE_HEATING,
        )
    )

    assert source.evidence is None
    assert recorder.records[-1].payload["dispatch_outcome"] == "dispatched"

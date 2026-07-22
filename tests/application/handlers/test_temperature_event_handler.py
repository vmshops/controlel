from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration.zone_target_resolver import (
    SensorConfigurationNotFoundError,
    ZoneTargetResolver,
)
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.state.runtime_state_store import RuntimeStateStore
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


class RecordingControlLoop:
    def __init__(self):
        self.contexts = []

    def process(self, context):
        self.contexts.append(context)
        return context


class RecordingTargetResolver(ZoneTargetResolver):
    def __init__(self, zone: Zone):
        self.zone = zone
        self.sensor_ids = []

    def resolve(self, sensor_id: SensorId) -> Zone:
        self.sensor_ids.append(sensor_id)
        return self.zone


def create_event(
    value: float,
    timestamp: datetime | None = None,
) -> TemperatureMeasuredEvent:
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(value),
        timestamp=timestamp or datetime.now(UTC),
    )
    return TemperatureMeasuredEvent(measurement=measurement)


def create_configured_resolver(target: float = 22) -> ZoneTargetResolver:
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
            target_temperature=Temperature(target),
        )
    )
    return ZoneTargetResolver(sensors, zones)


def test_accepted_measurement_is_recorded_and_uses_resolved_zone_target():
    state_store = RuntimeStateStore()
    control_loop = RecordingControlLoop()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_resolver=create_configured_resolver(target=18),
    )
    handler.control_loop = control_loop
    event = create_event(19)

    handler.handle(event)

    assert state_store.get_latest(event.measurement.sensor_id) == event.measurement
    assert control_loop.contexts[0].sensor_id == event.measurement.sensor_id
    assert control_loop.contexts[0].zone_id == ZoneId(value="living_room")
    assert control_loop.contexts[0].target_temperature == Temperature(18)


def test_stale_measurement_does_not_invoke_target_resolution_or_control_loop():
    state_store = RuntimeStateStore()
    newest_timestamp = datetime.now(UTC)
    newest_event = create_event(20, newest_timestamp)
    stale_event = create_event(19, newest_timestamp - timedelta(minutes=1))
    state_store.record(newest_event.measurement)
    target_resolver = RecordingTargetResolver(
        Zone(
            zone_id=ZoneId(value="living_room"),
            name="Living room",
            target_temperature=Temperature(22),
        )
    )
    control_loop = RecordingControlLoop()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_resolver=target_resolver,
    )
    handler.control_loop = control_loop

    result = handler.handle(stale_event)

    assert result is None
    assert target_resolver.sensor_ids == []
    assert control_loop.contexts == []
    assert state_store.get_latest(newest_event.measurement.sensor_id) == (newest_event.measurement)


def test_missing_configuration_keeps_measurement_and_skips_regulation():
    state_store = RuntimeStateStore()
    control_loop = RecordingControlLoop()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_resolver=ZoneTargetResolver(SensorRepository(), ZoneRepository()),
    )
    handler.control_loop = control_loop
    event = create_event(19)

    with pytest.raises(SensorConfigurationNotFoundError):
        handler.handle(event)

    assert state_store.list_latest() == [event.measurement]
    assert control_loop.contexts == []


def test_accepted_measurement_preserves_decision_behavior():
    handler = TemperatureEventHandler(
        state_store=RuntimeStateStore(),
        target_resolver=create_configured_resolver(target=22),
    )

    result = handler.handle(create_event(19))

    assert result.decision.action == "enable_heating"

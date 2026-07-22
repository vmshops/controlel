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
from controlel.application.state.zone_temperature_aggregator import (
    PrimarySensorConfigurationNotFoundError,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

PRIMARY_SENSOR_ID = SensorId(value="living_room_primary")
SECONDARY_SENSOR_ID = SensorId(value="living_room_secondary")
ZONE_ID = ZoneId(value="living_room")


class RecordingControlLoop:
    def __init__(self):
        self.contexts = []

    def process(self, context):
        self.contexts.append(context)
        return context


class RecordingTargetResolver:
    def __init__(self, zone: Zone):
        self.zone = zone
        self.sensor_ids = []

    def resolve(self, sensor_id: SensorId) -> Zone:
        self.sensor_ids.append(sensor_id)
        return self.zone


class RecordingAggregator:
    def __init__(
        self,
        effective: Measurement | None,
        error: Exception | None = None,
    ):
        self.effective = effective
        self.error = error
        self.zones = []

    def get_effective(self, zone: Zone) -> Measurement | None:
        self.zones.append(zone)
        if self.error is not None:
            raise self.error
        return self.effective


def create_zone(target: float = 22) -> Zone:
    return Zone(
        zone_id=ZONE_ID,
        primary_sensor_id=PRIMARY_SENSOR_ID,
        name="Living room",
        target_temperature=Temperature(target),
    )


def create_measurement(
    sensor_id: SensorId = PRIMARY_SENSOR_ID,
    value: float = 19,
    timestamp: datetime | None = None,
) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        value=Temperature(value),
        timestamp=timestamp or datetime.now(UTC),
    )


def create_handler(
    state_store: RuntimeStateStore,
    resolver,
    aggregator,
) -> tuple[TemperatureEventHandler, RecordingControlLoop]:
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_resolver=resolver,
        temperature_aggregator=aggregator,
    )
    control_loop = RecordingControlLoop()
    handler.control_loop = control_loop
    return handler, control_loop


def test_stale_measurement_returns_before_zone_resolution_and_aggregation():
    state_store = RuntimeStateStore()
    newest_timestamp = datetime.now(UTC)
    newest = create_measurement(timestamp=newest_timestamp)
    stale = create_measurement(timestamp=newest_timestamp - timedelta(minutes=1))
    state_store.record(newest)
    resolver = RecordingTargetResolver(create_zone())
    aggregator = RecordingAggregator(newest)
    handler, control_loop = create_handler(state_store, resolver, aggregator)

    result = handler.handle(TemperatureMeasuredEvent(measurement=stale))

    assert result is None
    assert resolver.sensor_ids == []
    assert aggregator.zones == []
    assert control_loop.contexts == []
    assert state_store.get_latest(PRIMARY_SENSOR_ID) is newest


def test_accepted_primary_measurement_creates_context_and_invokes_regulation():
    state_store = RuntimeStateStore()
    measurement = create_measurement()
    zone = create_zone(target=18)
    resolver = RecordingTargetResolver(zone)
    aggregator = RecordingAggregator(measurement)
    handler, control_loop = create_handler(state_store, resolver, aggregator)

    result = handler.handle(TemperatureMeasuredEvent(measurement=measurement))

    assert result is control_loop.contexts[0]
    assert state_store.get_latest(PRIMARY_SENSOR_ID) is measurement
    assert aggregator.zones == [zone]
    assert control_loop.contexts[0].sensor_id == PRIMARY_SENSOR_ID
    assert control_loop.contexts[0].zone_id == ZONE_ID
    assert control_loop.contexts[0].current_temperature == measurement.value
    assert control_loop.contexts[0].target_temperature == Temperature(18)


def test_accepted_secondary_is_stored_but_does_not_invoke_regulation():
    state_store = RuntimeStateStore()
    primary = create_measurement()
    secondary = create_measurement(SECONDARY_SENSOR_ID, value=30)
    state_store.record(primary)
    zone = create_zone()
    aggregator = RecordingAggregator(primary)
    handler, control_loop = create_handler(
        state_store,
        RecordingTargetResolver(zone),
        aggregator,
    )

    result = handler.handle(TemperatureMeasuredEvent(measurement=secondary))

    assert result is None
    assert state_store.get_latest(SECONDARY_SENSOR_ID) is secondary
    assert aggregator.zones == [zone]
    assert control_loop.contexts == []


def test_missing_primary_runtime_state_produces_no_decision():
    state_store = RuntimeStateStore()
    secondary = create_measurement(SECONDARY_SENSOR_ID)
    handler, control_loop = create_handler(
        state_store,
        RecordingTargetResolver(create_zone()),
        RecordingAggregator(None),
    )

    result = handler.handle(TemperatureMeasuredEvent(measurement=secondary))

    assert result is None
    assert state_store.get_latest(SECONDARY_SENSOR_ID) is secondary
    assert control_loop.contexts == []


def test_primary_configuration_exception_propagates_after_measurement_is_stored():
    state_store = RuntimeStateStore()
    measurement = create_measurement()
    error = PrimarySensorConfigurationNotFoundError(PRIMARY_SENSOR_ID, ZONE_ID)
    handler, control_loop = create_handler(
        state_store,
        RecordingTargetResolver(create_zone()),
        RecordingAggregator(None, error=error),
    )

    with pytest.raises(PrimarySensorConfigurationNotFoundError) as raised:
        handler.handle(TemperatureMeasuredEvent(measurement=measurement))

    assert raised.value is error
    assert state_store.get_latest(PRIMARY_SENSOR_ID) is measurement
    assert control_loop.contexts == []


def test_zone_resolution_exception_propagates_before_aggregation():
    state_store = RuntimeStateStore()
    measurement = create_measurement()
    aggregator = RecordingAggregator(None)
    handler, control_loop = create_handler(
        state_store,
        ZoneTargetResolver(SensorRepository(), ZoneRepository()),
        aggregator,
    )

    with pytest.raises(SensorConfigurationNotFoundError):
        handler.handle(TemperatureMeasuredEvent(measurement=measurement))

    assert state_store.get_latest(PRIMARY_SENSOR_ID) is measurement
    assert aggregator.zones == []
    assert control_loop.contexts == []

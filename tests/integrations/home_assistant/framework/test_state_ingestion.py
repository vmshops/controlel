import asyncio
import logging
from datetime import UTC, datetime, timedelta
from threading import Event as ThreadEvent
from threading import get_ident
from types import SimpleNamespace

import pytest
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_STATE_CHANGED,
    UnitOfTemperature,
)
from homeassistant.core import State

from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel.config import (
    DiagnosticConfiguration,
    HomeAssistantSensorBinding,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import HomeAssistantScheduledFailureSink
from custom_components.controlel.host import HomeAssistantControlelHost
from custom_components.controlel.measurement_ingestion import HomeAssistantMeasurementMapper
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
ENTITY_ID = "sensor.living_room_temperature"


class RecordingRuntime:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []
        self.threads: list[int] = []
        self.process_gates: dict[float, tuple[ThreadEvent, ThreadEvent]] = {}
        self.start_gate: tuple[ThreadEvent, ThreadEvent] | None = None
        self.active = False

    def process_temperature(self, measurement):
        assert self.active is False
        self.active = True
        try:
            self.threads.append(get_ident())
            self.operations.append(("temperature", measurement))
            if gate := self.process_gates.get(measurement.value.value):
                gate[0].set()
                gate[1].wait()
            return RuntimeProcessingResult(
                status=RuntimeProcessingStatus.NO_DECISION,
                reason=TemperatureNoDecisionReason.SECONDARY_MEASUREMENT,
            )
        finally:
            self.active = False

    def start(self):
        assert self.active is False
        self.active = True
        try:
            self.threads.append(get_ident())
            self.operations.append(("start", None))
            if self.start_gate is not None:
                self.start_gate[0].set()
                self.start_gate[1].wait()
            return SimpleNamespace(
                status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
                next_evaluation_at=NOW,
            )
        finally:
            self.active = False

    def mark_measurement_indeterminate(self):
        assert self.active is False
        self.threads.append(get_ident())
        self.operations.append(("indeterminate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def stop(self) -> None:
        assert self.active is False
        self.threads.append(get_ident())
        self.operations.append(("stop", None))


def make_host(hass, runtime: RecordingRuntime) -> HomeAssistantControlelHost:
    bridge = HomeAssistantEventLoopBridge(hass.loop)
    sink = HomeAssistantScheduledFailureSink(
        hass=hass,
        bridge=bridge,
        entry_id="framework-entry",
        logger=logging.getLogger(__name__),
    )
    host = HomeAssistantControlelHost(
        hass=hass,
        runtime=runtime,
        executor=HomeAssistantRuntimeExecutor(),
        measurement_mapper=HomeAssistantMeasurementMapper(
            HomeAssistantSensorBinding(
                entity_id=ENTITY_ID,
                sensor_id=SensorId("living_room_temperature"),
            )
        ),
        failure_sink=sink,
        config=SimpleNamespace(
            zone_name="Living room",
            zone_id=ZoneId("living_room"),
            sensor_name="Living room temperature",
            sensor_id=SensorId("living_room_temperature"),
            temperature_entity_id=ENTITY_ID,
            target_temperature=Temperature(21),
            heating_turn_on_differential=0.0,
            heating_turn_off_differential=0.0,
            heat_demand_confirmation_duration=timedelta(0),
            primary_measurement_max_age=timedelta(minutes=5),
            indeterminate_grace_period=timedelta(minutes=1),
            minimum_heating_on_time=timedelta(0),
            minimum_heating_off_time=timedelta(0),
            indeterminate_timeout_action=SimpleNamespace(value="disable_heating"),
            diagnostic_configuration=DiagnosticConfiguration(
                profile="basic",
                debug_duration=timedelta(hours=1),
                configured_debug_duration=timedelta(hours=1),
                profile_before_debug="detailed",
            ),
        ),
        core_version="0.4.0",
        logger=logging.getLogger(__name__),
    )
    sink.bind_fatal_handler(host.request_fatal_shutdown)
    return host


def fire_state(hass, state: State, old_state: State | None = None) -> None:
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {
            ATTR_ENTITY_ID: state.entity_id,
            "old_state": old_state,
            "new_state": state,
        },
    )


async def wait_until(predicate) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_real_state_events_map_only_configured_entity_and_preserve_framework_state(hass) -> None:
    hass.states.async_set(ENTITY_ID, "unknown")
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    loop_thread = get_ident()
    await host.async_initialize()
    assert [operation for operation, _ in runtime.operations] == ["start", "indeterminate"]

    hass.states.async_set(
        "sensor.other",
        "12",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    celsius = State(
        ENTITY_ID,
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        last_updated=NOW,
    )
    fahrenheit = State(
        ENTITY_ID,
        "68",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.FAHRENHEIT},
        last_updated=NOW + timedelta(seconds=1),
    )
    fire_state(hass, celsius)
    fire_state(hass, fahrenheit, celsius)
    await hass.async_block_till_done()

    measurements = [value for operation, value in runtime.operations if operation == "temperature"]
    assert [measurement.value.value for measurement in measurements] == [20.0, pytest.approx(20.0)]
    assert measurements[0].timestamp is NOW
    assert len(set(runtime.threads)) == 1
    assert runtime.threads[0] != loop_thread

    invalid_states = [
        State(ENTITY_ID, "unknown", last_updated=NOW + timedelta(seconds=2)),
        State(ENTITY_ID, "unavailable", last_updated=NOW + timedelta(seconds=3)),
        State(
            ENTITY_ID,
            "not-a-number",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
            last_updated=NOW + timedelta(seconds=4),
        ),
        State(
            ENTITY_ID,
            "20",
            {ATTR_UNIT_OF_MEASUREMENT: "%"},
            last_updated=NOW + timedelta(seconds=5),
        ),
    ]
    for state in invalid_states:
        fire_state(hass, state)
    await hass.async_block_till_done()
    assert len([operation for operation, _ in runtime.operations if operation == "temperature"]) == 2

    newer = State(
        ENTITY_ID,
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        last_updated=NOW + timedelta(seconds=20),
    )
    older = State(
        ENTITY_ID,
        "21",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        last_updated=NOW + timedelta(seconds=10),
    )
    fire_state(hass, newer)
    fire_state(hass, older, newer)
    fire_state(hass, older, newer)
    await hass.async_block_till_done()
    measurements = [value for operation, value in runtime.operations if operation == "temperature"]
    assert [measurement.value.value for measurement in measurements[-2:]] == [22.0, 21.0]

    await host.async_stop()
    fire_state(
        hass,
        State(
            ENTITY_ID,
            "18",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
            last_updated=NOW + timedelta(seconds=30),
        ),
    )
    await hass.async_block_till_done()
    assert [operation for operation, _ in runtime.operations].count("temperature") == 4


@pytest.mark.asyncio
async def test_real_startup_subscription_buffers_snapshot_start_and_drain_without_loss(hass) -> None:
    hass.states.async_set(
        ENTITY_ID,
        "19",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    runtime = RecordingRuntime()
    snapshot_entered = ThreadEvent()
    snapshot_release = ThreadEvent()
    start_entered = ThreadEvent()
    start_release = ThreadEvent()
    during_drain_entered = ThreadEvent()
    during_drain_release = ThreadEvent()
    runtime.process_gates[19.0] = (snapshot_entered, snapshot_release)
    runtime.process_gates[21.0] = (during_drain_entered, during_drain_release)
    runtime.start_gate = (start_entered, start_release)
    host = make_host(hass, runtime)

    initialize_task = hass.async_create_task(host.async_initialize())
    await asyncio.to_thread(start_entered.wait)
    hass.states.async_set(
        ENTITY_ID,
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await wait_until(lambda: len(host._buffer) == 1)
    start_release.set()

    await asyncio.to_thread(snapshot_entered.wait)
    hass.states.async_set(
        ENTITY_ID,
        "21",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await wait_until(lambda: len(host._buffer) == 2)
    snapshot_release.set()

    await asyncio.to_thread(during_drain_entered.wait)
    hass.states.async_set(
        ENTITY_ID,
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await wait_until(lambda: len(host._buffer) == 1)
    during_drain_release.set()
    await initialize_task

    hass.states.async_set(
        ENTITY_ID,
        "23",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()

    assert [
        value.value.value if operation == "temperature" else operation for operation, value in runtime.operations
    ] == ["start", 19.0, 20.0, 21.0, 22.0, 23.0]
    assert len(set(runtime.threads)) == 1
    await host.async_stop()

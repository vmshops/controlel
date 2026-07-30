import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, get_ident
from types import SimpleNamespace

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
from custom_components.controlel.config import HomeAssistantSensorBinding
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import HomeAssistantScheduledFailureSink
from custom_components.controlel.host import HomeAssistantControlelHost
from custom_components.controlel.measurement_ingestion import (
    HomeAssistantMeasurementMapper,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def host_config():
    return SimpleNamespace(
        zone_name="Room",
        zone_id=ZoneId("room"),
        sensor_name="Room temperature",
        sensor_id=SensorId("room_temperature"),
        temperature_entity_id="sensor.room",
        target_temperature=Temperature(21),
        heating_turn_on_differential=0.3,
        heating_turn_off_differential=0.1,
        indeterminate_timeout_action=SimpleNamespace(value="disable_heating"),
    )


@dataclass
class FakeState:
    state: str
    last_updated: datetime
    entity_id: str = "sensor.room"

    @property
    def attributes(self):
        return {"unit_of_measurement": "°C"}


class FakeHass:
    def async_create_task(self, target, name=None):
        return asyncio.create_task(target, name=name)


class FakeRuntime:
    def __init__(self):
        self.operations: list[tuple[str, object]] = []
        self.worker_threads: list[int] = []
        self.process_entered = Event()
        self.process_release = Event()
        self.process_release.set()
        self.start_entered = Event()
        self.start_release = Event()
        self.start_release.set()

    def process_temperature(self, measurement):
        self.worker_threads.append(get_ident())
        self.operations.append(("measurement", measurement.value.value))
        self.process_entered.set()
        self.process_release.wait()
        return RuntimeProcessingResult(
            status=RuntimeProcessingStatus.NO_DECISION,
            reason=TemperatureNoDecisionReason.SECONDARY_MEASUREMENT,
        )

    def start(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("start", None))
        self.start_entered.set()
        self.start_release.wait()
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def reevaluate_heat_demand(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("reevaluate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def stop(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("stop", None))


def test_snapshot_buffer_start_live_and_stop_ordering():
    async def scenario():
        event_loop_thread = get_ident()
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        runtime.process_release.clear()
        runtime.start_release.clear()
        listener_holder = {}
        unsubscribed: list[None] = []

        def subscribe(hass, entity_id, listener):
            listener_holder["listener"] = listener
            return lambda: unsubscribed.append(None)

        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.2.0",
            logger=logging.getLogger(__name__),
            state_subscriber=subscribe,
            state_getter=lambda entity_id: FakeState("19", NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)

        initialize = asyncio.create_task(host.async_initialize())
        while not runtime.process_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("20", NOW.replace(second=1)))
        runtime.process_release.set()

        while not runtime.start_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("21", NOW.replace(second=2)))
        runtime.start_release.set()
        await initialize

        listener_holder["listener"](FakeState("22", NOW.replace(second=3)))
        while len(runtime.operations) < 5:
            await asyncio.sleep(0)

        duplicate = FakeState("22", NOW.replace(second=3))
        listener_holder["listener"](duplicate)
        await asyncio.sleep(0.01)

        await host.async_stop()
        await host.async_stop()
        listener_holder["listener"](FakeState("23", NOW.replace(second=4)))
        await asyncio.sleep(0)
        return (
            runtime,
            host,
            unsubscribed,
            event_loop_thread,
        )

    runtime, host, unsubscribed, event_loop_thread = asyncio.run(scenario())

    assert runtime.operations == [
        ("measurement", 19.0),
        ("measurement", 20.0),
        ("start", None),
        ("measurement", 21.0),
        ("measurement", 22.0),
        ("stop", None),
    ]
    assert len(set(runtime.worker_threads)) == 1
    assert runtime.worker_threads[0] != event_loop_thread
    assert unsubscribed == [None]
    assert host.accepting is False
    assert host.stopped is True


def test_unavailable_snapshot_reaches_start_without_synthetic_measurement():
    async def scenario():
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.2.0",
            logger=logging.getLogger(__name__),
            state_subscriber=lambda hass, entity_id, listener: lambda: None,
            state_getter=lambda entity_id: FakeState("unavailable", NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
        await host.async_initialize()
        await host.async_stop()
        return runtime.operations

    assert asyncio.run(scenario()) == [("start", None), ("stop", None)]

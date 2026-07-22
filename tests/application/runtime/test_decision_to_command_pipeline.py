from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration.zone_target_resolver import (
    SensorConfigurationNotFoundError,
)
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)


class MutableClock:
    def __init__(self, current_time: datetime = NOW):
        self.current_time = current_time

    def now(self) -> datetime:
        return self.current_time


class RecordingHeatSource:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.commands: list[HeatSourceCommand] = []
        self.error = RuntimeError("heat source failed")

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if len(self.commands) <= self.failures:
            raise self.error


class FailOnCallHeatSource(RecordingHeatSource):
    def __init__(self, fail_on_call: int):
        super().__init__()
        self.fail_on_call = fail_on_call

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if len(self.commands) == self.fail_on_call:
            raise self.error


class ObserveOnlyControlLoop:
    def process(self, context) -> DecisionCreatedEvent:
        return DecisionCreatedEvent(
            decision=Decision(
                sensor_id=context.sensor_id,
                zone_id=context.zone_id,
                observed_at=context.observed_at,
                action=DecisionAction.OBSERVE_ONLY,
            )
        )


def create_measurement(
    value: float,
    sensor_id: str = "living_room_temperature",
    timestamp: datetime = NOW,
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value=sensor_id),
        value=Temperature(value),
        timestamp=timestamp,
    )


def create_runtime(
    port: RecordingHeatSource,
    zones: tuple[str, ...] = ("living_room",),
    clock: MutableClock | None = None,
    max_future_skew: timedelta = timedelta(0),
    max_ages: dict[str, timedelta] | None = None,
) -> ControlRuntime:
    sensors = SensorRepository()
    zone_repository = ZoneRepository()
    max_ages = max_ages or {}
    for zone_name in zones:
        sensor_id = SensorId(value=f"{zone_name}_temperature")
        zone_id = ZoneId(value=zone_name)
        sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name=sensor_id.value))
        zone_repository.add(
            Zone(
                zone_id=zone_id,
                primary_sensor_id=sensor_id,
                primary_measurement_max_age=max_ages.get(zone_name, MAX_AGE),
                name=zone_name,
                target_temperature=Temperature(22),
            )
        )

    return ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zone_repository,
        heat_source_port=port,
        clock=clock or MutableClock(),
        max_future_skew=max_future_skew,
    )


def create_runtime_with_secondary(port: RecordingHeatSource) -> ControlRuntime:
    sensors = SensorRepository()
    zone_id = ZoneId(value="living_room")
    for sensor_name in ("living_room_primary", "living_room_secondary"):
        sensors.add(
            Sensor(
                sensor_id=SensorId(value=sensor_name),
                zone_id=zone_id,
                name=sensor_name,
            )
        )
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=zone_id,
            primary_sensor_id=SensorId(value="living_room_primary"),
            primary_measurement_max_age=MAX_AGE,
            name="living_room",
            target_temperature=Temperature(22),
        )
    )
    return ControlRuntime(sensors, zones, port, MutableClock(), timedelta(0))


def test_single_zone_action_executes_shared_source_command_with_exact_provenance():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    measurement = create_measurement(19)

    result = runtime.process_temperature(measurement)

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.decision_event.decision.observed_at is measurement.timestamp
    assert result.building_heat_demand.status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert result.command is port.commands[0]
    assert result.command.action is HeatingAction.ENABLE_HEATING
    assert "zone_id" not in HeatSourceCommand.model_fields
    demand = runtime.zone_demand_store.get(ZoneId(value="living_room"))
    assert demand.observed_at is measurement.timestamp
    assert demand.source_sensor_id is measurement.sensor_id


def test_first_false_with_other_zone_missing_is_indeterminate_without_source_action():
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"))

    result = runtime.process_temperature(create_measurement(23))

    assert result.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE
    assert result.building_heat_demand.missing_zone_ids == (ZoneId(value="bedroom"),)
    assert result.command is None
    assert port.commands == []
    assert runtime.heat_source_state_store.get() is None


def test_first_true_with_other_zone_missing_enables_source():
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"))

    result = runtime.process_temperature(create_measurement(19))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.building_heat_demand.status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert port.commands[0].action is HeatingAction.ENABLE_HEATING


def test_single_zone_first_false_creates_explicit_disable_candidate():
    port = RecordingHeatSource()
    runtime = create_runtime(port)

    result = runtime.process_temperature(create_measurement(23))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.building_heat_demand.status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
    assert result.command.action is HeatingAction.DISABLE_HEATING


def test_second_true_creates_candidate_but_is_suppressed():
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"))
    first = runtime.process_temperature(create_measurement(19))

    second = runtime.process_temperature(create_measurement(19, sensor_id="bedroom_temperature"))

    assert first.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert second.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert second.command.id != first.command.id
    assert len(port.commands) == 1


def test_source_remains_enabled_until_last_true_zone_stops():
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"))
    runtime.process_temperature(create_measurement(19))
    runtime.process_temperature(create_measurement(19, sensor_id="bedroom_temperature"))

    one_stops = runtime.process_temperature(create_measurement(23))
    last_stops = runtime.process_temperature(create_measurement(23, sensor_id="bedroom_temperature"))

    assert one_stops.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert one_stops.command.action is HeatingAction.ENABLE_HEATING
    assert last_stops.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert last_stops.command.action is HeatingAction.DISABLE_HEATING
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_all_zones_fresh_false_explicitly_disables_source():
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"))
    first = runtime.process_temperature(create_measurement(23))
    second = runtime.process_temperature(create_measurement(23, sensor_id="bedroom_temperature"))

    assert first.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE
    assert second.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert second.command.action is HeatingAction.DISABLE_HEATING


@pytest.mark.parametrize("expired_requires_heat", [True, False])
def test_expired_demand_prevents_disable(expired_requires_heat):
    clock = MutableClock()
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"), clock)
    first_value = 19 if expired_requires_heat else 23
    runtime.process_temperature(create_measurement(first_value))
    clock.current_time = NOW + MAX_AGE + timedelta(seconds=1)

    result = runtime.process_temperature(
        create_measurement(
            23,
            sensor_id="bedroom_temperature",
            timestamp=clock.current_time,
        )
    )

    assert result.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE
    assert result.building_heat_demand.expired_zone_ids == (ZoneId(value="living_room"),)
    assert result.command is None
    assert all(command.action is not HeatingAction.DISABLE_HEATING for command in port.commands)


def test_fresh_true_overrides_expired_uncertainty():
    clock = MutableClock()
    port = RecordingHeatSource()
    runtime = create_runtime(port, ("living_room", "bedroom"), clock)
    runtime.process_temperature(create_measurement(23))
    clock.current_time = NOW + MAX_AGE + timedelta(seconds=1)

    result = runtime.process_temperature(
        create_measurement(
            19,
            sensor_id="bedroom_temperature",
            timestamp=clock.current_time,
        )
    )

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert result.building_heat_demand.status is BuildingHeatDemandStatus.HEAT_REQUIRED


def test_secondary_and_out_of_order_paths_do_not_change_retained_demand():
    port = RecordingHeatSource()
    runtime = create_runtime_with_secondary(port)
    accepted = Measurement(
        sensor_id=SensorId(value="living_room_primary"),
        value=Temperature(19),
        timestamp=NOW,
    )
    runtime.process_temperature(accepted)
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))

    secondary = runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="living_room_secondary"),
            value=Temperature(23),
            timestamp=NOW,
        )
    )
    stale = runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="living_room_primary"),
            value=Temperature(23),
            timestamp=NOW - timedelta(seconds=1),
        )
    )

    assert secondary.reason is TemperatureNoDecisionReason.SECONDARY_MEASUREMENT
    assert stale.reason is TemperatureNoDecisionReason.OUT_OF_ORDER
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained


def test_missing_primary_path_does_not_record_zone_demand():
    port = RecordingHeatSource()
    runtime = create_runtime_with_secondary(port)

    result = runtime.process_temperature(
        Measurement(
            sensor_id=SensorId(value="living_room_secondary"),
            value=Temperature(19),
            timestamp=NOW,
        )
    )

    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_MISSING
    assert runtime.zone_demand_store.list_current() == []
    assert port.commands == []


def test_expired_primary_path_retains_previous_zone_demand():
    clock = MutableClock()
    port = RecordingHeatSource()
    runtime = create_runtime(port, clock=clock)
    runtime.process_temperature(create_measurement(19))
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))
    clock.current_time = NOW + timedelta(minutes=10)
    expired_timestamp = clock.current_time - MAX_AGE - timedelta(seconds=1)

    result = runtime.process_temperature(create_measurement(23, timestamp=expired_timestamp))

    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained


def test_admitted_future_primary_path_retains_previous_zone_demand():
    port = RecordingHeatSource()
    runtime = create_runtime(port, max_future_skew=timedelta(minutes=1))
    runtime.process_temperature(create_measurement(19))
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))

    result = runtime.process_temperature(create_measurement(23, timestamp=NOW + timedelta(seconds=1)))

    assert result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_FUTURE_DATED
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained


def test_timestamp_admission_rejection_retains_demand_and_publishes_temperature_event():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    runtime.process_temperature(create_measurement(19))
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))
    observed = []
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, observed.append)
    rejected = create_measurement(23, timestamp=NOW + timedelta(seconds=1))

    result = runtime.process_temperature(rejected)

    assert result.reason is TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained
    assert observed[0].measurement is rejected


def test_configuration_failure_retains_existing_demand():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    runtime.process_temperature(create_measurement(19))
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))

    with pytest.raises(SensorConfigurationNotFoundError):
        runtime.process_temperature(create_measurement(19, sensor_id="unknown"))

    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained


def test_observe_only_retains_demand_and_returns_without_aggregate():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    runtime.process_temperature(create_measurement(19))
    retained = runtime.zone_demand_store.get(ZoneId(value="living_room"))
    runtime.temperature_handler.control_loop = ObserveOnlyControlLoop()

    result = runtime.process_temperature(create_measurement(23))

    assert result.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND
    assert result.building_heat_demand is None
    assert result.command is None
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")) is retained


def test_source_failure_keeps_updated_demand_and_state_then_later_retries():
    clock = MutableClock()
    port = RecordingHeatSource(failures=1)
    runtime = create_runtime(port, clock=clock)
    decisions = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, decisions.append)
    first = create_measurement(19)

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(first)

    assert raised.value is port.error
    assert decisions[0].decision.observed_at is first.timestamp
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")).requires_heat is True
    assert runtime.heat_source_state_store.get() is None
    clock.current_time = NOW + timedelta(seconds=1)

    retry = runtime.process_temperature(create_measurement(19, timestamp=clock.current_time))

    assert retry.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert len(port.commands) == 2
    assert runtime.heat_source_state_store.get().command_id == retry.command.id


def test_failed_transition_retains_new_demand_and_previous_applied_state_then_retries():
    port = FailOnCallHeatSource(fail_on_call=2)
    runtime = create_runtime(port)
    enabled = runtime.process_temperature(create_measurement(19))
    previous_state = runtime.heat_source_state_store.get()

    with pytest.raises(RuntimeError):
        runtime.process_temperature(create_measurement(23))

    assert runtime.zone_demand_store.get(ZoneId(value="living_room")).requires_heat is False
    assert runtime.heat_source_state_store.get() is previous_state
    assert previous_state.command_id == enabled.command.id

    retry = runtime.process_temperature(create_measurement(23))

    assert retry.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert retry.command.action is HeatingAction.DISABLE_HEATING


def test_temperature_and_decision_events_are_published_unchanged():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    temperatures = []
    decisions = []
    runtime.event_bus.subscribe(TemperatureMeasuredEvent, temperatures.append)
    runtime.event_bus.subscribe(DecisionCreatedEvent, decisions.append)
    measurement = create_measurement(19)

    result = runtime.process_temperature(measurement)

    assert temperatures[0].measurement is measurement
    assert decisions[0] is result.decision_event


def test_observer_failure_propagates_before_demand_or_source_processing():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    error = RuntimeError("observer failed")

    def fail(_event):
        raise error

    runtime.event_bus.subscribe(DecisionCreatedEvent, fail)

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(create_measurement(19))

    assert raised.value is error
    assert runtime.zone_demand_store.list_current() == []
    assert port.commands == []


def test_temperature_handler_records_measurement_before_temperature_observer_failure():
    port = RecordingHeatSource()
    runtime = create_runtime(port)
    measurement = create_measurement(19)
    error = RuntimeError("temperature observer failed")

    def fail(_event):
        assert runtime.state_store.get_latest(measurement.sensor_id) is measurement
        raise error

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, fail)

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(measurement)

    assert raised.value is error
    assert runtime.zone_demand_store.list_current() == []
    assert port.commands == []

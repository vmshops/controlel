"""Heating module adapter for the module-neutral v0.1 scenario runner."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.control_runtime_assembly import ControlRuntimeAssembly
from controlel.application.runtime.control_runtime_startup import ControlRuntimeStartup
from controlel.application.runtime.heat_demand_evaluation_result import HeatDemandEvaluationResult
from controlel.application.runtime.runtime_processing_result import RuntimeProcessingResult
from controlel.application.services.heating_diagnostics_boundary import HeatingDiagnosticsBoundary
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.operational_event_stream import (
    OperationalEventStream,
    operational_event_to_dict,
)
from controlel.application.state.heating_diagnostics import (
    empty_heating_diagnostics_snapshot,
    heating_diagnostics_to_dict,
)
from controlel.domain.capabilities.temperature_capability import TemperatureCapability
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.entities.zone import Zone
from controlel.domain.operational_events import MeasurementEventCondition
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import ReportedSourceState, SourceCapabilities, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from controlel.simulation.adapters.heating_ports import (
    RecordingHeatSourcePort,
    RecordingScheduledFailureSink,
)
from controlel.simulation.adapters.heating_providers import (
    VirtualSourceStateProvider,
    VirtualTemperatureSensor,
)
from controlel.simulation.recorder import SimulationRecorder
from controlel.simulation.runner import TrustedSimulationAdapter
from controlel.simulation.scenario import Scenario, ScenarioTimelineItem, parse_duration
from controlel.simulation.time import DeterministicScheduler, VirtualClock

HEATING_MODULE_CONTRACT_VERSION = 1
_SUPPORTED_EVENT_FIELDS = {
    "runtime.start": frozenset(),
    "runtime.stop": frozenset(),
    "runtime.restart": frozenset(),
    "simulation.checkpoint": frozenset(),
    "sensor.temperature_observed": frozenset({"value", "observed_at"}),
    "sensor.availability_changed": frozenset({"availability", "value", "observed_at"}),
    "source.reported_state_changed": frozenset({"state", "observed_at", "transition_at"}),
    "source.command_port_changed": frozenset({"outcome", "failure_reason_code"}),
}


class HeatingScenarioConfiguration(BaseModel):
    zone_id: str
    zone_name: str
    sensor_id: str
    sensor_name: str
    target_temperature: float
    primary_measurement_max_age: timedelta
    max_future_skew: timedelta
    indeterminate_grace_period: timedelta
    indeterminate_timeout_action: HeatingAction
    heating_turn_on_differential: float = 0.0
    heating_turn_off_differential: float = 0.0
    heat_demand_confirmation_duration: timedelta = timedelta(0)
    minimum_heating_on_time: timedelta = timedelta(0)
    minimum_heating_off_time: timedelta = timedelta(0)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator(
        "primary_measurement_max_age",
        "max_future_skew",
        "indeterminate_grace_period",
        "heat_demand_confirmation_duration",
        "minimum_heating_on_time",
        "minimum_heating_off_time",
        mode="before",
    )
    @classmethod
    def parse_durations(cls, value: object, info: object) -> timedelta:
        return parse_duration(value, str(getattr(info, "field_name", "duration")))

    @model_validator(mode="after")
    def validate_values(self) -> HeatingScenarioConfiguration:
        if not self.zone_id or not self.sensor_id or not self.zone_name or not self.sensor_name:
            raise ValueError("zone and sensor identities/names must not be empty")
        if not isfinite(self.target_temperature):
            raise ValueError("target_temperature must be finite")
        if self.primary_measurement_max_age <= timedelta(0):
            raise ValueError("primary_measurement_max_age must be positive")
        for field_name in (
            "max_future_skew",
            "indeterminate_grace_period",
            "heat_demand_confirmation_duration",
            "minimum_heating_on_time",
            "minimum_heating_off_time",
        ):
            if getattr(self, field_name) < timedelta(0):
                raise ValueError(f"{field_name} must not be negative")
        return self


class HeatingInitialState(BaseModel):
    zone_temperature: float | None = None
    zone_temperature_observed_at: datetime | None = None
    source_reported_state: ReportedSourceState | None = None
    source_reported_observed_at: datetime | None = None
    source_transition_at: datetime | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("zone_temperature_observed_at", "source_reported_observed_at", "source_transition_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{getattr(info, 'field_name', 'timestamp')} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def evidence_requires_timestamps(self) -> HeatingInitialState:
        if (self.zone_temperature is None) != (self.zone_temperature_observed_at is None):
            raise ValueError("initial zone temperature and its observed_at must be supplied together")
        if (self.source_reported_state is None) != (self.source_reported_observed_at is None):
            raise ValueError("initial reported source state and its observed_at must be supplied together")
        if self.source_transition_at is not None and self.source_reported_state is None:
            raise ValueError("source_transition_at requires initial reported source state")
        return self


class HeatingSimulationAdapter(TrustedSimulationAdapter):
    """Map heating scenario evidence to existing ControlRuntime public methods."""

    adapter_version = "0.1"

    def __init__(
        self,
        scenario: Scenario,
        clock: VirtualClock,
        scheduler: DeterministicScheduler,
        recorder: SimulationRecorder,
    ) -> None:
        self.validate_scenario(scenario)
        self.scenario = scenario
        self.configuration = HeatingScenarioConfiguration.model_validate(scenario.configuration)
        self.initial_state = HeatingInitialState.model_validate(scenario.initial_state)
        self.clock = clock
        self.scheduler = scheduler
        self.recorder = recorder
        self.zone_id = ZoneId(value=self.configuration.zone_id)
        self.sensor_id = SensorId(value=self.configuration.sensor_id)
        self.sensor_repository = SensorRepository()
        self.zone_repository = ZoneRepository()
        self.sensor = Sensor(
            id=uuid5(NAMESPACE_URL, f"controlel-simulation:sensor:{self.sensor_id.value}"),
            sensor_id=self.sensor_id,
            zone_id=self.zone_id,
            name=self.configuration.sensor_name,
            capabilities=[TemperatureCapability()],
            created_at=scenario.start_at,
            updated_at=scenario.start_at,
        )
        self.zone = Zone(
            id=uuid5(NAMESPACE_URL, f"controlel-simulation:zone:{self.zone_id.value}"),
            zone_id=self.zone_id,
            primary_sensor_id=self.sensor_id,
            primary_measurement_max_age=self.configuration.primary_measurement_max_age,
            name=self.configuration.zone_name,
            target_temperature=Temperature(value=self.configuration.target_temperature),
            created_at=scenario.start_at,
            updated_at=scenario.start_at,
        )
        self.sensor_repository.add(self.sensor)
        self.zone_repository.add(self.zone)
        self.temperature_provider = VirtualTemperatureSensor(self.sensor_id)
        self.source_state_provider = VirtualSourceStateProvider()
        self.source_port = RecordingHeatSourcePort(clock, recorder)
        self.failure_sink = RecordingScheduledFailureSink(clock, recorder)
        self._operational_event_recorder: OperationalEventRecorder
        self._captured_operational_events = 0
        self.runtime = self._build_runtime()
        self.startup = ControlRuntimeStartup(self.runtime)
        self._initial_state_applied = False

    @staticmethod
    def validate_scenario(scenario: Scenario) -> None:
        if scenario.module != "heating":
            raise ValueError("HeatingSimulationAdapter requires module 'heating'")
        if scenario.module_contract_version != HEATING_MODULE_CONTRACT_VERSION:
            raise ValueError("unsupported heating module contract version")
        if not scenario.timeline:
            raise ValueError("heating scenario timeline must not be empty")
        first = scenario.timeline[0]
        if first.event.type != "runtime.start" or first.delivery_at != scenario.start_at:
            raise ValueError("v0.1 heating scenarios must start with runtime.start at start_at")
        if sum(item.event.type == "runtime.start" for item in scenario.timeline) != 1:
            raise ValueError("v0.1 heating scenarios require exactly one runtime.start event")
        for item in scenario.timeline:
            event = item.event
            allowed = _SUPPORTED_EVENT_FIELDS.get(event.type)
            if allowed is None:
                raise ValueError(f"unsupported heating scenario event: {event.type}")
            unknown = set(event.payload) - allowed
            if unknown:
                raise ValueError(f"unsupported fields for {event.type}: {', '.join(sorted(unknown))}")
            if event.type.startswith("sensor.") and event.subject != str(scenario.configuration.get("sensor_id", "")):
                raise ValueError("sensor event subject must match configured sensor_id")
            if event.type == "sensor.temperature_observed":
                _require_fields(event.payload, "value", "observed_at")
            elif event.type == "sensor.availability_changed":
                _require_fields(event.payload, "availability", "observed_at")
                availability = event.payload["availability"]
                if availability not in {"available", "unavailable"}:
                    raise ValueError("sensor availability must be available or unavailable")
                if availability == "available" and "value" not in event.payload:
                    raise ValueError("available sensor event requires an explicit value")
            elif event.type == "source.reported_state_changed":
                _require_fields(event.payload, "state", "observed_at")
            elif event.type == "source.command_port_changed":
                _require_fields(event.payload, "outcome")
                if event.payload["outcome"] not in {"succeed", "fail"}:
                    raise ValueError("source command-port outcome must be succeed or fail")
                if event.payload["outcome"] == "fail" and not event.payload.get("failure_reason_code"):
                    raise ValueError("failed source command-port outcome requires failure_reason_code")

    def dispatch(self, item: ScenarioTimelineItem) -> None:
        event = item.event
        evidence_at = _optional_payload_datetime(event.payload, "observed_at")
        self.recorder.record(
            "timeline.event",
            recorded_at=self.clock.now(),
            scheduled_for=item.delivery_at,
            delivered_at=self.clock.now(),
            evidence_at=evidence_at,
            payload={
                "event_type": event.type,
                "phase": item.phase.value,
                "sequence": item.sequence,
                "subject": event.subject,
                "event_payload": event.payload,
            },
        )

        if event.type == "runtime.start":
            self.startup.begin()
            self._capture_operational_events()
            self._apply_initial_state()
            return
        if event.type == "runtime.stop":
            self.runtime.stop()
        elif event.type == "runtime.restart":
            self.runtime.stop()
            self._capture_operational_events()
            self.runtime = self._build_runtime()
            self.startup = ControlRuntimeStartup(self.runtime)
            self.startup.begin()
        elif event.type == "sensor.temperature_observed":
            observed_at = _payload_datetime(event.payload, "observed_at")
            measurement = self.temperature_provider.observe(
                _payload_float(event.payload, "value"),
                observed_at=observed_at,
            )
            self._record_result("sensor.temperature_observed", self.runtime.process_temperature(measurement))
        elif event.type == "sensor.availability_changed":
            observed_at = _payload_datetime(event.payload, "observed_at")
            if event.payload["availability"] == "unavailable":
                self.temperature_provider.mark_unavailable(observed_at=observed_at)
                self._record_result(
                    "sensor.availability_changed",
                    self.runtime.mark_measurement_indeterminate(MeasurementEventCondition.UNAVAILABLE),
                )
            else:
                measurement = self.temperature_provider.observe(
                    _payload_float(event.payload, "value"),
                    observed_at=observed_at,
                )
                self._record_result("sensor.availability_changed", self.runtime.process_temperature(measurement))
        elif event.type == "source.reported_state_changed":
            evidence = self.source_state_provider.observe(
                ReportedSourceState(str(event.payload["state"])),
                observed_at=_payload_datetime(event.payload, "observed_at"),
                transition_at=_optional_payload_datetime(event.payload, "transition_at"),
            )
            self._record_result("source.reported_state_changed", self.runtime.ingest_reported_source_state(evidence))
        elif event.type == "source.command_port_changed":
            if event.payload["outcome"] == "succeed":
                self.source_port.configure_success()
            else:
                self.source_port.configure_failure(str(event.payload["failure_reason_code"]))
        elif event.type == "simulation.checkpoint":
            self.capture_diagnostics("checkpoint")
        else:
            raise ValueError(f"unsupported heating scenario event: {event.type}")
        self._capture_operational_events()

    def capture_after_scheduler(self) -> None:
        self._capture_operational_events()

    def capture_diagnostics(self, reason: str) -> None:
        current = empty_heating_diagnostics_snapshot(self.zone_id.value)
        projection = HeatingDiagnosticsBoundary().project(
            runtime=self.runtime,
            zone_ids=(self.zone_id,),
            current=current,
            refresh_runtime_evidence=True,
        )
        self.recorder.record(
            "diagnostics.heating",
            recorded_at=self.clock.now(),
            delivered_at=self.clock.now(),
            payload={
                "capture_reason": reason,
                "snapshot": heating_diagnostics_to_dict(projection.snapshot),
                "failure_exception_type": projection.failure_exception_type,
            },
        )

    def _build_runtime(self) -> ControlRuntime:
        self._operational_event_recorder = OperationalEventRecorder(OperationalEventStream(capacity=1000))
        self._captured_operational_events = 0
        assembly = ControlRuntimeAssembly(
            sensor_repository=self.sensor_repository,
            zone_repository=self.zone_repository,
            heat_delivery_controller=None,
            clock=self.clock,
            scheduler=self.scheduler,
            scheduled_failure_sink=self.failure_sink,
            max_future_skew=self.configuration.max_future_skew,
            indeterminate_grace_period=self.configuration.indeterminate_grace_period,
            indeterminate_timeout_action=self.configuration.indeterminate_timeout_action,
            heating_turn_on_differential=self.configuration.heating_turn_on_differential,
            heating_turn_off_differential=self.configuration.heating_turn_off_differential,
            heat_demand_confirmation_duration=self.configuration.heat_demand_confirmation_duration,
            minimum_heating_on_time=self.configuration.minimum_heating_on_time,
            minimum_heating_off_time=self.configuration.minimum_heating_off_time,
            source_ownership=SourceOwnership.CONTROLEL_OWNED,
            source_capabilities=SourceCapabilities(),
            operational_event_recorder=self._operational_event_recorder,
        )
        return assembly.build(self.source_port)

    def _apply_initial_state(self) -> None:
        if self._initial_state_applied:
            return
        self._initial_state_applied = True
        initial = self.initial_state
        if initial.source_reported_state is not None and initial.source_reported_observed_at is not None:
            evidence = self.source_state_provider.observe(
                initial.source_reported_state,
                observed_at=initial.source_reported_observed_at,
                transition_at=initial.source_transition_at,
            )
            self.recorder.record(
                "initial.source_reported_state",
                recorded_at=self.clock.now(),
                delivered_at=self.clock.now(),
                evidence_at=evidence.observed_at,
                payload={"state": evidence.state.value},
            )
            self._record_result("initial.source_reported_state", self.startup.ingest_reported_source(evidence))
            self._capture_operational_events()
        if initial.zone_temperature is not None and initial.zone_temperature_observed_at is not None:
            measurement = self.temperature_provider.observe(
                initial.zone_temperature,
                observed_at=initial.zone_temperature_observed_at,
            )
            self.recorder.record(
                "initial.temperature",
                recorded_at=self.clock.now(),
                delivered_at=self.clock.now(),
                evidence_at=measurement.timestamp,
                payload={"sensor_id": self.sensor_id.value, "value": measurement.value.value},
            )
            self._record_result("initial.temperature", self.startup.ingest_temperature(measurement))
            self._capture_operational_events()

    def _capture_operational_events(self) -> None:
        snapshot = self._operational_event_recorder.stream.snapshot()
        new_events = snapshot.events[self._captured_operational_events :]
        for event in new_events:
            self.recorder.record(
                "operational_event",
                recorded_at=event.timestamp,
                delivered_at=self.clock.now(),
                payload=operational_event_to_dict(event),
            )
        self._captured_operational_events = len(snapshot.events)

    def _record_result(self, operation: str, result: HeatDemandEvaluationResult | RuntimeProcessingResult) -> None:
        if isinstance(result, RuntimeProcessingResult):
            evaluation = result.heat_demand_evaluation
            payload: dict[str, object] = {
                "operation": operation,
                "result_type": "runtime_processing",
                "status": result.status.value,
                "reason": result.reason.value if result.reason is not None else None,
            }
        else:
            evaluation = result
            payload = {
                "operation": operation,
                "result_type": "heat_demand_evaluation",
                "status": result.status.value,
                "reason": None,
            }
        if evaluation is not None:
            payload.update(
                {
                    "trigger": evaluation.trigger.value,
                    "building_demand": evaluation.building_heat_demand.status.value,
                    "building_demand_reason": evaluation.building_heat_demand.reason.value,
                    "command_action": evaluation.command.action.value if evaluation.command is not None else None,
                    "scheduled_for": evaluation.scheduled_for,
                    "next_evaluation_at": evaluation.next_evaluation_at,
                }
            )
        self.recorder.record(
            "runtime.result",
            recorded_at=self.clock.now(),
            delivered_at=self.clock.now(),
            payload=payload,
        )


def _require_fields(payload: Mapping[str, object], *names: str) -> None:
    missing = [name for name in names if name not in payload]
    if missing:
        raise ValueError(f"missing event payload fields: {', '.join(missing)}")


def _payload_datetime(payload: Mapping[str, object], name: str) -> datetime:
    value = payload.get(name)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an aware ISO 8601 timestamp")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _optional_payload_datetime(payload: Mapping[str, object], name: str) -> datetime | None:
    return _payload_datetime(payload, name) if payload.get(name) is not None else None


def _payload_float(payload: Mapping[str, object], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)

from dataclasses import dataclass

from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.runtime.runtime_processing_result import (
    TemperatureNoDecisionReason,
)
from controlel.application.services.control_loop_service import ControlLoopService
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_temperature_aggregator import (
    ZoneTemperatureAggregator,
    ZoneTemperatureStatus,
)
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.regulation.context import ControlContext


@dataclass(frozen=True)
class TemperatureHandlingResult:
    reason: TemperatureNoDecisionReason | None
    decision_event: DecisionCreatedEvent | None

    def __post_init__(self) -> None:
        if self.reason is not None and not isinstance(self.reason, TemperatureNoDecisionReason):
            raise TypeError("reason must be a TemperatureNoDecisionReason or None")
        if self.decision_event is not None and not isinstance(self.decision_event, DecisionCreatedEvent):
            raise TypeError("decision_event must be a DecisionCreatedEvent or None")
        if (self.reason is None) == (self.decision_event is None):
            raise ValueError("exactly one of reason or decision_event is required")


class TemperatureEventHandler:
    """
    Handles incoming temperature measurements.
    """

    def __init__(
        self,
        state_store: RuntimeStateStore,
        target_resolver: ZoneTargetResolver,
        temperature_aggregator: ZoneTemperatureAggregator,
        timestamp_validator: MeasurementTimestampValidator,
    ):
        self.state_store = state_store
        self.target_resolver = target_resolver
        self.temperature_aggregator = temperature_aggregator
        self.timestamp_validator = timestamp_validator
        self.control_loop = ControlLoopService()

    def handle(self, event: TemperatureMeasuredEvent) -> TemperatureHandlingResult:
        if not self.timestamp_validator.is_admissible(event.measurement):
            return TemperatureHandlingResult(
                reason=TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED,
                decision_event=None,
            )

        if not self.state_store.record(event.measurement):
            return TemperatureHandlingResult(
                reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
                decision_event=None,
            )

        zone = self.target_resolver.resolve(event.measurement.sensor_id)
        temperature_result = self.temperature_aggregator.get_effective(zone)

        no_decision_reasons = {
            ZoneTemperatureStatus.MISSING: TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_MISSING,
            ZoneTemperatureStatus.EXPIRED: TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED,
            ZoneTemperatureStatus.FUTURE_DATED: TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_FUTURE_DATED,
        }
        if temperature_result.status in no_decision_reasons:
            return TemperatureHandlingResult(
                reason=no_decision_reasons[temperature_result.status],
                decision_event=None,
            )

        if event.measurement.sensor_id != zone.primary_sensor_id:
            return TemperatureHandlingResult(
                reason=TemperatureNoDecisionReason.SECONDARY_MEASUREMENT,
                decision_event=None,
            )

        effective_measurement = temperature_result.measurement
        if effective_measurement is None:
            raise RuntimeError("EFFECTIVE zone temperature result must contain a measurement")

        context = ControlContext(
            sensor_id=effective_measurement.sensor_id,
            zone_id=zone.zone_id,
            observed_at=effective_measurement.timestamp,
            current_temperature=effective_measurement.value,
            target_temperature=zone.target_temperature,
        )

        return TemperatureHandlingResult(
            reason=None,
            decision_event=self.control_loop.process(context),
        )

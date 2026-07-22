from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.services.control_loop_service import ControlLoopService
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_temperature_aggregator import (
    ZoneTemperatureAggregator,
)
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.regulation.context import ControlContext


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

    def handle(self, event: TemperatureMeasuredEvent):
        if not self.timestamp_validator.is_admissible(event.measurement):
            return None

        if not self.state_store.record(event.measurement):
            return None

        zone = self.target_resolver.resolve(event.measurement.sensor_id)
        effective_measurement = self.temperature_aggregator.get_effective(zone)

        if effective_measurement is None:
            return None

        if event.measurement.sensor_id != zone.primary_sensor_id:
            return None

        context = ControlContext(
            sensor_id=effective_measurement.sensor_id,
            zone_id=zone.zone_id,
            current_temperature=effective_measurement.value,
            target_temperature=zone.target_temperature,
        )

        return self.control_loop.process(context)

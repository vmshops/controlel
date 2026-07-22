from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.services.control_loop_service import ControlLoopService
from controlel.application.state.runtime_state_store import RuntimeStateStore
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
    ):
        self.state_store = state_store
        self.target_resolver = target_resolver
        self.control_loop = ControlLoopService()

    def handle(self, event: TemperatureMeasuredEvent):
        if not self.state_store.record(event.measurement):
            return None

        target_temperature = self.target_resolver.resolve(event.measurement.sensor_id)

        context = ControlContext(
            current_temperature=event.measurement.value,
            target_temperature=target_temperature,
        )

        return self.control_loop.process(context)

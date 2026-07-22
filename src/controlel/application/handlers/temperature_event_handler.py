from controlel.application.services.control_loop_service import ControlLoopService
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


class TemperatureEventHandler:
    """
    Handles incoming temperature measurements.
    """

    def __init__(
        self,
        state_store: RuntimeStateStore,
        target_temperature: Temperature,
    ):
        self.state_store = state_store
        self.target_temperature = target_temperature
        self.control_loop = ControlLoopService()

    def handle(self, event: TemperatureMeasuredEvent):
        if not self.state_store.record(event.measurement):
            return None

        context = ControlContext(
            current_temperature=event.measurement.value,
            target_temperature=self.target_temperature,
        )

        return self.control_loop.process(context)

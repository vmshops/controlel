from controlel.application.services.control_loop_service import ControlLoopService
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


class TemperatureEventHandler:
    """
    Handles incoming temperature measurements.
    """

    def __init__(self):
        self.control_loop = ControlLoopService()

    def handle(self, event: TemperatureMeasuredEvent):
        target_temperature = event.measurement.target

        if target_temperature is None:
            target_temperature = Temperature(21)

        context = ControlContext(
            current_temperature=event.measurement.value,
            target_temperature=target_temperature,
        )

        return self.control_loop.process(context)

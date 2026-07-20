from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)


class ControlRuntime:
    """
    Composition root for the control system.
    Connects events, handlers and services.
    """

    def __init__(self):
        self.event_bus = EventBus()

        self.temperature_handler = TemperatureEventHandler()

        self.event_bus.subscribe(
            TemperatureMeasuredEvent,
            self.temperature_handler.handle,
        )

    def process_temperature(self, measurement):
        event = TemperatureMeasuredEvent(
            measurement=measurement,
        )

        return self.event_bus.publish(event)

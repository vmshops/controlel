from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


class ControlRuntime:
    """
    Composition root for the control system.
    Connects events, handlers and services.
    """

    def __init__(self, target_temperature: Temperature):
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()

        self.temperature_handler = TemperatureEventHandler(
            state_store=self.state_store,
            target_temperature=target_temperature,
        )

        self.event_bus.subscribe(
            TemperatureMeasuredEvent,
            self.temperature_handler.handle,
        )

    def process_temperature(self, measurement: Measurement):
        event = TemperatureMeasuredEvent(
            measurement=measurement,
        )

        return self.event_bus.publish(event)

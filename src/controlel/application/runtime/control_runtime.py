from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.decision_event_handler import DecisionEventHandler
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.services.command_dispatcher import CommandDispatcher
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.events.decision_event import DecisionCreatedEvent
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

    def __init__(
        self,
        target_temperature: Temperature,
        actuator: ActuatorPort,
    ):
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()
        self.decision_handler = DecisionEventHandler()
        self.command_dispatcher = CommandDispatcher(actuator=actuator)

        self.temperature_handler = TemperatureEventHandler(
            state_store=self.state_store,
            target_temperature=target_temperature,
        )

    def process_temperature(
        self,
        measurement: Measurement,
    ) -> DecisionCreatedEvent | None:
        event = TemperatureMeasuredEvent(
            measurement=measurement,
        )

        decision_event = self.temperature_handler.handle(event)
        self.event_bus.publish(event)

        if decision_event is None:
            return None

        self.event_bus.publish(decision_event)

        command = self.decision_handler.handle(decision_event)
        if command is not None:
            self.command_dispatcher.dispatch(command)

        return decision_event

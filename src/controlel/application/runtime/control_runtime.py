from collections.abc import Mapping
from datetime import timedelta

from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.decision_event_handler import DecisionEventHandler
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
)
from controlel.application.services.command_dispatcher import CommandDispatcher
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.services.zone_actuator_router import ZoneActuatorRouter
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_temperature_aggregator import (
    ZoneTemperatureAggregator,
)
from controlel.application.time.clock import Clock
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.zone_id import ZoneId


class ControlRuntime:
    """
    Composition root for the control system.
    Connects events, handlers and services.
    """

    def __init__(
        self,
        sensor_repository: SensorRepository,
        zone_repository: ZoneRepository,
        actuator_routes: Mapping[ZoneId, ActuatorPort],
        clock: Clock,
        max_future_skew: timedelta,
    ) -> None:
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()
        self.control_state_repository = StateRepository()
        self.decision_handler = DecisionEventHandler()
        self.actuator_router = ZoneActuatorRouter(actuator_routes)
        self.command_dispatcher = CommandDispatcher(
            actuator_router=self.actuator_router,
            state_repository=self.control_state_repository,
        )
        self.target_resolver = ZoneTargetResolver(
            sensor_repository=sensor_repository,
            zone_repository=zone_repository,
        )
        self.temperature_aggregator = ZoneTemperatureAggregator(
            state_store=self.state_store,
            sensor_repository=sensor_repository,
            clock=clock,
        )
        self.timestamp_validator = MeasurementTimestampValidator(
            clock=clock,
            max_future_skew=max_future_skew,
        )

        self.temperature_handler = TemperatureEventHandler(
            state_store=self.state_store,
            target_resolver=self.target_resolver,
            temperature_aggregator=self.temperature_aggregator,
            timestamp_validator=self.timestamp_validator,
        )

    def process_temperature(
        self,
        measurement: Measurement,
    ) -> RuntimeProcessingResult:
        event = TemperatureMeasuredEvent(
            measurement=measurement,
        )

        handling_result = self.temperature_handler.handle(event)
        self.event_bus.publish(event)

        if handling_result.reason is not None:
            return RuntimeProcessingResult(
                status=RuntimeProcessingStatus.NO_DECISION,
                reason=handling_result.reason,
            )

        decision_event = handling_result.decision_event
        if decision_event is None:
            raise RuntimeError("Decision handling result must contain a decision event")

        self.event_bus.publish(decision_event)

        command = self.decision_handler.handle(decision_event)
        if command is None:
            return RuntimeProcessingResult(
                status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
                decision_event=decision_event,
            )

        executed = self.command_dispatcher.dispatch(command)
        return RuntimeProcessingResult(
            status=(
                RuntimeProcessingStatus.COMMAND_EXECUTED if executed else RuntimeProcessingStatus.COMMAND_SUPPRESSED
            ),
            decision_event=decision_event,
            command=command,
        )

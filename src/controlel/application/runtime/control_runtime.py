from datetime import timedelta

from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.handlers.zone_demand_handler import ZoneDemandHandler
from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
)
from controlel.application.services.heat_source_command_dispatcher import (
    HeatSourceCommandDispatcher,
)
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.state.heat_demand_aggregator import HeatDemandAggregator
from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.application.state.zone_temperature_aggregator import (
    ZoneTemperatureAggregator,
)
from controlel.application.time.clock import Clock
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository


class ControlRuntime:
    """
    Composition root for the control system.
    Connects events, handlers and services.
    """

    def __init__(
        self,
        sensor_repository: SensorRepository,
        zone_repository: ZoneRepository,
        heat_source_port: HeatSourcePort,
        clock: Clock,
        max_future_skew: timedelta,
    ) -> None:
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()
        self.zone_demand_store = ZoneDemandStore()
        self.heat_source_state_store = HeatSourceStateStore()
        self.zone_demand_handler = ZoneDemandHandler()
        self.heat_demand_aggregator = HeatDemandAggregator(
            demand_store=self.zone_demand_store,
            zone_repository=zone_repository,
            clock=clock,
        )
        self.heat_source_command_dispatcher = HeatSourceCommandDispatcher(
            heat_source_port=heat_source_port,
            state_store=self.heat_source_state_store,
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

        zone_demand = self.zone_demand_handler.handle(decision_event)
        if zone_demand is None:
            return RuntimeProcessingResult(
                status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
                decision_event=decision_event,
            )

        self.zone_demand_store.record(zone_demand)
        building_heat_demand = self.heat_demand_aggregator.evaluate()
        if building_heat_demand.status is BuildingHeatDemandStatus.INDETERMINATE:
            return RuntimeProcessingResult(
                status=RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE,
                decision_event=decision_event,
                building_heat_demand=building_heat_demand,
            )

        action_by_status = {
            BuildingHeatDemandStatus.HEAT_REQUIRED: HeatingAction.ENABLE_HEATING,
            BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatingAction.DISABLE_HEATING,
        }
        command = HeatSourceCommand(
            command_type=CommandFamily.HEATING,
            action=action_by_status[building_heat_demand.status],
        )
        executed = self.heat_source_command_dispatcher.dispatch(command)
        return RuntimeProcessingResult(
            status=(
                RuntimeProcessingStatus.COMMAND_EXECUTED if executed else RuntimeProcessingStatus.COMMAND_SUPPRESSED
            ),
            decision_event=decision_event,
            building_heat_demand=building_heat_demand,
            command=command,
        )

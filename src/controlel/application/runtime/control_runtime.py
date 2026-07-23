from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Lock

from controlel.application.configuration.zone_target_resolver import (
    ZoneTargetResolver,
)
from controlel.application.events.event_bus import EventBus
from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.handlers.zone_demand_handler import ZoneDemandHandler
from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.ports.scheduled_runtime_failure_sink import (
    ScheduledRuntimeFailure,
    ScheduledRuntimeFailureSink,
)
from controlel.application.ports.scheduler import ScheduledTaskHandle, Scheduler
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
)
from controlel.application.runtime.runtime_lifecycle import (
    RuntimeReentrancyError,
    RuntimeStoppedError,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
)
from controlel.application.services.heat_demand_deadline_calculator import (
    HeatDemandDeadlineCalculator,
)
from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandSafetyPhase,
    HeatDemandSafetyPolicy,
)
from controlel.application.services.heat_source_command_dispatcher import (
    HeatSourceCommandDispatcher,
)
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.state.heat_demand_aggregator import HeatDemandAggregator
from controlel.application.state.heat_demand_safety_state_store import (
    HeatDemandSafetyStateStore,
)
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
    """Composition root for explicit control and shared-source orchestration."""

    def __init__(
        self,
        sensor_repository: SensorRepository,
        zone_repository: ZoneRepository,
        heat_source_port: HeatSourcePort,
        clock: Clock,
        scheduler: Scheduler,
        scheduled_failure_sink: ScheduledRuntimeFailureSink,
        max_future_skew: timedelta,
        indeterminate_grace_period: timedelta,
        indeterminate_timeout_action: HeatingAction,
    ) -> None:
        self.clock = clock
        self.scheduler = scheduler
        self.scheduled_failure_sink = scheduled_failure_sink
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()
        self.zone_demand_store = ZoneDemandStore()
        self.heat_demand_safety_state_store = HeatDemandSafetyStateStore()
        self.heat_source_state_store = HeatSourceStateStore()
        self.zone_demand_handler = ZoneDemandHandler()
        self.heat_demand_aggregator = HeatDemandAggregator(
            demand_store=self.zone_demand_store,
            zone_repository=zone_repository,
            clock=clock,
        )
        self.heat_demand_safety_policy = HeatDemandSafetyPolicy(
            grace_period=indeterminate_grace_period,
            timeout_action=indeterminate_timeout_action,
        )
        self.heat_demand_deadline_calculator = HeatDemandDeadlineCalculator(
            demand_store=self.zone_demand_store,
            zone_repository=zone_repository,
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

        self._scheduled_handle: ScheduledTaskHandle | None = None
        self._scheduled_deadline: datetime | None = None
        self._schedule_generation = 0
        self._execution_lock = Lock()
        self._active_operation: str | None = None
        self._stopped = False

    def start(self) -> HeatDemandEvaluationResult:
        with self._runtime_operation("start"):
            return self._evaluate_heat_demand(HeatDemandEvaluationTrigger.STARTUP)

    def reevaluate_heat_demand(self) -> HeatDemandEvaluationResult:
        with self._runtime_operation("reevaluate_heat_demand"):
            return self._evaluate_heat_demand(HeatDemandEvaluationTrigger.MANUAL)

    def process_temperature(
        self,
        measurement: Measurement,
    ) -> RuntimeProcessingResult:
        with self._runtime_operation("process_temperature"):
            return self._process_temperature(measurement)

    def stop(self) -> None:
        with self._runtime_operation("stop"):
            if self._stopped:
                return

            self._stopped = True
            self._schedule_generation += 1
            handle = self._scheduled_handle
            self._scheduled_handle = None
            self._scheduled_deadline = None
            if handle is not None:
                handle.cancel()

    @contextmanager
    def _runtime_operation(
        self,
        operation: str,
        *,
        allow_stopped: bool = False,
    ) -> Iterator[None]:
        if not self._execution_lock.acquire(blocking=False):
            active_operation = self._active_operation
            if active_operation is None:
                active_operation = "unknown"
            raise RuntimeReentrancyError(
                active_operation=active_operation,
                attempted_operation=operation,
            )

        self._active_operation = operation
        try:
            if operation != "stop" and not allow_stopped and self._stopped:
                raise RuntimeStoppedError("ControlRuntime has been stopped")
            yield
        finally:
            self._active_operation = None
            self._execution_lock.release()

    def _process_temperature(
        self,
        measurement: Measurement,
    ) -> RuntimeProcessingResult:
        event = TemperatureMeasuredEvent(measurement=measurement)

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
        evaluation = self._evaluate_heat_demand(
            HeatDemandEvaluationTrigger.ACTIONABLE_DECISION,
        )
        runtime_status_by_evaluation = {
            HeatDemandEvaluationStatus.INDETERMINATE_GRACE: (
                RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE
            ),
            HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED: RuntimeProcessingStatus.COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED: RuntimeProcessingStatus.COMMAND_SUPPRESSED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED: RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED: RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED,
        }
        return RuntimeProcessingResult(
            status=runtime_status_by_evaluation[evaluation.status],
            decision_event=decision_event,
            heat_demand_evaluation=evaluation,
        )

    def _evaluate_heat_demand(
        self,
        trigger: HeatDemandEvaluationTrigger,
        scheduled_for: datetime | None = None,
        indeterminate_start_hint: datetime | None = None,
    ) -> HeatDemandEvaluationResult:
        building_heat_demand = self.heat_demand_aggregator.evaluate()
        safety_assessment = self.heat_demand_safety_policy.evaluate(
            demand=building_heat_demand,
            current_state=self.heat_demand_safety_state_store.get(),
            indeterminate_start_hint=indeterminate_start_hint,
        )
        self.heat_demand_safety_state_store.save(safety_assessment.state)

        eligibility_deadline = self.heat_demand_deadline_calculator.next_eligibility_change_at(building_heat_demand)
        grace_deadline = (
            safety_assessment.timeout_at
            if safety_assessment.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE
            else None
        )
        deadlines = [deadline for deadline in (eligibility_deadline, grace_deadline) if deadline is not None]
        next_evaluation_at = min(deadlines) if deadlines else None
        self._replace_scheduled_evaluation(next_evaluation_at)

        command: HeatSourceCommand | None = None
        if safety_assessment.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE:
            status = HeatDemandEvaluationStatus.INDETERMINATE_GRACE
        else:
            if safety_assessment.phase is HeatDemandSafetyPhase.DETERMINATE:
                action = {
                    BuildingHeatDemandStatus.HEAT_REQUIRED: HeatingAction.ENABLE_HEATING,
                    BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatingAction.DISABLE_HEATING,
                }[building_heat_demand.status]
                executed_status = HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED
                suppressed_status = HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED
            else:
                action = safety_assessment.action
                if action is None:
                    raise RuntimeError("Timed-out safety assessment must contain an action")
                executed_status = HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
                suppressed_status = HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED

            command = HeatSourceCommand(
                command_type=CommandFamily.HEATING,
                action=action,
            )
            executed = self.heat_source_command_dispatcher.dispatch(command)
            status = executed_status if executed else suppressed_status

        return HeatDemandEvaluationResult(
            trigger=trigger,
            status=status,
            building_heat_demand=building_heat_demand,
            safety_assessment=safety_assessment,
            command=command,
            scheduled_for=scheduled_for,
            next_evaluation_at=next_evaluation_at,
        )

    def _replace_scheduled_evaluation(
        self,
        deadline: datetime | None,
    ) -> None:
        if deadline is not None and (deadline.tzinfo is None or deadline.utcoffset() is None):
            raise ValueError("scheduled deadline must be timezone-aware")

        if deadline == self._scheduled_deadline and self._scheduled_handle is not None:
            return

        old_handle = self._scheduled_handle
        if deadline is None:
            self._schedule_generation += 1
            self._scheduled_handle = None
            self._scheduled_deadline = None
            if old_handle is not None:
                old_handle.cancel()
            return

        generation = self._schedule_generation + 1

        def callback() -> None:
            self._scheduled_callback(deadline, generation)

        new_handle = self.scheduler.schedule_at(deadline, callback)
        self._schedule_generation = generation
        self._scheduled_handle = new_handle
        self._scheduled_deadline = deadline

        if old_handle is not None:
            old_handle.cancel()

    def _scheduled_callback(
        self,
        scheduled_for: datetime,
        generation: int,
    ) -> None:
        if self._stopped or generation < self._schedule_generation:
            return

        try:
            with self._runtime_operation(
                "scheduled_callback",
                allow_stopped=True,
            ):
                if (
                    self._stopped
                    or generation != self._schedule_generation
                    or self._scheduled_handle is None
                    or self._scheduled_deadline != scheduled_for
                ):
                    return

                self._consume_scheduled_evaluation(
                    scheduled_for=scheduled_for,
                )
        except Exception as error:
            self.scheduled_failure_sink.report(
                ScheduledRuntimeFailure(
                    scheduled_for=scheduled_for,
                    error=error,
                )
            )

    def _consume_scheduled_evaluation(
        self,
        scheduled_for: datetime,
    ) -> None:
        self._schedule_generation += 1
        self._scheduled_handle = None
        self._scheduled_deadline = None

        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Clock.now() must return a timezone-aware datetime")
        if now < scheduled_for:
            self._replace_scheduled_evaluation(scheduled_for)
            return

        self._evaluate_heat_demand(
            trigger=HeatDemandEvaluationTrigger.SCHEDULED,
            scheduled_for=scheduled_for,
            indeterminate_start_hint=scheduled_for,
        )

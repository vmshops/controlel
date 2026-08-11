from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
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
from controlel.application.runtime.fatal_shutdown_result import (
    FatalShutdownEmergencyOutcome,
    FatalShutdownResult,
)
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
from controlel.application.services.demand_arbitrator import (
    DemandArbitrator,
    MultiZoneDemandArbitrator,
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
from controlel.application.services.heating_episode_observer import (
    HeatingEpisodeObservationErrorEvidence,
    HeatingEpisodeObserver,
    heat_delivery_observation_from_state,
    heat_source_observation_from_state,
)
from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.application.services.shadow_heating_performance_monitor import (
    ShadowHeatingPerformanceMonitor,
)
from controlel.application.services.source_control_policy import (
    SourceControlAssessment,
    SourceControlOutcome,
    SourceControlPolicy,
)
from controlel.application.services.temperature_hysteresis_policy import (
    TemperatureHysteresisAssessment,
    TemperatureHysteresisPolicy,
)
from controlel.application.services.zone_heat_delivery_controller import (
    ZoneHeatDeliveryController,
)
from controlel.application.services.zone_heat_demand_confirmation_policy import (
    ZoneHeatDemandConfirmationAssessment,
    ZoneHeatDemandConfirmationPolicy,
)
from controlel.application.state.heat_demand_aggregator import HeatDemandAggregator
from controlel.application.state.heat_demand_safety_state_store import (
    HeatDemandSafetyStateStore,
)
from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.source_control_state import SourceControlState
from controlel.application.state.temperature_hysteresis_state import (
    HysteresisDemandState,
    TemperatureHysteresisState,
)
from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.application.state.zone_heat_demand_confirmation_state import (
    ZoneHeatDemandConfirmationPhase,
    ZoneHeatDemandConfirmationState,
)
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
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import ZoneHeatDemandInput, ZoneHeatDemandInputReason
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.heat_delivery import (
    HeatingEpisodeTerminationReason,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.zone_id import ZoneId


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
        heating_turn_on_differential: float = 0.0,
        heating_turn_off_differential: float = 0.0,
        heat_demand_confirmation_duration: timedelta = timedelta(0),
        minimum_heating_on_time: timedelta = timedelta(0),
        minimum_heating_off_time: timedelta = timedelta(0),
        demand_arbitrator: DemandArbitrator | None = None,
        heat_delivery_controller: ZoneHeatDeliveryController | None = None,
    ) -> None:
        self.clock = clock
        self.scheduler = scheduler
        self.scheduled_failure_sink = scheduled_failure_sink
        self.event_bus = EventBus()
        self.state_store = RuntimeStateStore()
        self.zone_repository = zone_repository
        self.heat_delivery_controller = heat_delivery_controller
        self.heating_episode_observer = HeatingEpisodeObserver()
        self.heating_episode_observation_error: str | None = None
        self.heating_episode_observation_errors: dict[ZoneId, str] = {}
        self.heating_episode_observation_error_evidence: dict[ZoneId, HeatingEpisodeObservationErrorEvidence] = {}
        self.heating_episode_observation_global_error_evidence: HeatingEpisodeObservationErrorEvidence | None = None
        self.heating_performance_monitor = ShadowHeatingPerformanceMonitor()
        self.zone_demand_store = ZoneDemandStore()
        self.heat_demand_safety_state_store = HeatDemandSafetyStateStore()
        self.heat_source_state_store = HeatSourceStateStore()
        self.zone_demand_handler = ZoneDemandHandler()
        self.heat_demand_aggregator = HeatDemandAggregator(
            demand_store=self.zone_demand_store,
            zone_repository=zone_repository,
            clock=clock,
        )
        self.demand_arbitrator = demand_arbitrator if demand_arbitrator is not None else MultiZoneDemandArbitrator()
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
        self.temperature_hysteresis_policy = TemperatureHysteresisPolicy(
            turn_on_differential=heating_turn_on_differential,
            turn_off_differential=heating_turn_off_differential,
        )
        self.zone_heat_demand_confirmation_policy = ZoneHeatDemandConfirmationPolicy(
            confirmation_duration=heat_demand_confirmation_duration,
        )
        self.source_control_policy = SourceControlPolicy(
            minimum_on_time=minimum_heating_on_time,
            minimum_off_time=minimum_heating_off_time,
        )
        self.temperature_hysteresis_state: TemperatureHysteresisState | None = None
        self.temperature_hysteresis_assessment: TemperatureHysteresisAssessment | None = None
        self.temperature_hysteresis_states: dict[ZoneId, TemperatureHysteresisState] = {}
        self.temperature_hysteresis_assessments: dict[ZoneId, TemperatureHysteresisAssessment] = {}
        self.zone_heat_demand_confirmation_state: ZoneHeatDemandConfirmationState | None = None
        self.zone_heat_demand_confirmation_assessment: ZoneHeatDemandConfirmationAssessment | None = None
        self.zone_heat_demand_confirmation_states: dict[ZoneId, ZoneHeatDemandConfirmationState] = {}
        self.zone_heat_demand_confirmation_assessments: dict[ZoneId, ZoneHeatDemandConfirmationAssessment] = {}
        self._zone_confirmation_inputs: dict[ZoneId, BuildingHeatDemandStatus] = {}
        self._last_processed_zone_id: ZoneId | None = None
        self.source_control_state: SourceControlState | None = None
        self.source_control_assessment: SourceControlAssessment | None = None
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
        self._fatal_shutdown_result: FatalShutdownResult | None = None

    def start(self) -> HeatDemandEvaluationResult:
        with self._runtime_operation("start"):
            return self._evaluate_heat_demand(HeatDemandEvaluationTrigger.STARTUP)

    def reevaluate_heat_demand(self) -> HeatDemandEvaluationResult:
        with self._runtime_operation("reevaluate_heat_demand"):
            return self._evaluate_heat_demand(HeatDemandEvaluationTrigger.MANUAL)

    def mark_measurement_indeterminate(self) -> HeatDemandEvaluationResult:
        """Invalidate current zone input and reevaluate through safety policy."""

        with self._runtime_operation("mark_measurement_indeterminate"):
            self.zone_demand_store.clear()
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
            if self.source_control_state is not None:
                self.source_control_state = self.source_control_policy.stopped_state(
                    self.source_control_state,
                    now=self.source_control_state.last_evaluated_at,
                )
            now = self.clock.now()
            self._terminate_heating_episodes(
                ended_at=now,
                reason=HeatingEpisodeTerminationReason.RUNTIME_STOPPED,
            )
            self.zone_heat_demand_confirmation_states = {
                zone_id: self.zone_heat_demand_confirmation_policy.stopped_state(state, now=now)
                for zone_id, state in self.zone_heat_demand_confirmation_states.items()
            }
            self.zone_heat_demand_confirmation_state = self._representative_confirmation_state(
                fallback=self.zone_heat_demand_confirmation_policy.stopped_state(
                    self.zone_heat_demand_confirmation_state,
                    now=now,
                )
            )

    def fatal_shutdown(
        self,
        original_failed_action: HeatingAction | None,
        requested_at: datetime,
    ) -> FatalShutdownResult:
        """Enter terminal state and make at most one emergency disable request."""

        if original_failed_action is not None and not isinstance(
            original_failed_action,
            HeatingAction,
        ):
            raise TypeError("original_failed_action must be a HeatingAction or None")
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")

        with self._runtime_operation("fatal_shutdown", allow_stopped=True):
            if self._fatal_shutdown_result is not None:
                return self._fatal_shutdown_result

            self._stopped = True
            self._schedule_generation += 1
            handle = self._scheduled_handle
            self._scheduled_handle = None
            self._scheduled_deadline = None
            if handle is not None:
                try:
                    handle.cancel()
                except Exception:
                    pass
            self.source_control_state = self.source_control_policy.fatal_state(
                self.source_control_state,
                now=requested_at,
            )
            self._terminate_heating_episodes(
                ended_at=requested_at,
                reason=HeatingEpisodeTerminationReason.FATAL_SHUTDOWN,
            )
            self.zone_heat_demand_confirmation_states = {
                zone_id: self.zone_heat_demand_confirmation_policy.fatal_state(state, now=requested_at)
                for zone_id, state in self.zone_heat_demand_confirmation_states.items()
            }
            self.zone_heat_demand_confirmation_state = self._representative_confirmation_state(
                fallback=self.zone_heat_demand_confirmation_policy.fatal_state(
                    self.zone_heat_demand_confirmation_state,
                    now=requested_at,
                )
            )

            if original_failed_action is HeatingAction.DISABLE_HEATING:
                result = FatalShutdownResult(
                    emergency_disable_attempted=False,
                    emergency_disable_outcome=(FatalShutdownEmergencyOutcome.DISABLE_SKIPPED_ALREADY_FAILED),
                    timestamp=requested_at,
                    original_failed_action=original_failed_action,
                )
            else:
                command = HeatSourceCommand(
                    command_type=CommandFamily.HEATING,
                    action=HeatingAction.DISABLE_HEATING,
                )
                try:
                    self.heat_source_command_dispatcher.dispatch_emergency(command)
                except Exception as error:
                    result = FatalShutdownResult(
                        emergency_disable_attempted=True,
                        emergency_disable_outcome=(FatalShutdownEmergencyOutcome.DISABLE_FAILED),
                        timestamp=requested_at,
                        original_failed_action=original_failed_action,
                        emergency_failure_type=type(error).__name__,
                    )
                else:
                    result = FatalShutdownResult(
                        emergency_disable_attempted=True,
                        emergency_disable_outcome=(FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED),
                        timestamp=requested_at,
                        original_failed_action=original_failed_action,
                    )

            self._fatal_shutdown_result = result
            return result

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

        zone = self.target_resolver.resolve(measurement.sensor_id)
        self._last_processed_zone_id = zone.zone_id
        hysteresis = self.temperature_hysteresis_policy.evaluate(
            current_temperature=measurement.value.value,
            target_temperature=zone.target_temperature.value,
            raw_requires_heat=zone_demand.requires_heat,
            current_state=self.temperature_hysteresis_states.get(zone.zone_id),
        )
        self.temperature_hysteresis_states[zone.zone_id] = hysteresis.state
        self.temperature_hysteresis_assessments[zone.zone_id] = hysteresis
        self.temperature_hysteresis_state = hysteresis.state
        self.temperature_hysteresis_assessment = hysteresis
        self.zone_demand_store.record(
            ZoneDemand(
                zone_id=zone_demand.zone_id,
                requires_heat=(hysteresis.state.demand is HysteresisDemandState.HEAT_REQUIRED),
                source_sensor_id=zone_demand.source_sensor_id,
                observed_at=zone_demand.observed_at,
            )
        )
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
            HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED: RuntimeProcessingStatus.COMMAND_DEFERRED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED: RuntimeProcessingStatus.SAFETY_COMMAND_DEFERRED,
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
        aggregate_demand = self.heat_demand_aggregator.evaluate()
        previous_pending_zone_ids = {
            zone_id
            for zone_id, state in self.zone_heat_demand_confirmation_states.items()
            if state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
        }
        active_zone_ids = {item.zone_id for item in aggregate_demand.zone_inputs}
        self.zone_heat_demand_confirmation_states = {
            zone_id: state
            for zone_id, state in self.zone_heat_demand_confirmation_states.items()
            if zone_id in active_zone_ids
        }
        self.zone_heat_demand_confirmation_assessments = {
            zone_id: assessment
            for zone_id, assessment in self.zone_heat_demand_confirmation_assessments.items()
            if zone_id in active_zone_ids
        }
        self._zone_confirmation_inputs = {
            zone_id: demand for zone_id, demand in self._zone_confirmation_inputs.items() if zone_id in active_zone_ids
        }
        confirmation_assessments = dict(self.zone_heat_demand_confirmation_assessments)
        evaluated_zone_ids: list[ZoneId] = []
        confirmed_inputs = []
        for zone_input in aggregate_demand.zone_inputs:
            current_state = self.zone_heat_demand_confirmation_states.get(zone_input.zone_id)
            deadline_reevaluation = (
                trigger is HeatDemandEvaluationTrigger.SCHEDULED
                and current_state is not None
                and current_state.confirmation_deadline == scheduled_for
            )
            input_changed = self._zone_confirmation_inputs.get(zone_input.zone_id) is not zone_input.demand
            current_zone_event = (
                trigger is HeatDemandEvaluationTrigger.ACTIONABLE_DECISION
                and zone_input.zone_id == self._last_processed_zone_id
            )
            if (
                current_state is None
                or input_changed
                or deadline_reevaluation
                or current_zone_event
                or trigger in {HeatDemandEvaluationTrigger.STARTUP, HeatDemandEvaluationTrigger.MANUAL}
            ):
                assessment = self.zone_heat_demand_confirmation_policy.evaluate(
                    hysteresis_demand=zone_input.demand,
                    now=aggregate_demand.evaluated_at,
                    current_state=current_state,
                    deadline_reevaluation=deadline_reevaluation,
                )
                self.zone_heat_demand_confirmation_states[zone_input.zone_id] = assessment.state
                confirmation_assessments[zone_input.zone_id] = assessment
                evaluated_zone_ids.append(zone_input.zone_id)
            else:
                assessment = confirmation_assessments[zone_input.zone_id]
            self._zone_confirmation_inputs[zone_input.zone_id] = zone_input.demand
            confirmed_inputs.append(
                zone_input.model_copy(
                    update={
                        "demand": assessment.output_demand,
                        "preserves_confirmed_heat": (
                            assessment.output_demand is BuildingHeatDemandStatus.INDETERMINATE
                            and assessment.state.confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
                        ),
                    }
                )
            )
        self.zone_heat_demand_confirmation_assessments = confirmation_assessments
        representative_zone_id = self._representative_zone_id(
            tuple(evaluated_zone_ids) or tuple(confirmation_assessments),
            scheduled_for=scheduled_for,
        )
        confirmation_assessment = (
            confirmation_assessments.get(representative_zone_id) if representative_zone_id is not None else None
        )
        self.zone_heat_demand_confirmation_assessment = confirmation_assessment
        self.zone_heat_demand_confirmation_state = (
            confirmation_assessment.state if confirmation_assessment is not None else None
        )
        confirmed_aggregate_demand = aggregate_demand.model_copy(update={"zone_inputs": tuple(confirmed_inputs)})
        if self.heat_delivery_controller is not None:
            for zone_input in confirmed_inputs:
                zone = self.zone_repository.get(zone_input.zone_id)
                measurement = (
                    self.state_store.get_latest(zone.primary_sensor_id)
                    if zone_input.reason is ZoneHeatDemandInputReason.ELIGIBLE
                    else None
                )
                self.heat_delivery_controller.evaluate_zone(
                    zone_id=zone_input.zone_id,
                    confirmed_demand=zone_input.demand,
                    zone_target_temperature=zone.target_temperature.value,
                    valid_zone_measurement_temperature=(measurement.value.value if measurement is not None else None),
                    now=aggregate_demand.evaluated_at,
                )
        confirmed_aggregate_demand = MultiZoneDemandArbitrator().resolve(confirmed_aggregate_demand)
        building_heat_demand = self.demand_arbitrator.resolve(confirmed_aggregate_demand)
        safety_assessment = self.heat_demand_safety_policy.evaluate(
            demand=building_heat_demand,
            current_state=self.heat_demand_safety_state_store.get(),
            indeterminate_start_hint=indeterminate_start_hint,
        )
        self.heat_demand_safety_state_store.save(safety_assessment.state)

        eligibility_deadline = self.heat_demand_deadline_calculator.next_eligibility_change_at(building_heat_demand)
        confirmation_deadlines = [
            state.confirmation_deadline
            for state in self.zone_heat_demand_confirmation_states.values()
            if state.confirmation_deadline is not None
        ]
        confirmation_deadline = min(confirmation_deadlines) if confirmation_deadlines else None
        current_pending_zone_ids = {
            zone_id
            for zone_id, state in self.zone_heat_demand_confirmation_states.items()
            if state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
        }
        confirmation_callback_invalidated = bool(previous_pending_zone_ids - current_pending_zone_ids)
        grace_deadline = (
            safety_assessment.timeout_at
            if safety_assessment.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE
            else None
        )

        command: HeatSourceCommand | None = None
        source_assessment: SourceControlAssessment | None = None
        if safety_assessment.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE:
            status = HeatDemandEvaluationStatus.INDETERMINATE_GRACE
            deadlines = [
                deadline
                for deadline in (
                    eligibility_deadline,
                    grace_deadline,
                    confirmation_deadline,
                )
                if deadline is not None
            ]
            next_evaluation_at = min(deadlines) if deadlines else None
            self._replace_scheduled_evaluation(
                next_evaluation_at,
                force=confirmation_callback_invalidated,
            )
        else:
            if safety_assessment.phase is HeatDemandSafetyPhase.DETERMINATE:
                action = {
                    BuildingHeatDemandStatus.HEAT_REQUIRED: HeatingAction.ENABLE_HEATING,
                    BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatingAction.DISABLE_HEATING,
                }[building_heat_demand.status]
                executed_status = HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED
                suppressed_status = HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED
                deferred_status = HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED
                safety_command = False
            else:
                action = safety_assessment.action
                if action is None:
                    raise RuntimeError("Timed-out safety assessment must contain an action")
                executed_status = HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
                suppressed_status = HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED
                deferred_status = HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED
                safety_command = True

            command = HeatSourceCommand(
                command_type=CommandFamily.HEATING,
                action=action,
            )
            source_assessment = self.source_control_policy.evaluate(
                desired_command=action,
                now=building_heat_demand.evaluated_at,
                current_state=self.source_control_state,
                safety_command=safety_command,
                lockout_expiry_reevaluation=(
                    trigger is HeatDemandEvaluationTrigger.SCHEDULED
                    and self.source_control_state is not None
                    and self.source_control_state.next_reevaluation_deadline == scheduled_for
                ),
            )
            self.source_control_state = source_assessment.state
            self.source_control_assessment = source_assessment
            source_deadline = self.source_control_state.next_reevaluation_deadline
            deadlines = [
                deadline
                for deadline in (
                    eligibility_deadline,
                    grace_deadline,
                    confirmation_deadline,
                    source_deadline,
                )
                if deadline is not None
            ]
            next_evaluation_at = min(deadlines) if deadlines else None
            self._replace_scheduled_evaluation(
                next_evaluation_at,
                force=confirmation_callback_invalidated,
            )
            if source_assessment.outcome is SourceControlOutcome.DEFER:
                status = deferred_status
            elif source_assessment.outcome is SourceControlOutcome.SUPPRESS_DUPLICATE:
                status = suppressed_status
            else:
                try:
                    executed = self.heat_source_command_dispatcher.dispatch(command)
                except Exception:
                    self.source_control_state = self.source_control_policy.record_failed(
                        source_assessment,
                        failed_at=building_heat_demand.evaluated_at,
                    )
                    self.source_control_assessment = replace(
                        source_assessment,
                        state=self.source_control_state,
                    )
                    self._observe_heating_episodes(
                        tuple(confirmed_inputs),
                        captured_at=building_heat_demand.evaluated_at,
                    )
                    raise
                if executed:
                    self.source_control_state = self.source_control_policy.record_dispatched(
                        source_assessment,
                        dispatched_at=building_heat_demand.evaluated_at,
                        safety_command=safety_command,
                    )
                    source_assessment = replace(
                        source_assessment,
                        state=self.source_control_state,
                    )
                    self.source_control_assessment = source_assessment
                    status = executed_status
                else:
                    self.source_control_state = self.source_control_policy.record_suppressed_duplicate(
                        source_assessment,
                        evaluated_at=building_heat_demand.evaluated_at,
                    )
                    source_assessment = replace(
                        source_assessment,
                        state=self.source_control_state,
                    )
                    self.source_control_assessment = source_assessment
                    status = suppressed_status

        self._observe_heating_episodes(
            tuple(confirmed_inputs),
            captured_at=building_heat_demand.evaluated_at,
        )
        return HeatDemandEvaluationResult(
            trigger=trigger,
            status=status,
            building_heat_demand=building_heat_demand,
            safety_assessment=safety_assessment,
            command=command,
            scheduled_for=scheduled_for,
            next_evaluation_at=next_evaluation_at,
            hysteresis_assessment=self.temperature_hysteresis_assessment,
            confirmation_assessment=confirmation_assessment,
            source_control_assessment=source_assessment,
        )

    def _observe_heating_episodes(
        self,
        zone_inputs: tuple[ZoneHeatDemandInput, ...],
        *,
        captured_at: datetime,
    ) -> None:
        """Observe completed control facts without influencing control behavior."""

        try:
            source_observation = heat_source_observation_from_state(
                self.source_control_state,
                captured_at=captured_at,
            )
        except Exception as error:
            self.heating_episode_observation_errors = {}
            self.heating_episode_observation_error = f"{type(error).__name__}: {error}"
            self.heating_episode_observation_error_evidence = {}
            self.heating_episode_observation_global_error_evidence = HeatingEpisodeObservationErrorEvidence(
                zone_id=None,
                evidence_at=captured_at,
                exception_type=type(error).__name__,
            )
            return

        errors: dict[ZoneId, str] = {}
        error_evidence: dict[ZoneId, HeatingEpisodeObservationErrorEvidence] = {}
        for zone_input in zone_inputs:
            try:
                zone = self.zone_repository.get(zone_input.zone_id)
                latest = self.state_store.get_latest(zone.primary_sensor_id)
                zone_temperature = self._zone_temperature_observation(
                    zone_input.reason,
                    latest,
                )
                actuator_observations = (
                    tuple(
                        heat_delivery_observation_from_state(state, captured_at=captured_at)
                        for state in self.heat_delivery_controller.states_for_zone(zone_input.zone_id)
                    )
                    if self.heat_delivery_controller is not None
                    else ()
                )
                episode = self.heating_episode_observer.observe(
                    zone_id=zone_input.zone_id,
                    confirmed_demand=zone_input.demand,
                    target_temperature=zone.target_temperature.value,
                    zone_temperature=zone_temperature,
                    actuator_observations=actuator_observations,
                    source_observation=source_observation,
                    captured_at=captured_at,
                )
                if episode is not None and episode.ended_at is not None:
                    self.heating_performance_monitor.submit_episode(episode)
            except Exception as error:
                errors[zone_input.zone_id] = f"{type(error).__name__}: {error}"
                error_evidence[zone_input.zone_id] = HeatingEpisodeObservationErrorEvidence(
                    zone_id=zone_input.zone_id,
                    evidence_at=captured_at,
                    exception_type=type(error).__name__,
                )

        self.heating_episode_observation_errors = errors
        self.heating_episode_observation_error_evidence = error_evidence
        self.heating_episode_observation_global_error_evidence = None
        self.heating_episode_observation_error = (
            "; ".join(
                f"{zone_id.value}: {error}" for zone_id, error in sorted(errors.items(), key=lambda item: item[0].value)
            )
            or None
        )

    def _terminate_heating_episodes(
        self,
        *,
        ended_at: datetime,
        reason: HeatingEpisodeTerminationReason,
    ) -> None:
        try:
            episodes = self.heating_episode_observer.terminate_all(
                ended_at=ended_at,
                reason=reason,
            )
            for episode in episodes:
                self.heating_performance_monitor.submit_episode(episode)
            self.heating_episode_observation_global_error_evidence = None
        except Exception as error:
            self.heating_episode_observation_error = f"{type(error).__name__}: {error}"
            self.heating_episode_observation_global_error_evidence = HeatingEpisodeObservationErrorEvidence(
                zone_id=None,
                evidence_at=ended_at,
                exception_type=type(error).__name__,
            )

    @staticmethod
    def _zone_temperature_observation(
        reason: ZoneHeatDemandInputReason,
        measurement: Measurement | None,
    ) -> ObservedValue[float]:
        if measurement is None or reason is ZoneHeatDemandInputReason.MISSING:
            return ObservedValue.unknown("zone measurement is missing")
        if reason is ZoneHeatDemandInputReason.ELIGIBLE:
            return ObservedValue.valid(measurement.value.value, measurement.timestamp)
        if reason is ZoneHeatDemandInputReason.EXPIRED:
            return ObservedValue(
                value=measurement.value.value,
                observed_at=measurement.timestamp,
                quality=ObservationQuality.STALE,
                reason="zone measurement is expired",
            )
        return ObservedValue(
            value=measurement.value.value,
            observed_at=measurement.timestamp,
            quality=ObservationQuality.CONFLICTING,
            reason="zone measurement is future-dated",
        )

    def _representative_zone_id(
        self,
        zone_ids: tuple[ZoneId, ...],
        *,
        scheduled_for: datetime | None,
    ) -> ZoneId | None:
        if scheduled_for is not None:
            matching = sorted(
                (
                    zone_id
                    for zone_id in zone_ids
                    if self.zone_heat_demand_confirmation_states[zone_id].confirmation_deadline == scheduled_for
                ),
                key=lambda zone_id: zone_id.value,
            )
            if matching:
                return matching[0]
        if self._last_processed_zone_id in zone_ids:
            return self._last_processed_zone_id
        return min(zone_ids, key=lambda zone_id: zone_id.value) if zone_ids else None

    def _representative_confirmation_state(
        self,
        *,
        fallback: ZoneHeatDemandConfirmationState,
    ) -> ZoneHeatDemandConfirmationState:
        zone_id = self._representative_zone_id(
            tuple(self.zone_heat_demand_confirmation_states),
            scheduled_for=None,
        )
        return self.zone_heat_demand_confirmation_states.get(zone_id, fallback)

    def _replace_scheduled_evaluation(
        self,
        deadline: datetime | None,
        *,
        force: bool = False,
    ) -> None:
        if deadline is not None and (deadline.tzinfo is None or deadline.utcoffset() is None):
            raise ValueError("scheduled deadline must be timezone-aware")

        if not force and deadline == self._scheduled_deadline and self._scheduled_handle is not None:
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

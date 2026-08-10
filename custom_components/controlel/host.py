"""Home Assistant lifecycle and serialized ControlRuntime ownership."""

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.fatal_shutdown_result import (
    FatalShutdownEmergencyOutcome,
    FatalShutdownResult,
)
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
)
from controlel.application.runtime.runtime_lifecycle import (
    RuntimeReentrancyError,
    RuntimeStoppedError,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandSafetyPhase,
)
from controlel.application.state.source_control_state import (
    SourceControlState as CoreSourceControlState,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.measurements.measurement import Measurement

from .config import HomeAssistantIntegrationConfig
from .const import INTEGRATION_VERSION
from .failure_sink import HomeAssistantScheduledFailureSink
from .heat_source import HomeAssistantServiceCallError
from .measurement_ingestion import (
    HomeAssistantMeasurementMapper,
    MeasurementRejectionReason,
    StateLike,
    StateVersion,
)
from .observability import (
    PROFILE_REFRESH_CADENCE_SECONDS,
    ObservabilityController,
)
from .operational import (
    TRACE_LIMITS,
    ActiveLockoutType,
    CommandOutcome,
    ConfirmationState,
    DecisionCode,
    DecisionReason,
    DecisionTraceRecord,
    EmergencyDisableOutcome,
    HeatDemandState,
    MeasurementStatus,
    OperationalSnapshotSource,
    RuntimeStatus,
    SafetyState,
    SourceControlState,
    initial_snapshot,
)
from .runtime_executor import (
    HomeAssistantRuntimeExecutor,
    RuntimeExecutorClosedError,
)

type Unsubscribe = Callable[[], None]
type StateListener = Callable[[StateLike | None], None]
type StateSubscriber = Callable[[object, str, StateListener], Unsubscribe]
type StateGetter = Callable[[str], StateLike | None]
type ShutdownSubscriber = Callable[[object, Callable[[], None]], Unsubscribe]
type IntervalSubscriber = Callable[
    [object, Callable[[datetime], None], timedelta],
    Unsubscribe,
]
_MEASUREMENT_UNSET = object()


class HomeAssistantTaskOwner(Protocol):
    def async_create_task(
        self,
        target: Coroutine[Any, Any, Any],
        name: str | None = None,
    ) -> asyncio.Task[Any]: ...


class HomeAssistantControlelHost:
    """Own one runtime and every path by which Home Assistant can enter it."""

    def __init__(
        self,
        hass: HomeAssistantTaskOwner,
        runtime: ControlRuntime,
        executor: HomeAssistantRuntimeExecutor,
        measurement_mapper: HomeAssistantMeasurementMapper,
        failure_sink: HomeAssistantScheduledFailureSink,
        config: HomeAssistantIntegrationConfig,
        core_version: str,
        logger: logging.Logger,
        state_subscriber: StateSubscriber | None = None,
        state_getter: StateGetter | None = None,
        shutdown_subscriber: ShutdownSubscriber | None = None,
        interval_subscriber: IntervalSubscriber | None = None,
    ) -> None:
        self._hass = hass
        self._runtime = runtime
        self._executor = executor
        self._measurement_mapper = measurement_mapper
        self._failure_sink = failure_sink
        self._config = config
        self._temperature_entity_id = config.temperature_entity_id
        self._logger = logger
        self._state_subscriber = state_subscriber or _default_state_subscriber
        self._state_getter = state_getter or self._default_state_getter
        self._shutdown_subscriber = shutdown_subscriber or _default_shutdown_subscriber
        self._interval_subscriber = interval_subscriber or _default_interval_subscriber
        diagnostic = config.diagnostic_configuration
        self.snapshot_source = OperationalSnapshotSource(
            initial_snapshot(
                zone_name=config.zone_name,
                zone_id=config.zone_id.value,
                sensor_name=config.sensor_name,
                sensor_id=config.sensor_id.value,
                temperature_entity_id=config.temperature_entity_id,
                target_temperature=config.target_temperature.value,
                heating_turn_on_differential=config.heating_turn_on_differential,
                heating_turn_off_differential=config.heating_turn_off_differential,
                heat_demand_confirmation_duration_seconds=(config.heat_demand_confirmation_duration.total_seconds()),
                primary_measurement_max_age_seconds=config.primary_measurement_max_age.total_seconds(),
                sensor_failure_grace_period_seconds=config.indeterminate_grace_period.total_seconds(),
                minimum_heating_on_time_seconds=config.minimum_heating_on_time.total_seconds(),
                minimum_heating_off_time_seconds=config.minimum_heating_off_time.total_seconds(),
                timeout_action=config.indeterminate_timeout_action.value,
                diagnostic_profile=diagnostic.profile,
                diagnostic_refresh_cadence_seconds=PROFILE_REFRESH_CADENCE_SECONDS[diagnostic.profile],
                debug_expiry_deadline=None,
                debug_profile_duration_seconds=(diagnostic.configured_debug_duration.total_seconds()),
                trace_capacity=TRACE_LIMITS[diagnostic.profile],
                integration_version=INTEGRATION_VERSION,
                core_version=core_version,
            ),
            trace_limit=TRACE_LIMITS[diagnostic.profile],
        )
        self.observability = ObservabilityController(
            hass=hass,
            source=self.snapshot_source,
            configured_profile=diagnostic.profile,
            profile_before_debug=diagnostic.profile_before_debug,
            debug_duration=diagnostic.debug_duration,
            interval_subscriber=self._interval_subscriber,
            logger=logger,
        )
        self._failure_sink.bind_state_handlers(
            recoverable=self._on_recoverable_failure_state,
            fatal=self._on_fatal_failure_state,
        )

        self._lifecycle_lock = asyncio.Lock()
        self._buffer: deque[StateLike | None] = deque()
        self._live_queue: deque[StateLike | None] = deque()
        self._unsubscribe: Unsubscribe | None = None
        self._unsubscribe_shutdown: Unsubscribe | None = None
        self._live_drain_task: asyncio.Task[Any] | None = None
        self._accepted_callback_tasks: set[asyncio.Task[Any]] = set()
        self._fatal_shutdown_task: asyncio.Task[Any] | None = None
        self._fatal_error: Exception | None = None
        self._last_state_version: StateVersion | None = None
        self._accepting = True
        self._buffering = True
        self._initialized = False
        self._stopping = False
        self._stopped = False

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def stopped(self) -> bool:
        return self._stopped

    async def async_initialize(self) -> None:
        async with self._lifecycle_lock:
            if self._initialized:
                raise RuntimeError("Controlel host is already initialized")
            if self._stopping or self._stopped:
                raise RuntimeError("Controlel host cannot initialize after shutdown")

            self._unsubscribe = self._state_subscriber(
                self._hass,
                self._temperature_entity_id,
                self._on_state_change,
            )
            self._unsubscribe_shutdown = self._shutdown_subscriber(
                self._hass,
                self._on_home_assistant_stop,
            )
            snapshot = self._state_getter(self._temperature_entity_id)

            try:
                startup_result = await self._executor.async_submit(self._runtime.start)
            except HomeAssistantServiceCallError as error:
                self._handle_synchronous_failure(error)
            except Exception as error:
                self._handle_synchronous_failure(error)
                raise
            else:
                now = datetime.now(UTC)
                self.snapshot_source.update(
                    now=now,
                    runtime_status=RuntimeStatus.ACTIVE,
                    trace_record=self._trace_record(
                        code=DecisionCode.RUNTIME_STARTED,
                        reason=DecisionReason.RUNTIME_LIFECYCLE,
                        timestamp=now,
                    ),
                )
                if isinstance(startup_result, HeatDemandEvaluationResult):
                    self._observe_evaluation_result(startup_result)
                if startup_result is not None:
                    self._log_evaluation_result(startup_result)

            if snapshot is not None:
                await self._async_process_state_now(snapshot)
            await self._async_drain_setup_buffer()
            if self._fatal_error is not None:
                raise self._fatal_error
            self._buffering = False
            self._initialized = True
            self._failure_sink.clear_fatal_issue_after_successful_reload()
            self.observability.start()
            self._logger.info("Controlel runtime started")

    async def async_process_state(
        self,
        state: StateLike | None,
    ) -> RuntimeProcessingResult | None:
        if not self._accepting:
            return None
        if self._buffering:
            self._buffer.append(state)
            return None
        return await self._async_process_state_now(state)

    async def async_reevaluate(self) -> HeatDemandEvaluationResult:
        if not self._accepting:
            raise RuntimeStoppedError("Controlel host is not accepting work")
        try:
            result = await self._executor.async_submit(self._runtime.reevaluate_heat_demand)
        except Exception as error:
            self._handle_synchronous_failure(error)
            raise
        self._observe_evaluation_result(result)
        self._log_evaluation_result(result)
        return result

    def submit_scheduled_callback(
        self,
        callback: Callable[[], None],
    ) -> None:
        """Accept a timer callback on the HA loop without running core code there."""
        if not self._accepting:
            return
        task = self._create_task(
            self._async_run_scheduled_callback(callback),
            "Controlel scheduled runtime callback",
        )
        self._accepted_callback_tasks.add(task)
        task.add_done_callback(self._accepted_callback_tasks.discard)

    def request_fatal_shutdown(self, error: Exception) -> None:
        """Coordinate terminal shutdown on the HA loop after a fatal failure."""
        if self._stopping or self._stopped or self._fatal_error is not None:
            return
        self._logger.error(
            "Stopping Controlel after fatal runtime failure",
            exc_info=(type(error), error, error.__traceback__),
        )
        self._accepting = False
        self._fatal_error = error
        self.observability.stop()
        now = datetime.now(UTC)
        self.snapshot_source.update(
            now=now,
            runtime_status=RuntimeStatus.FATAL_ERROR,
            safety_state=SafetyState.FATAL_ERROR,
            source_control_state=SourceControlState.FATAL_ERROR,
            aggregate_demand=None,
            active_lockout_deadline=None,
            active_lockout_remaining_seconds=None,
            confirmation_state=ConfirmationState.FATAL_ERROR,
            confirmation_started_at=None,
            confirmation_deadline=None,
            minimum_on_deadline=None,
            minimum_off_deadline=None,
            active_lockout_type=None,
            lockout_remaining_seconds=None,
            deferred_command=None,
            deferred_reason=None,
            deferred_since=None,
            deferred_deadline=None,
            deferred_remaining_seconds=None,
            safety_bypassed_lockout=True,
            fatal_failure_active=True,
            emergency_disable_attempted=False,
            emergency_disable_outcome=EmergencyDisableOutcome.REQUESTED,
            emergency_disable_timestamp=now,
            original_fatal_cause=type(error).__name__,
            last_command_outcome=CommandOutcome.FAILED_FATAL,
            last_command_timestamp=now,
            last_command_failure_type=type(error).__name__,
            trace_record=self._trace_record(
                code=DecisionCode.COMMAND_FAILED,
                reason=DecisionReason.FATAL_RUNTIME_FAILURE,
                timestamp=now,
                outcome=CommandOutcome.FAILED_FATAL,
                safety=SafetyState.FATAL_ERROR,
            ),
        )
        self._logger.warning("Emergency heating-off command requested")
        self._fatal_shutdown_task = self._create_task(
            self._async_fatal_shutdown(error, now),
            "Controlel fatal runtime shutdown",
        )

    async def _async_fatal_shutdown(
        self,
        error: Exception,
        requested_at: datetime,
    ) -> None:
        failed_action = getattr(error, "action", None)
        if not isinstance(failed_action, HeatingAction):
            failed_action = None

        fatal_shutdown = getattr(self._runtime, "fatal_shutdown", None)
        if not callable(fatal_shutdown) or self._executor.closed:
            self._record_fatal_emergency_outcome(
                requested_at=requested_at,
                outcome=EmergencyDisableOutcome.NO_COMMAND_PATH_AVAILABLE,
                attempted=False,
                failure_type=None,
            )
        else:
            try:
                result = await self._executor.async_submit(
                    fatal_shutdown,
                    failed_action,
                    requested_at,
                )
            except Exception as emergency_error:
                self._record_fatal_emergency_outcome(
                    requested_at=requested_at,
                    outcome=EmergencyDisableOutcome.FAILED,
                    attempted=True,
                    failure_type=type(emergency_error).__name__,
                )
            else:
                if not isinstance(result, FatalShutdownResult):
                    self._record_fatal_emergency_outcome(
                        requested_at=requested_at,
                        outcome=EmergencyDisableOutcome.NO_COMMAND_PATH_AVAILABLE,
                        attempted=False,
                        failure_type=None,
                    )
                else:
                    outcome = {
                        FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED: (EmergencyDisableOutcome.DISPATCHED),
                        FatalShutdownEmergencyOutcome.DISABLE_FAILED: (EmergencyDisableOutcome.FAILED),
                        FatalShutdownEmergencyOutcome.DISABLE_SKIPPED_ALREADY_FAILED: (
                            EmergencyDisableOutcome.SKIPPED_ALREADY_FAILED
                        ),
                    }[result.emergency_disable_outcome]
                    self._record_fatal_emergency_outcome(
                        requested_at=result.timestamp,
                        outcome=outcome,
                        attempted=result.emergency_disable_attempted,
                        failure_type=result.emergency_failure_type,
                    )

        await self.async_stop()

    def _record_fatal_emergency_outcome(
        self,
        *,
        requested_at: datetime,
        outcome: EmergencyDisableOutcome,
        attempted: bool,
        failure_type: str | None,
    ) -> None:
        code = {
            EmergencyDisableOutcome.DISPATCHED: (DecisionCode.FATAL_SHUTDOWN_DISABLE_DISPATCHED),
            EmergencyDisableOutcome.FAILED: DecisionCode.FATAL_SHUTDOWN_DISABLE_FAILED,
            EmergencyDisableOutcome.SKIPPED_ALREADY_FAILED: (
                DecisionCode.FATAL_SHUTDOWN_DISABLE_SKIPPED_ALREADY_FAILED
            ),
            EmergencyDisableOutcome.NO_COMMAND_PATH_AVAILABLE: (DecisionCode.FATAL_SHUTDOWN_NO_COMMAND_PATH_AVAILABLE),
        }[outcome]
        command_outcome = (
            CommandOutcome.DISPATCHED if outcome is EmergencyDisableOutcome.DISPATCHED else CommandOutcome.FAILED_FATAL
        )
        requested = HeatingAction.DISABLE_HEATING.value if attempted else None
        self.snapshot_source.update(
            now=requested_at,
            runtime_status=RuntimeStatus.FATAL_ERROR,
            safety_state=SafetyState.FATAL_ERROR,
            source_control_state=SourceControlState.FATAL_ERROR,
            aggregate_demand=None,
            active_lockout_deadline=None,
            active_lockout_remaining_seconds=None,
            confirmation_state=ConfirmationState.FATAL_ERROR,
            confirmation_started_at=None,
            confirmation_deadline=None,
            minimum_on_deadline=None,
            minimum_off_deadline=None,
            active_lockout_type=None,
            lockout_remaining_seconds=None,
            deferred_command=None,
            deferred_reason=None,
            deferred_since=None,
            deferred_deadline=None,
            deferred_remaining_seconds=None,
            safety_bypassed_lockout=True,
            fatal_failure_active=True,
            emergency_disable_attempted=attempted,
            emergency_disable_outcome=outcome,
            emergency_disable_timestamp=requested_at,
            last_requested_command=requested,
            last_command_outcome=command_outcome,
            last_command_timestamp=requested_at,
            last_command_failure_type=failure_type,
            trace_record=replace(
                self._trace_record(
                    code=code,
                    reason=DecisionReason.FATAL_RUNTIME_FAILURE,
                    timestamp=requested_at,
                    requested=requested,
                    outcome=command_outcome,
                    safety=SafetyState.FATAL_ERROR,
                ),
                emergency_disable_outcome=outcome,
            ),
        )
        wording = {
            EmergencyDisableOutcome.DISPATCHED: ("Emergency heating-off command dispatched"),
            EmergencyDisableOutcome.FAILED: "Emergency heating-off command failed",
            EmergencyDisableOutcome.SKIPPED_ALREADY_FAILED: (
                "Emergency heating-off command failed; recursive request skipped"
            ),
            EmergencyDisableOutcome.NO_COMMAND_PATH_AVAILABLE: ("Unable to request emergency heating-off command"),
        }[outcome]
        if outcome is EmergencyDisableOutcome.DISPATCHED:
            self._logger.warning(wording)
        else:
            self._logger.error(wording)

    async def async_stop(self) -> None:
        async with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopping = True
            self._accepting = False
            self.observability.stop()

            unsubscribe = self._unsubscribe
            self._unsubscribe = None
            if unsubscribe is not None:
                try:
                    unsubscribe()
                except Exception:
                    self._logger.exception("Failed to unsubscribe Controlel state listener")

            unsubscribe_shutdown = self._unsubscribe_shutdown
            self._unsubscribe_shutdown = None
            if unsubscribe_shutdown is not None:
                try:
                    unsubscribe_shutdown()
                except Exception:
                    self._logger.exception("Failed to unsubscribe Controlel shutdown listener")

            drain_task = self._live_drain_task
            if drain_task is not None and drain_task is not asyncio.current_task():
                await asyncio.gather(drain_task, return_exceptions=True)

            callback_tasks = [task for task in self._accepted_callback_tasks if task is not asyncio.current_task()]
            if callback_tasks:
                await asyncio.gather(*callback_tasks, return_exceptions=True)

            if not self._executor.closed:
                try:
                    await self._executor.async_submit(self._runtime.stop)
                except RuntimeExecutorClosedError:
                    pass
                except Exception as error:
                    self._logger.exception("Controlel runtime stop failed; continuing cleanup")
                    self._failure_sink.handle_synchronous_failure(error)
                finally:
                    await self._executor.async_close()

            self._buffer.clear()
            self._live_queue.clear()
            self._buffering = False
            self._stopping = False
            self._stopped = True
            now = datetime.now(UTC)
            if self._fatal_error is None:
                self.snapshot_source.update(
                    now=now,
                    runtime_status=RuntimeStatus.STOPPED,
                    safety_state=SafetyState.STOPPED,
                    source_control_state=SourceControlState.STOPPED,
                    active_lockout_type=None,
                    active_lockout_deadline=None,
                    active_lockout_remaining_seconds=None,
                    lockout_remaining_seconds=None,
                    deferred_command=None,
                    deferred_reason=None,
                    deferred_since=None,
                    deferred_deadline=None,
                    deferred_remaining_seconds=None,
                    confirmation_state=ConfirmationState.STOPPED,
                    confirmation_started_at=None,
                    confirmation_deadline=None,
                    grace_deadline=None,
                    trace_record=self._trace_record(
                        code=DecisionCode.RUNTIME_STOPPED,
                        reason=DecisionReason.RUNTIME_LIFECYCLE,
                        timestamp=now,
                    ),
                )
            self.snapshot_source.close()
            self._logger.info("Controlel runtime stopped")

    def clear_transient_issues(self) -> None:
        self._failure_sink.clear_transient_issues()

    def _on_state_change(self, state: StateLike | None) -> None:
        if not self._accepting:
            return
        if self._buffering:
            self._buffer.append(state)
            return

        self._live_queue.append(state)
        if self._live_drain_task is None or self._live_drain_task.done():
            self._live_drain_task = self._create_task(
                self._async_drain_live_queue(),
                "Controlel temperature state processing",
            )

    def _on_home_assistant_stop(self) -> None:
        if self._stopping or self._stopped:
            return
        self._create_task(
            self.async_stop(),
            "Controlel Home Assistant shutdown",
        )

    async def _async_drain_setup_buffer(self) -> None:
        while self._buffer:
            await self._async_process_state_now(self._buffer.popleft())

    async def _async_drain_live_queue(self) -> None:
        while self._live_queue:
            await self._async_process_state_now(self._live_queue.popleft())

    async def _async_process_state_now(
        self,
        state: StateLike | None,
    ) -> RuntimeProcessingResult | None:
        version = self._measurement_mapper.state_version(state)
        if version is not None and version == self._last_state_version:
            self._logger.debug("Discarded exact duplicate Controlel state version")
            return None
        self._last_state_version = version

        mapping = self._measurement_mapper.map_state(state)
        if mapping.measurement is None:
            self._observe_rejected_state(state, mapping.rejection_reason)
            result = await self._executor.async_submit(self._runtime.mark_measurement_indeterminate)
            if isinstance(result, HeatDemandEvaluationResult):
                self._observe_evaluation_result(result)
            self._logger.debug(
                "Rejected Home Assistant temperature state reason=%s",
                mapping.rejection_reason,
            )
            return None

        try:
            result = await self._executor.async_submit(
                self._runtime.process_temperature,
                mapping.measurement,
            )
        except RuntimeStoppedError as error:
            if self._stopping or self._stopped:
                self._logger.debug("Ignored temperature state during Controlel shutdown")
                return None
            self._handle_synchronous_failure(error)
            raise
        except Exception as error:
            self._handle_synchronous_failure(error)
            if isinstance(error, HomeAssistantServiceCallError):
                self._observe_service_failure(error, mapping.measurement)
                return None
            raise

        self._observe_processing_result(result, mapping.measurement)
        if result.status is RuntimeProcessingStatus.NO_DECISION and result.reason in {
            TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED,
            TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED,
            TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_FUTURE_DATED,
        }:
            indeterminate = await self._executor.async_submit(self._runtime.mark_measurement_indeterminate)
            self._observe_evaluation_result(indeterminate)
        self._logger.debug(
            "Accepted Controlel measurement timestamp=%s processing_status=%s",
            mapping.measurement.timestamp,
            result.status,
        )
        self._log_processing_result(result)
        return result

    async def _async_run_scheduled_callback(
        self,
        callback: Callable[[], None],
    ) -> None:
        if not self._accepting:
            return
        heat_source_state_store = getattr(self._runtime, "heat_source_state_store", None)
        previous_state = heat_source_state_store.get() if heat_source_state_store is not None else None
        previous_failure = self._failure_sink.last_failure
        try:
            await self._executor.async_submit(callback)
        except RuntimeExecutorClosedError:
            if not self._stopping and not self._stopped:
                raise
        else:
            if heat_source_state_store is not None:
                self._observe_scheduled_state(previous_state, previous_failure)

    def _handle_synchronous_failure(self, error: Exception) -> None:
        self._failure_sink.handle_synchronous_failure(error)
        if isinstance(error, HomeAssistantServiceCallError):
            return
        if isinstance(error, RuntimeStoppedError) and (self._stopping or self._stopped):
            return
        if isinstance(error, RuntimeReentrancyError):
            self.request_fatal_shutdown(error)

    def _observe_rejected_state(
        self,
        state: StateLike | None,
        reason: MeasurementRejectionReason | None,
    ) -> None:
        now = datetime.now(UTC)
        status_by_reason = {
            MeasurementRejectionReason.MISSING_STATE: MeasurementStatus.NOT_RECEIVED,
            MeasurementRejectionReason.UNKNOWN: MeasurementStatus.UNKNOWN,
            MeasurementRejectionReason.UNAVAILABLE: MeasurementStatus.UNAVAILABLE,
        }
        status = status_by_reason.get(reason, MeasurementStatus.INVALID_VALUE)
        timestamp = state.last_updated if state is not None else None
        if timestamp is not None and (timestamp.tzinfo is None or timestamp.utcoffset() is None):
            timestamp = None
        self.snapshot_source.update(
            now=now,
            current_temperature=None,
            measurement_status=status,
            latest_input_status=status,
            measurement_timestamp=timestamp,
            last_meaningful_event_at=now,
        )

    def _observe_processing_result(
        self,
        result: RuntimeProcessingResult,
        measurement: Measurement,
    ) -> None:
        now = datetime.now(UTC)
        base: dict[str, Any] = {
            "current_temperature": measurement.value.value,
            "measurement_status": MeasurementStatus.VALID,
            "latest_input_status": MeasurementStatus.VALID,
            "measurement_timestamp": measurement.timestamp,
            "last_meaningful_event_at": now,
        }
        if result.status is RuntimeProcessingStatus.NO_DECISION:
            if result.reason in {
                TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED,
                TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_FUTURE_DATED,
            }:
                base.update(
                    current_temperature=None,
                    measurement_status=MeasurementStatus.FUTURE_TIMESTAMP,
                    latest_input_status=MeasurementStatus.FUTURE_TIMESTAMP,
                    demand_reason=DecisionReason.MEASUREMENT_FUTURE_TIMESTAMP,
                )
            elif result.reason is TemperatureNoDecisionReason.PRIMARY_MEASUREMENT_EXPIRED:
                base.update(
                    current_temperature=None,
                    measurement_status=MeasurementStatus.STALE,
                    latest_input_status=MeasurementStatus.STALE,
                    zone_heat_demand=HeatDemandState.INDETERMINATE,
                    demand_reason=DecisionReason.MEASUREMENT_STALE,
                )
            self.snapshot_source.update(now=now, **base)
            return

        decision_event = result.decision_event
        if decision_event is None:
            self.snapshot_source.update(now=now, **base)
            return
        decision = decision_event.decision
        demand = (
            HeatDemandState.HEAT_REQUIRED
            if decision.action.value == HeatingAction.ENABLE_HEATING.value
            else HeatDemandState.NO_HEAT_REQUIRED
        )
        reason = (
            DecisionReason.TEMPERATURE_BELOW_TARGET
            if demand is HeatDemandState.HEAT_REQUIRED
            else DecisionReason.TEMPERATURE_AT_OR_ABOVE_TARGET
        )
        base.update(
            raw_zone_heat_demand=demand,
            demand_reason=reason,
            active_demand_cause=reason,
        )
        evaluation = result.heat_demand_evaluation
        if evaluation is None:
            code = (
                DecisionCode.HEAT_REQUESTED
                if demand is HeatDemandState.HEAT_REQUIRED
                else DecisionCode.HEAT_NOT_REQUIRED
            )
            trace = self._trace_record(
                code=code,
                reason=reason,
                timestamp=decision.timestamp,
                measured=measurement.value.value,
                demand=demand,
            )
        else:
            evaluation_changes, trace = self._evaluation_observation(
                evaluation,
                measured=measurement.value.value,
                reason=reason,
                timestamp=decision.timestamp,
            )
            base.update(evaluation_changes)
        self._log_demand_transition(
            self.snapshot_source.current.zone_heat_demand,
            demand,
            reason,
        )
        self.snapshot_source.update(
            now=now,
            trace_record=trace,
            **base,
        )

    def _observe_evaluation_result(
        self,
        result: HeatDemandEvaluationResult,
    ) -> None:
        reason = self._reason_from_building_demand(result)
        changes, trace = self._evaluation_observation(
            result,
            measured=self.snapshot_source.current.current_temperature,
            reason=reason,
            timestamp=result.building_heat_demand.evaluated_at,
        )
        if reason is DecisionReason.MEASUREMENT_STALE:
            changes.update(
                current_temperature=None,
                measurement_status=MeasurementStatus.STALE,
            )
        elif reason is DecisionReason.MEASUREMENT_FUTURE_TIMESTAMP:
            changes.update(
                current_temperature=None,
                measurement_status=MeasurementStatus.FUTURE_TIMESTAMP,
            )
        self._log_demand_transition(
            self.snapshot_source.current.zone_heat_demand,
            changes["zone_heat_demand"],
            reason,
        )
        self.snapshot_source.update(
            now=datetime.now(UTC),
            trace_record=trace,
            **changes,
        )

    def _evaluation_observation(
        self,
        result: HeatDemandEvaluationResult,
        *,
        measured: float | None,
        reason: DecisionReason,
        timestamp: datetime,
    ) -> tuple[dict[str, Any], DecisionTraceRecord]:
        demand = {
            BuildingHeatDemandStatus.HEAT_REQUIRED: HeatDemandState.HEAT_REQUIRED,
            BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatDemandState.NO_HEAT_REQUIRED,
            BuildingHeatDemandStatus.INDETERMINATE: HeatDemandState.INDETERMINATE,
        }[result.building_heat_demand.status]
        safety = {
            HeatDemandSafetyPhase.DETERMINATE: SafetyState.NORMAL,
            HeatDemandSafetyPhase.INDETERMINATE_GRACE: SafetyState.INDETERMINATE_GRACE,
            HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT: SafetyState.TIMEOUT_ACTION_APPLIED,
        }[result.safety_assessment.phase]
        outcome = {
            HeatDemandEvaluationStatus.INDETERMINATE_GRACE: CommandOutcome.NONE,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED: CommandOutcome.DISPATCHED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED: (CommandOutcome.SUPPRESSED_DUPLICATE),
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED: CommandOutcome.DISPATCHED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED: (CommandOutcome.SUPPRESSED_DUPLICATE),
            HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED: CommandOutcome.DEFERRED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED: CommandOutcome.DEFERRED,
        }[result.status]
        if result.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE:
            code = DecisionCode.INDETERMINATE_PRESERVE_PREVIOUS
        elif result.status in {
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
        }:
            code = (
                DecisionCode.TIMEOUT_DISABLE_HEATING
                if result.command is not None and result.command.action is HeatingAction.DISABLE_HEATING
                else DecisionCode.TIMEOUT_ENABLE_HEATING
            )
            reason = DecisionReason.SAFETY_GRACE_EXPIRED
        elif outcome is CommandOutcome.DEFERRED:
            code = DecisionCode.COMMAND_DEFERRED
            if result.source_control_assessment is not None:
                reason = DecisionReason(result.source_control_assessment.reason.value)
        elif outcome is CommandOutcome.SUPPRESSED_DUPLICATE:
            code = DecisionCode.COMMAND_SUPPRESSED_DUPLICATE
            reason = DecisionReason.DUPLICATE_COMMAND
        else:
            code = DecisionCode.COMMAND_DISPATCHED
        command = result.command.action.value if result.command is not None else None
        command_timestamp = result.command.created_at if result.command is not None else None
        changes: dict[str, Any] = {
            "zone_heat_demand": demand,
            "hysteresis_demand": demand,
            "demand_reason": reason,
            "active_demand_cause": reason,
            "safety_state": safety,
            "grace_deadline": result.safety_assessment.timeout_at
            if safety is SafetyState.INDETERMINATE_GRACE
            else None,
        }
        hysteresis = result.hysteresis_assessment
        if hysteresis is not None and demand is not HeatDemandState.INDETERMINATE:
            raw_demand = (
                HeatDemandState.HEAT_REQUIRED if hysteresis.raw_requires_heat else HeatDemandState.NO_HEAT_REQUIRED
            )
            filtered_demand = (
                HeatDemandState.HEAT_REQUIRED
                if hysteresis.state.demand.value == "heat_required"
                else HeatDemandState.NO_HEAT_REQUIRED
            )
            hysteresis_reason = DecisionReason(hysteresis.reason.value)
            changes.update(
                raw_zone_heat_demand=raw_demand,
                hysteresis_demand=filtered_demand,
                heating_enable_threshold=hysteresis.enable_threshold,
                heating_disable_threshold=hysteresis.disable_threshold,
                demand_reason=hysteresis_reason,
                active_demand_cause=hysteresis_reason,
            )
            demand = filtered_demand
            reason = hysteresis_reason
        confirmation = result.confirmation_assessment
        if confirmation is not None:
            confirmation_state = confirmation.state
            confirmed_demand = HeatDemandState(confirmation.output_demand.value)
            confirmation_reason = confirmation_state.last_reason.value
            changes.update(
                confirmed_zone_heat_demand=confirmed_demand,
                zone_heat_demand=confirmed_demand,
                confirmation_state=ConfirmationState(confirmation_state.phase.value),
                confirmation_started_at=(confirmation_state.confirmation_started_at),
                confirmation_deadline=confirmation_state.confirmation_deadline,
                confirmation_reason=confirmation_reason,
            )
            reason = DecisionReason(confirmation_reason)
            changes.update(active_demand_cause=reason)
            demand = confirmed_demand
            if confirmation_reason in {item.value for item in DecisionCode}:
                code = DecisionCode(confirmation_reason)
        source = result.source_control_assessment
        if source is not None:
            state = source.state
            changes.update(_source_control_snapshot_changes(state))
        if command is not None:
            changes.update(
                last_requested_command=command,
                last_command_outcome=outcome,
                last_command_timestamp=command_timestamp,
                last_command_failure_type=None,
            )
        if outcome is CommandOutcome.SUPPRESSED_DUPLICATE:
            changes["duplicate_commands_suppressed"] = self.snapshot_source.current.duplicate_commands_suppressed + 1
        if outcome is CommandOutcome.DISPATCHED:
            changes["recoverable_failure_active"] = False
        trace = self._trace_record(
            code=code,
            reason=reason,
            timestamp=timestamp,
            measured=measured,
            demand=demand,
            requested=command,
            outcome=outcome,
            safety=safety,
        )
        trace = replace(
            trace,
            raw_demand=changes.get("raw_zone_heat_demand"),
            hysteresis_demand=changes.get("hysteresis_demand"),
            confirmed_zone_demand=changes.get("confirmed_zone_heat_demand"),
            confirmation_state=changes.get("confirmation_state"),
            confirmation_reason=changes.get("confirmation_reason"),
            source_control_state=changes.get("source_control_state"),
            deferred_reason=changes.get("deferred_reason"),
            safety_bypassed_lockout=changes.get("safety_bypassed_lockout", False),
        )
        return changes, trace

    def _reason_from_building_demand(
        self,
        result: HeatDemandEvaluationResult,
    ) -> DecisionReason:
        demand = result.building_heat_demand
        if demand.status is BuildingHeatDemandStatus.HEAT_REQUIRED:
            return DecisionReason.TEMPERATURE_BELOW_TARGET
        if demand.status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED:
            return DecisionReason.TEMPERATURE_AT_OR_ABOVE_TARGET
        if demand.expired_zone_ids:
            return DecisionReason.MEASUREMENT_STALE
        if demand.future_dated_zone_ids:
            return DecisionReason.MEASUREMENT_FUTURE_TIMESTAMP
        current_status = self.snapshot_source.current.measurement_status
        return {
            MeasurementStatus.UNKNOWN: DecisionReason.MEASUREMENT_UNKNOWN,
            MeasurementStatus.UNAVAILABLE: DecisionReason.MEASUREMENT_UNAVAILABLE,
            MeasurementStatus.INVALID_VALUE: DecisionReason.MEASUREMENT_INVALID,
        }.get(current_status, DecisionReason.WAITING_FOR_FIRST_MEASUREMENT)

    def _observe_service_failure(
        self,
        error: HomeAssistantServiceCallError,
        measurement: Measurement,
    ) -> None:
        demand = (
            HeatDemandState.HEAT_REQUIRED
            if error.action is HeatingAction.ENABLE_HEATING
            else HeatDemandState.NO_HEAT_REQUIRED
        )
        reason = (
            DecisionReason.TEMPERATURE_BELOW_TARGET
            if demand is HeatDemandState.HEAT_REQUIRED
            else DecisionReason.TEMPERATURE_AT_OR_ABOVE_TARGET
        )
        self.snapshot_source.update(
            now=datetime.now(UTC),
            current_temperature=measurement.value.value,
            measurement_status=MeasurementStatus.VALID,
            latest_input_status=MeasurementStatus.VALID,
            measurement_timestamp=measurement.timestamp,
            zone_heat_demand=demand,
            demand_reason=reason,
        )

    def _observe_scheduled_state(
        self,
        previous_heat_source_state: object | None,
        previous_failure: object | None,
    ) -> None:
        safety = self._runtime.heat_demand_safety_state_store.get()
        if safety is None:
            return
        now = safety.last_evaluated_at
        current = self.snapshot_source.current
        latest = self._runtime.state_store.get_latest(self._config.sensor_id)
        deadline = (
            safety.indeterminate_since + self._config.indeterminate_grace_period
            if safety.indeterminate_since is not None
            else None
        )
        if safety.indeterminate_since is None:
            safety_state = SafetyState.NORMAL
        elif deadline is not None and now < deadline:
            safety_state = SafetyState.INDETERMINATE_GRACE
        else:
            safety_state = SafetyState.TIMEOUT_ACTION_APPLIED
        measurement_status = current.measurement_status
        measured: float | None = current.current_temperature
        if latest is None:
            demand = HeatDemandState.INDETERMINATE
            reason = DecisionReason.WAITING_FOR_FIRST_MEASUREMENT
            measured = None
        else:
            age = now - latest.timestamp
            if age > self._config.primary_measurement_max_age:
                demand = HeatDemandState.INDETERMINATE
                reason = DecisionReason.MEASUREMENT_STALE
                measured = None
                if measurement_status is MeasurementStatus.VALID:
                    measurement_status = MeasurementStatus.STALE
            elif latest.timestamp - now > self._config.max_future_skew:
                demand = HeatDemandState.INDETERMINATE
                reason = DecisionReason.MEASUREMENT_FUTURE_TIMESTAMP
                measured = None
                measurement_status = MeasurementStatus.FUTURE_TIMESTAMP
            else:
                zone_demand = self._runtime.zone_demand_store.get(self._config.zone_id)
                demand = (
                    HeatDemandState.HEAT_REQUIRED
                    if zone_demand is not None and zone_demand.requires_heat
                    else HeatDemandState.NO_HEAT_REQUIRED
                )
                reason = (
                    DecisionReason.TEMPERATURE_BELOW_TARGET
                    if demand is HeatDemandState.HEAT_REQUIRED
                    else DecisionReason.TEMPERATURE_AT_OR_ABOVE_TARGET
                )
                measurement_status = MeasurementStatus.VALID
                measured = latest.value.value
        changes: dict[str, Any] = {
            "current_temperature": measured,
            "measurement_status": measurement_status,
            "measurement_timestamp": latest.timestamp if latest is not None else None,
            "zone_heat_demand": demand,
            "demand_reason": reason,
            "safety_state": safety_state,
            "grace_deadline": deadline if safety_state is SafetyState.INDETERMINATE_GRACE else None,
        }
        confirmation = self._runtime.zone_heat_demand_confirmation_state
        if confirmation is not None:
            confirmed_demand = (
                HeatDemandState.INDETERMINATE
                if confirmation.hysteresis_demand is BuildingHeatDemandStatus.INDETERMINATE
                else HeatDemandState(confirmation.confirmed_demand.value)
            )
            changes.update(
                hysteresis_demand=HeatDemandState(confirmation.hysteresis_demand.value),
                confirmed_zone_heat_demand=confirmed_demand,
                zone_heat_demand=confirmed_demand,
                confirmation_state=ConfirmationState(confirmation.phase.value),
                confirmation_started_at=confirmation.confirmation_started_at,
                confirmation_deadline=confirmation.confirmation_deadline,
                confirmation_reason=confirmation.last_reason.value,
            )
        source = self._runtime.source_control_assessment
        if source is not None:
            state = source.state
            changes.update(_source_control_snapshot_changes(state))
        trace: DecisionTraceRecord | None = None
        if confirmation is not None and confirmation.last_reason.value == "heat_demand_confirmation_completed":
            source_assessment = self._runtime.source_control_assessment
            requested = HeatingAction.ENABLE_HEATING.value
            if source_assessment is not None and source_assessment.outcome.value == "defer":
                outcome = CommandOutcome.DEFERRED
            elif source_assessment is not None and source_assessment.outcome.value == "suppress_duplicate":
                outcome = CommandOutcome.SUPPRESSED_DUPLICATE
            elif (
                self._failure_sink.last_failure is not None and self._failure_sink.last_failure is not previous_failure
            ):
                outcome = CommandOutcome.FAILED_RECOVERABLE
            else:
                outcome = CommandOutcome.DISPATCHED
            changes.update(
                last_requested_command=requested,
                last_command_outcome=outcome,
                last_command_timestamp=now,
                active_demand_cause=(DecisionReason.HEAT_DEMAND_CONFIRMATION_COMPLETED),
            )
            trace = self._trace_record(
                code=DecisionCode.HEAT_DEMAND_CONFIRMATION_COMPLETED,
                reason=DecisionReason.HEAT_DEMAND_CONFIRMATION_COMPLETED,
                timestamp=now,
                measured=measured,
                demand=HeatDemandState.HEAT_REQUIRED,
                requested=requested,
                outcome=outcome,
                safety=safety_state,
            )
        if safety_state is SafetyState.INDETERMINATE_GRACE:
            if current.safety_state is not SafetyState.INDETERMINATE_GRACE:
                trace = self._trace_record(
                    code=DecisionCode.INDETERMINATE_PRESERVE_PREVIOUS,
                    reason=reason,
                    timestamp=now,
                    measured=measured,
                    demand=demand,
                    safety=safety_state,
                )
        elif safety_state is SafetyState.TIMEOUT_ACTION_APPLIED:
            requested = self._config.indeterminate_timeout_action.value
            new_failure = self._failure_sink.last_failure
            current_heat_source_state = self._runtime.heat_source_state_store.get()
            if new_failure is not None and new_failure is not previous_failure:
                outcome = CommandOutcome.FAILED_RECOVERABLE
            elif current_heat_source_state is previous_heat_source_state:
                outcome = CommandOutcome.SUPPRESSED_DUPLICATE
                changes["duplicate_commands_suppressed"] = current.duplicate_commands_suppressed + 1
            else:
                outcome = CommandOutcome.DISPATCHED
            changes.update(
                last_requested_command=requested,
                last_command_outcome=outcome,
                last_command_timestamp=now,
            )
            trace = self._trace_record(
                code=(
                    DecisionCode.TIMEOUT_DISABLE_HEATING
                    if self._config.indeterminate_timeout_action is HeatingAction.DISABLE_HEATING
                    else DecisionCode.TIMEOUT_ENABLE_HEATING
                ),
                reason=DecisionReason.SAFETY_GRACE_EXPIRED,
                timestamp=now,
                measured=None,
                demand=HeatDemandState.INDETERMINATE,
                requested=requested,
                outcome=outcome,
                safety=safety_state,
            )
            self._logger.info(
                "Controlel safety timeout applied action=%s outcome=%s",
                requested,
                outcome,
            )
            self._logger.warning(
                "Controlel measurement remained indeterminate through safety grace reason=%s",
                reason,
            )
        self._log_demand_transition(
            current.zone_heat_demand,
            demand,
            reason,
        )
        self.snapshot_source.update(
            now=datetime.now(UTC),
            trace_record=trace,
            **changes,
        )

    def _on_recoverable_failure_state(
        self,
        active: bool,
        error: Exception | None,
    ) -> None:
        now = datetime.now(UTC)
        changes: dict[str, Any] = {"recoverable_failure_active": active}
        trace = None
        if active and error is not None:
            requested = (
                error.action.value
                if isinstance(error, HomeAssistantServiceCallError)
                else self.snapshot_source.current.last_requested_command
            )
            changes.update(
                last_requested_command=requested,
                last_command_outcome=CommandOutcome.FAILED_RECOVERABLE,
                last_command_timestamp=now,
                last_command_failure_type=type(error).__name__,
            )
            trace = self._trace_record(
                code=DecisionCode.COMMAND_FAILED,
                reason=DecisionReason.SERVICE_CALL_FAILED,
                timestamp=now,
                requested=requested,
                outcome=CommandOutcome.FAILED_RECOVERABLE,
            )
            self._logger.warning(
                "Controlel service call failed failure_type=%s",
                type(error).__name__,
            )
        self.snapshot_source.update(now=now, trace_record=trace, **changes)

    def _on_fatal_failure_state(
        self,
        active: bool,
        error: Exception | None,
    ) -> None:
        self.snapshot_source.update(
            now=datetime.now(UTC),
            fatal_failure_active=active,
        )

    def _trace_record(
        self,
        *,
        code: DecisionCode,
        reason: DecisionReason,
        timestamp: datetime,
        measured: float | None | object = _MEASUREMENT_UNSET,
        demand: HeatDemandState | None = None,
        requested: str | None = None,
        outcome: CommandOutcome = CommandOutcome.NONE,
        safety: SafetyState | None = None,
    ) -> DecisionTraceRecord:
        current = self.snapshot_source.current
        measured_temperature = (
            current.current_temperature if measured is _MEASUREMENT_UNSET else cast(float | None, measured)
        )
        return DecisionTraceRecord(
            decision_code=code,
            reason_code=reason,
            timestamp=timestamp,
            measured_temperature=measured_temperature,
            target_temperature=self._config.target_temperature.value,
            resulting_demand=demand or current.zone_heat_demand,
            requested_command=requested,
            command_outcome=outcome,
            safety_state=safety or current.safety_state,
        )

    @property
    def active_issue_ids(self) -> tuple[str, ...]:
        issue_ids: list[str] = []
        if self._failure_sink.recoverable_failure_active:
            issue_ids.append(self._failure_sink.recoverable_issue_id)
        if self._failure_sink.fatal_failure_active:
            issue_ids.append(self._failure_sink.fatal_issue_id)
        return tuple(issue_ids)

    def _log_demand_transition(
        self,
        previous: HeatDemandState,
        current: HeatDemandState,
        reason: DecisionReason,
    ) -> None:
        if current is not previous:
            self._logger.debug(
                "Controlel demand transition previous=%s current=%s reason=%s",
                previous,
                current,
                reason,
            )

    def _log_processing_result(self, result: RuntimeProcessingResult) -> None:
        if result.status is RuntimeProcessingStatus.NO_DECISION:
            self._logger.debug("Controlel made no decision: %s", result.reason)
        elif result.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE:
            self._logger.info("Controlel heat demand is indeterminate and within grace")
        elif result.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED:
            self._logger.debug("Controlel suppressed an already-applied demand command")
        elif result.status is RuntimeProcessingStatus.COMMAND_EXECUTED:
            self._logger.info("Controlel executed a heat-demand command")
        elif result.status is RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED:
            self._logger.info("Controlel suppressed an already-applied safety command")
        elif result.status is RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED:
            self._logger.warning("Controlel executed the configured safety command")
        else:
            self._logger.debug("Controlel processing result: %s", result.status)

    def _log_evaluation_result(self, result: HeatDemandEvaluationResult) -> None:
        if result.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE:
            self._logger.info(
                "Controlel heat demand is indeterminate; next evaluation at %s",
                result.next_evaluation_at,
            )
        elif result.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED:
            self._logger.debug("Controlel suppressed an already-applied demand command")
        elif result.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED:
            self._logger.info("Controlel executed a heat-demand command")
        elif result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED:
            self._logger.info("Controlel suppressed an already-applied safety command")
        elif result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED:
            self._logger.warning("Controlel executed the configured safety command")

    def _default_state_getter(self, entity_id: str) -> StateLike | None:
        states = getattr(self._hass, "states")
        return states.get(entity_id)

    def _create_task(
        self,
        coroutine: Coroutine[Any, Any, Any],
        name: str,
    ) -> asyncio.Task[Any]:
        return self._hass.async_create_task(coroutine, name=name)


def _source_control_snapshot_changes(state: CoreSourceControlState) -> dict[str, object]:
    """Project one normalized core source-control snapshot into HA fields."""

    active_lockout_type = state.active_lockout_type
    active_lockout = ActiveLockoutType(active_lockout_type.value) if active_lockout_type is not None else None
    return {
        "source_control_state": SourceControlState(state.detailed_phase.value),
        "aggregate_demand": (state.aggregate_demand.value if state.aggregate_demand is not None else None),
        "earliest_next_enable_time": state.earliest_next_enable_time,
        "earliest_next_disable_time": state.earliest_next_disable_time,
        "active_lockout_type": active_lockout,
        "active_lockout_deadline": state.active_lockout_deadline,
        "minimum_on_deadline": state.earliest_next_disable_time,
        "minimum_off_deadline": state.earliest_next_enable_time,
        "deferred_command": (state.deferred_command.value if state.deferred_command is not None else None),
        "deferred_reason": (state.deferred_reason.value if state.deferred_reason is not None else None),
        "deferred_since": state.deferred_since,
        "deferred_deadline": state.deferred_deadline,
        "last_successful_enable_dispatch": state.last_successful_enable_dispatch,
        "last_successful_disable_dispatch": state.last_successful_disable_dispatch,
        "last_normal_command_dispatch": state.last_normal_command_dispatch,
        "safety_bypassed_lockout": state.safety_bypass_active,
    }


def _default_state_subscriber(
    hass: object,
    entity_id: str,
    listener: StateListener,
) -> Unsubscribe:
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def on_event(event: Any) -> None:
        listener(event.data["new_state"])

    return async_track_state_change_event(hass, entity_id, on_event)


def _default_shutdown_subscriber(
    hass: object,
    listener: Callable[[], None],
) -> Unsubscribe:
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.core import callback

    @callback
    def on_stop(_: Any) -> None:
        listener()

    return hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop)


def _default_interval_subscriber(
    hass: object,
    listener: Callable[[datetime], None],
    interval: timedelta,
) -> Unsubscribe:
    from homeassistant.helpers.event import async_track_time_interval

    return async_track_time_interval(hass, listener, interval)

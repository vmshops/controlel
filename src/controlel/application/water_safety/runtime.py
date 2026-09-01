"""Event-driven Water Safety v1 runtime state machine."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from controlel.application.configuration.water_safety_setup_adapter import (
    SHUTOFF_VALVE_ROLE_PREFIX,
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_SENSOR_ROLE,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupPayload,
)
from controlel.application.setup import EffectiveRuntimeConfiguration, IdentityQuality, RuntimeConfigurationOrigin
from controlel.application.setup.json_data import canonical_json
from controlel.application.water_safety.model import (
    OwnedWaterOutput,
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterOutputKind,
    WaterOutputOutcome,
    WaterOutputOwner,
    WaterSafetyDiagnostics,
    WaterSafetyEvent,
    WaterSafetyEventCode,
    WaterSafetyProcessingResult,
)
from controlel.application.water_safety.ports import (
    WaterSafetyEvidencePort,
    WaterSafetyOutputPort,
    WaterSafetyStatePort,
)
from controlel.domain.water_safety import (
    MoistureCondition,
    MoistureObservation,
    WaterIncident,
    WaterIncidentStatus,
    WaterSafetyAssessmentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
)


class WaterSafetyRuntime:
    """One-zone/one-sensor Water Safety v1 runtime.

    Calls are serialized by the host. ``next_deadline`` is the only scheduling
    contract: the host schedules a one-shot ``tick`` and reschedules after each
    result. No polling or hidden background loop exists in Core.
    """

    def __init__(
        self,
        effective: EffectiveRuntimeConfiguration,
        output_port: WaterSafetyOutputPort,
        *,
        state_port: WaterSafetyStatePort | None = None,
        evidence_port: WaterSafetyEvidencePort | None = None,
        restored_snapshot: WaterSafetySnapshot | None = None,
    ) -> None:
        if effective.origin is not RuntimeConfigurationOrigin.REAL:
            raise ValueError("Water Safety output runtime requires REAL canonical configuration")
        if effective.module_key != WATER_SAFETY_MODULE_KEY:
            raise ValueError("effective configuration is not for Water Safety")
        if effective.module_schema_version != WATER_SAFETY_SETUP_SCHEMA_VERSION:
            raise ValueError(f"unsupported Water Safety module schema version: {effective.module_schema_version}")
        self._config = WaterSafetySetupPayload.model_validate_json(canonical_json(effective.module_payload))
        expected_roles = {
            WATER_SAFETY_SENSOR_ROLE,
            *self._config.notification_target_roles,
            *self._config.siren_target_roles,
            *self._config.shutoff_valve_target_roles,
        }
        bindings = {binding.role: binding.reference for binding in effective.bindings}
        if set(bindings) != expected_roles:
            missing = sorted(expected_roles - set(bindings))
            extra = sorted(set(bindings) - expected_roles)
            raise ValueError(f"Water Safety runtime bindings differ; missing={missing}, extra={extra}")
        if any(reference.identity_quality is not IdentityQuality.STABLE for reference in bindings.values()):
            raise ValueError("Water Safety runtime requires stable provider references")

        self._effective = effective
        self._bindings = bindings
        self._output_port = output_port
        self._state_port = state_port
        self._evidence_port = evidence_port
        self._owner = WaterOutputOwner(
            environment_id=effective.environment_id,
            module_key=effective.module_key,
            module_instance_id=effective.module_instance_id,
        )
        self._owned_outputs = {
            role: OwnedWaterOutput(
                owner=self._owner,
                target_role=role,
                target=bindings[role],
                output_kind=(
                    WaterOutputKind.SHUTOFF_VALVE
                    if role.startswith(SHUTOFF_VALVE_ROLE_PREFIX)
                    else WaterOutputKind.SIREN
                ),
            )
            for role in (*self._config.siren_target_roles, *self._config.shutoff_valve_target_roles)
        }
        self._started = False
        if restored_snapshot is None:
            self._snapshot = WaterSafetySnapshot(
                environment_id=effective.environment_id,
                module_instance_id=effective.module_instance_id,
                canonical_revision_id=effective.canonical_revision_id,
                semantic_configuration_fingerprint=effective.semantic_configuration_fingerprint,
                sensor_id=self._config.sensor_id,
                state=WaterSafetyState.OK,
                processing_enabled=True,
            )
        else:
            self._validate_restored_snapshot(restored_snapshot)
            self._snapshot = restored_snapshot

    @property
    def state(self) -> WaterSafetyState:
        self._require_started()
        return self._snapshot.state

    @property
    def assessment_status(self) -> WaterSafetyAssessmentStatus:
        self._require_started()
        return self._snapshot.assessment_status

    @property
    def snapshot(self) -> WaterSafetySnapshot:
        self._require_started()
        return self._snapshot

    @property
    def next_deadline(self) -> datetime | None:
        deadlines = tuple(
            deadline
            for deadline in (self._snapshot.fault_deadline, self._snapshot.next_fault_notification_at)
            if deadline is not None
        )
        return min(deadlines) if deadlines and self._snapshot.processing_enabled else None

    def owned_outputs(self) -> tuple[OwnedWaterOutput, ...]:
        """Return module-owned persistent outputs without claiming their physical state."""

        return tuple(self._owned_outputs[role] for role in sorted(self._owned_outputs))

    def diagnostics(self) -> WaterSafetyDiagnostics:
        self._require_started()
        return WaterSafetyDiagnostics(
            state=self._snapshot.state,
            processing_enabled=self._snapshot.processing_enabled,
            sensor_id=self._config.sensor_id,
            zone_id=self._config.zone_id,
            area_id=self._config.area_id,
            critical_sensor=self._config.critical_sensor,
            assessment_status=self._snapshot.assessment_status,
            latest_observation=self._snapshot.latest_observation,
            last_confirmed_observation=self._snapshot.last_confirmed_observation,
            active_incident=self._snapshot.active_incident,
            last_incident=self._snapshot.last_incident,
            fault_deadline=self._snapshot.fault_deadline,
            next_fault_notification_at=self._snapshot.next_fault_notification_at,
            owned_outputs=self.owned_outputs(),
            canonical_revision_id=self._effective.canonical_revision_id,
            semantic_configuration_fingerprint=self._effective.semantic_configuration_fingerprint,
        )

    def start(self, current_observation: MoistureObservation, *, started_at: datetime) -> WaterSafetyProcessingResult:
        """Recover persisted state, then evaluate a current real sensor observation."""

        _require_aware(started_at, "started_at")
        if self._started:
            raise RuntimeError("Water Safety runtime has already started")
        self._require_sensor(current_observation)
        self._started = True
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        self._emit(events, started_at, WaterSafetyEventCode.RUNTIME_STARTED, previous, self._snapshot.state)
        if self._snapshot.processing_enabled:
            self._process_observation(current_observation, events, results, reassert_wet_outputs=True)
        self._persist()
        return self._result(previous, events, results)

    def observe(self, observation: MoistureObservation) -> WaterSafetyProcessingResult:
        self._require_started()
        self._require_sensor(observation)
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        if not self._snapshot.processing_enabled:
            return self._result(previous, events, results)
        latest = self._snapshot.latest_observation
        if latest is not None and observation.observed_at < latest.observed_at:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.OBSERVATION_IGNORED_OUT_OF_ORDER,
                previous,
                self._snapshot.state,
                observation=observation,
            )
            self._persist()
        else:
            self._process_observation(observation, events, results)
            self._persist()
        return self._result(previous, events, results)

    def tick(self, now: datetime) -> WaterSafetyProcessingResult:
        """Evaluate only due deterministic deadlines; late calls never catch up-spam."""

        self._require_started()
        _require_aware(now, "now")
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        if not self._snapshot.processing_enabled:
            return self._result(previous, events, results)
        if self._snapshot.fault_deadline is not None and now >= self._snapshot.fault_deadline:
            self._enter_sensor_fault(now, events, results)
        elif (
            self._snapshot.state is WaterSafetyState.SENSOR_FAULT
            and self._snapshot.next_fault_notification_at is not None
            and now >= self._snapshot.next_fault_notification_at
        ):
            self._emit(
                events,
                now,
                WaterSafetyEventCode.SENSOR_FAULT_NOTIFICATION_REPEATED,
                previous,
                self._snapshot.state,
                incident_id=self._active_incident_id,
            )
            self._notify_fault(now, events, results, repeated=True)
            interval = self._config.fault_repeat_interval_seconds
            assert interval is not None
            self._snapshot = replace(
                self._snapshot,
                next_fault_notification_at=now + timedelta(seconds=interval),
            )
        if events or results:
            self._persist()
        return self._result(previous, events, results)

    def silence(self, *, silenced_at: datetime) -> WaterSafetyProcessingResult:
        """Request all sirens off while leaving wet evidence and incident active."""

        self._require_started()
        _require_aware(silenced_at, "silenced_at")
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        incident = self._snapshot.active_incident
        if not self._snapshot.processing_enabled or incident is None or incident.silenced_at is not None:
            return self._result(previous, events, results)
        incident = replace(incident, silenced_at=silenced_at)
        self._snapshot = replace(self._snapshot, active_incident=incident)
        self._emit(
            events,
            silenced_at,
            WaterSafetyEventCode.INCIDENT_SILENCED,
            previous,
            self._snapshot.state,
            incident_id=incident.incident_id,
        )
        self._request_all_sirens(WaterOutputAction.REQUEST_SIREN_OFF, silenced_at, events, results)
        self._persist()
        return self._result(previous, events, results)

    def disable(self, *, disabled_at: datetime) -> WaterSafetyProcessingResult:
        """Stop processing/repeats, request safe cleanup, record outcomes, then disable."""

        self._require_started()
        _require_aware(disabled_at, "disabled_at")
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        if not self._snapshot.processing_enabled:
            return self._result(previous, events, results)
        self._emit(
            events,
            disabled_at,
            WaterSafetyEventCode.MODULE_DISABLE_STARTED,
            previous,
            previous,
            incident_id=self._active_incident_id,
        )
        self._request_all_sirens(WaterOutputAction.REQUEST_SIREN_OFF, disabled_at, events, results)
        self._snapshot = replace(
            self._snapshot,
            state=WaterSafetyState.DISABLED,
            processing_enabled=False,
            unavailable_since=None,
            fault_deadline=None,
            next_fault_notification_at=None,
        )
        self._emit(
            events,
            disabled_at,
            WaterSafetyEventCode.MODULE_DISABLED,
            previous,
            WaterSafetyState.DISABLED,
            incident_id=self._active_incident_id,
            details={
                "cleanup_failed": sum(result.outcome is WaterOutputOutcome.FAILED for result in results),
                "cleanup_requested": len(results),
            },
        )
        self._persist()
        return self._result(previous, events, results)

    def enable(self, current_observation: MoistureObservation, *, enabled_at: datetime) -> WaterSafetyProcessingResult:
        """Re-enable only by evaluating the supplied current real sensor state."""

        self._require_started()
        self._require_sensor(current_observation)
        _require_aware(enabled_at, "enabled_at")
        previous = self._snapshot.state
        events: list[WaterSafetyEvent] = []
        results: list[WaterOutputCommandResult] = []
        if self._snapshot.processing_enabled:
            self._process_observation(current_observation, events, results)
            self._persist()
            return self._result(previous, events, results)
        resumed_state = WaterSafetyState.WET if self._snapshot.active_incident is not None else WaterSafetyState.OK
        self._snapshot = replace(self._snapshot, state=resumed_state, processing_enabled=True)
        self._emit(
            events,
            enabled_at,
            WaterSafetyEventCode.MODULE_ENABLED,
            WaterSafetyState.DISABLED,
            resumed_state,
            incident_id=self._active_incident_id,
        )
        self._process_observation(current_observation, events, results, reassert_wet_outputs=True)
        self._persist()
        return self._result(previous, events, results)

    def _process_observation(
        self,
        observation: MoistureObservation,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
        *,
        reassert_wet_outputs: bool = False,
    ) -> None:
        previous = self._snapshot.state
        last_confirmed = self._snapshot.last_confirmed_observation
        if observation.condition in {MoistureCondition.DRY, MoistureCondition.WET}:
            last_confirmed = observation
        self._snapshot = replace(
            self._snapshot,
            latest_observation=observation,
            last_confirmed_observation=last_confirmed,
        )
        self._emit(
            events,
            observation.observed_at,
            WaterSafetyEventCode.OBSERVATION_ACCEPTED,
            previous,
            self._snapshot.state,
            observation=observation,
        )
        if observation.condition is MoistureCondition.DRY:
            self._process_dry(observation, events, results)
        elif observation.condition is MoistureCondition.WET:
            self._process_wet(observation, events, results, reassert_outputs=reassert_wet_outputs)
        else:
            self._process_indeterminate(observation, events, results)

    def _process_dry(
        self,
        observation: MoistureObservation,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> None:
        previous = self._snapshot.state
        grace_pending = self._snapshot.fault_deadline is not None
        if previous is WaterSafetyState.SENSOR_FAULT:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.SENSOR_FAULT_RECOVERED,
                previous,
                WaterSafetyState.OK,
                observation=observation,
                incident_id=self._active_incident_id,
            )
        incident = self._snapshot.active_incident
        recovered: WaterIncident | None = None
        if incident is not None:
            recovered = replace(
                incident,
                status=WaterIncidentStatus.RECOVERED,
                recovered_at=observation.observed_at,
            )
        self._snapshot = replace(
            self._snapshot,
            state=WaterSafetyState.OK,
            active_incident=None,
            last_incident=recovered or self._snapshot.last_incident,
            unavailable_since=None,
            fault_deadline=None,
            next_fault_notification_at=None,
        )
        if grace_pending:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.SENSOR_GRACE_CANCELLED,
                previous,
                WaterSafetyState.OK,
                observation=observation,
                incident_id=None if recovered is None else recovered.incident_id,
            )
        if recovered is not None:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.WET_INCIDENT_RECOVERED,
                previous,
                WaterSafetyState.OK,
                observation=observation,
                incident_id=recovered.incident_id,
            )
            self._request_all_sirens(WaterOutputAction.REQUEST_SIREN_OFF, observation.observed_at, events, results)
            self._notify(
                WaterOutputAction.NOTIFY_RECOVERY,
                "water_safety.recovery",
                self._config.messages.recovery,
                observation.observed_at,
                recovered.incident_id,
                events,
                results,
            )

    def _process_wet(
        self,
        observation: MoistureObservation,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
        *,
        reassert_outputs: bool,
    ) -> None:
        previous = self._snapshot.state
        grace_pending = self._snapshot.fault_deadline is not None
        if previous is WaterSafetyState.SENSOR_FAULT:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.SENSOR_FAULT_RECOVERED,
                previous,
                WaterSafetyState.WET,
                observation=observation,
                incident_id=self._active_incident_id,
            )
        incident = self._snapshot.active_incident
        is_new = incident is None
        if incident is None:
            sequence = self._snapshot.next_incident_sequence
            incident = WaterIncident(
                incident_id=f"{self._effective.module_instance_id}:wet:{sequence}",
                status=WaterIncidentStatus.ACTIVE,
                started_at=observation.observed_at,
                last_confirmed_wet_at=observation.observed_at,
            )
            self._snapshot = replace(self._snapshot, next_incident_sequence=sequence + 1)
        else:
            incident = replace(incident, last_confirmed_wet_at=observation.observed_at)
        self._snapshot = replace(
            self._snapshot,
            state=WaterSafetyState.WET,
            active_incident=incident,
            unavailable_since=None,
            fault_deadline=None,
            next_fault_notification_at=None,
        )
        if grace_pending:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.SENSOR_GRACE_CANCELLED,
                previous,
                WaterSafetyState.WET,
                observation=observation,
                incident_id=incident.incident_id,
            )
        if is_new:
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.WET_INCIDENT_STARTED,
                previous,
                WaterSafetyState.WET,
                observation=observation,
                incident_id=incident.incident_id,
            )
            self._request_all_shutoff_valves(observation.observed_at, events, results)
            self._request_all_sirens(WaterOutputAction.REQUEST_SIREN_ON, observation.observed_at, events, results)
            self._notify(
                WaterOutputAction.NOTIFY_WET,
                "water_safety.wet",
                self._config.messages.wet,
                observation.observed_at,
                incident.incident_id,
                events,
                results,
            )
        elif reassert_outputs:
            self._request_all_shutoff_valves(observation.observed_at, events, results)
            if incident.silenced_at is None:
                self._request_all_sirens(WaterOutputAction.REQUEST_SIREN_ON, observation.observed_at, events, results)

    def _process_indeterminate(
        self,
        observation: MoistureObservation,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> None:
        if self._snapshot.state is WaterSafetyState.SENSOR_FAULT:
            return
        immediate = self._config.unavailable_grace_seconds == 0
        if immediate:
            self._enter_sensor_fault(observation.observed_at, events, results)
            return
        if self._snapshot.fault_deadline is None:
            new_deadline = observation.observed_at + timedelta(seconds=self._config.unavailable_grace_seconds)
            previous = self._snapshot.state
            self._snapshot = replace(
                self._snapshot,
                unavailable_since=observation.observed_at,
                fault_deadline=new_deadline,
            )
            self._emit(
                events,
                observation.observed_at,
                WaterSafetyEventCode.SENSOR_GRACE_STARTED,
                previous,
                previous,
                observation=observation,
                incident_id=self._active_incident_id,
                details={"fault_deadline": new_deadline.isoformat()},
            )
        deadline = self._snapshot.fault_deadline
        if deadline is not None and observation.observed_at >= deadline:
            self._enter_sensor_fault(observation.observed_at, events, results)

    def _enter_sensor_fault(
        self,
        at: datetime,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> None:
        if self._snapshot.state is WaterSafetyState.SENSOR_FAULT:
            return
        previous = self._snapshot.state
        interval = self._config.fault_repeat_interval_seconds if self._config.critical_sensor else None
        self._snapshot = replace(
            self._snapshot,
            state=WaterSafetyState.SENSOR_FAULT,
            unavailable_since=None,
            fault_deadline=None,
            next_fault_notification_at=None if interval is None else at + timedelta(seconds=interval),
        )
        self._emit(
            events,
            at,
            WaterSafetyEventCode.SENSOR_FAULT_STARTED,
            previous,
            WaterSafetyState.SENSOR_FAULT,
            observation=self._snapshot.latest_observation,
            incident_id=self._active_incident_id,
            details={"critical_sensor": self._config.critical_sensor},
        )
        if self._config.critical_sensor:
            self._notify_fault(at, events, results, repeated=False)

    def _notify_fault(
        self,
        at: datetime,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
        *,
        repeated: bool,
    ) -> None:
        self._notify(
            WaterOutputAction.NOTIFY_SENSOR_FAULT,
            "water_safety.sensor_fault",
            self._config.messages.fault,
            at,
            self._active_incident_id,
            events,
            results,
            repeated=repeated,
        )

    def _notify(
        self,
        action: WaterOutputAction,
        message_code: str,
        custom_message: str | None,
        at: datetime,
        incident_id: str | None,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
        *,
        repeated: bool = False,
    ) -> None:
        for role in self._config.notification_target_roles:
            self._dispatch(
                WaterOutputKind.NOTIFICATION,
                action,
                role,
                at,
                events,
                results,
                incident_id=incident_id,
                message_code=message_code,
                custom_message=custom_message,
                repeated=repeated,
            )

    def _request_all_sirens(
        self,
        action: WaterOutputAction,
        at: datetime,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> None:
        for role in self._config.siren_target_roles:
            self._dispatch(
                WaterOutputKind.SIREN,
                action,
                role,
                at,
                events,
                results,
                incident_id=self._active_incident_id,
            )

    def _request_all_shutoff_valves(
        self,
        at: datetime,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> None:
        for role in self._config.shutoff_valve_target_roles:
            self._dispatch(
                WaterOutputKind.SHUTOFF_VALVE,
                WaterOutputAction.REQUEST_VALVE_CLOSE,
                role,
                at,
                events,
                results,
                incident_id=self._active_incident_id,
            )

    def _dispatch(
        self,
        kind: WaterOutputKind,
        action: WaterOutputAction,
        role: str,
        at: datetime,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
        *,
        incident_id: str | None,
        message_code: str | None = None,
        custom_message: str | None = None,
        repeated: bool = False,
    ) -> None:
        sequence = self._snapshot.next_command_sequence
        self._snapshot = replace(self._snapshot, next_command_sequence=sequence + 1)
        command = WaterOutputCommand(
            command_id=f"{self._effective.module_instance_id}:command:{sequence}",
            requested_at=at,
            owner=self._owner,
            output_kind=kind,
            action=action,
            target_role=role,
            target=self._bindings[role],
            incident_id=incident_id,
            message_code=message_code,
            custom_message=custom_message,
            repeated=repeated,
        )
        try:
            result = self._output_port.request(command)
            if result.command_id != command.command_id:
                result = WaterOutputCommandResult(
                    command_id=command.command_id,
                    occurred_at=at,
                    outcome=WaterOutputOutcome.FAILED,
                    failure_code="output_result_command_mismatch",
                )
        except Exception:
            result = WaterOutputCommandResult(
                command_id=command.command_id,
                occurred_at=at,
                outcome=WaterOutputOutcome.FAILED,
                failure_code="output_port_exception",
            )
        results.append(result)
        if kind in {WaterOutputKind.SIREN, WaterOutputKind.SHUTOFF_VALVE}:
            self._owned_outputs[role] = OwnedWaterOutput(
                owner=self._owner,
                target_role=role,
                target=self._bindings[role],
                output_kind=kind,
                last_requested_action=action,
                last_command_outcome=result.outcome,
                last_requested_at=at,
                last_failure_code=result.failure_code,
            )
        self._emit(
            events,
            at,
            WaterSafetyEventCode.OUTPUT_REQUESTED,
            self._snapshot.state,
            self._snapshot.state,
            incident_id=incident_id,
            command=command,
            command_result=result,
            details={"physical_state_confirmed": False},
        )

    def _emit(
        self,
        events: list[WaterSafetyEvent],
        at: datetime,
        code: WaterSafetyEventCode,
        previous_state: WaterSafetyState,
        new_state: WaterSafetyState,
        *,
        observation: MoistureObservation | None = None,
        incident_id: str | None = None,
        command: WaterOutputCommand | None = None,
        command_result: WaterOutputCommandResult | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        sequence = self._snapshot.next_event_sequence
        self._snapshot = replace(self._snapshot, next_event_sequence=sequence + 1)
        event = WaterSafetyEvent(
            event_id=f"{self._effective.module_instance_id}:event:{sequence}",
            occurred_at=at,
            code=code,
            previous_state=previous_state,
            new_state=new_state,
            observation=observation,
            incident_id=incident_id,
            command=command,
            command_result=command_result,
            details=tuple(sorted((details or {}).items())),
        )
        events.append(event)
        if self._evidence_port is not None:
            self._evidence_port.record(event)

    @property
    def _active_incident_id(self) -> str | None:
        incident = self._snapshot.active_incident
        return None if incident is None else incident.incident_id

    def _persist(self) -> None:
        if self._state_port is not None:
            self._state_port.save(self._snapshot)

    def _result(
        self,
        previous: WaterSafetyState,
        events: list[WaterSafetyEvent],
        results: list[WaterOutputCommandResult],
    ) -> WaterSafetyProcessingResult:
        return WaterSafetyProcessingResult(
            previous_state=previous,
            state=self._snapshot.state,
            snapshot=self._snapshot,
            events=tuple(events),
            output_results=tuple(results),
        )

    def _require_sensor(self, observation: MoistureObservation) -> None:
        if observation.sensor_id != self._config.sensor_id:
            raise ValueError("observation does not belong to the configured stable Controlel sensor")

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("Water Safety runtime must be started before processing")

    def _validate_restored_snapshot(self, snapshot: WaterSafetySnapshot) -> None:
        expected = (
            self._effective.environment_id,
            self._effective.module_instance_id,
            self._effective.canonical_revision_id,
            self._effective.semantic_configuration_fingerprint,
            self._config.sensor_id,
        )
        actual = (
            snapshot.environment_id,
            snapshot.module_instance_id,
            snapshot.canonical_revision_id,
            snapshot.semantic_configuration_fingerprint,
            snapshot.sensor_id,
        )
        if actual != expected:
            raise ValueError("restored Water Safety state does not match canonical runtime authority")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

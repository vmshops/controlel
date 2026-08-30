"""Passive Home Assistant evidence adapter for Frontend API v1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from controlel.application.services.operational_event_stream import (
    OperationalEventStreamSnapshot,
)
from controlel.domain.operational_events import OperationalEvent
from controlel.domain.source_control import ReportedSourceEvidence
from controlel.frontend_api.v1 import (
    BuildingEvidenceV1,
    DecisionEvidenceItemV1,
    DecisionEvidenceV1,
    EventStreamEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    ModuleEvidenceV1,
    OperationalEventEvidenceV1,
    ScopeV1,
    SetupEvidenceV1,
    SystemEvidenceV1,
    ZoneEvidenceV1,
)
from controlel.infrastructure.time.system_clock import SystemClock

from .core_capabilities import water_safety_core_available

if TYPE_CHECKING:
    from controlel.application.state.water_safety_diagnostics import WaterSafetyDiagnosticsSnapshotV1
    from controlel.frontend_api.v1 import WaterSafetyEvidenceV1

from .operational import (
    CommandOutcome,
    DecisionTraceRecord,
    HeatDemandState,
    OperationalSnapshot,
    RuntimeStatus,
    SourceControlState,
)


class FrontendApiHostV1(Protocol):
    """Narrow passive surface supplied by one loaded HA runtime."""

    @property
    def frontend_api_operational_evidence(
        self,
    ) -> tuple[
        OperationalSnapshot,
        tuple[DecisionTraceRecord, ...],
        int,
        OperationalEventStreamSnapshot,
        tuple[str, str | None, datetime | None],
        bool,
        ReportedSourceEvidence | None,
    ]: ...

    @property
    def frontend_api_setup_ready(self) -> bool: ...

    @property
    def frontend_api_water_safety_evidence(self) -> Any | None: ...


SetupEvidenceSource = Callable[[], SetupEvidenceV1]

_UNCONFIGURED_OPERATING_MODE = "UNCONFIGURED"
_HEATING_NOT_CONFIGURED = "heating_not_configured"


@dataclass(frozen=True, slots=True)
class UnconfiguredFrontendApiEvidenceSourceV1:
    """Passive evidence for a loaded but unconfigured Controlel config entry."""

    def snapshot(self) -> FrontendApiEvidenceV1:
        modules = [
            ModuleEvidenceV1(
                module_id="heating",
                status="inactive",
                reason=_HEATING_NOT_CONFIGURED,
            ),
        ]
        if water_safety_core_available():
            modules.append(
                ModuleEvidenceV1(
                    module_id="water_safety",
                    status="inactive",
                    reason="water_safety_not_configured",
                ),
            )
        return FrontendApiEvidenceV1(
            system=SystemEvidenceV1(
                status="stopped",
                operating_mode=_UNCONFIGURED_OPERATING_MODE,
            ),
            modules=tuple(modules),
            setup=SetupEvidenceV1(state="ready", reason_code=None),
        )


@dataclass(frozen=True, slots=True)
class HomeAssistantFrontendApiHostBridge:
    """Expose heating and optional Water Safety evidence through one Frontend API host."""

    heating_host: FrontendApiHostV1
    water_safety_host: object | None = None

    @property
    def frontend_api_operational_evidence(
        self,
    ) -> tuple[
        OperationalSnapshot,
        tuple[DecisionTraceRecord, ...],
        int,
        OperationalEventStreamSnapshot,
        tuple[str, str | None, datetime | None],
        bool,
        ReportedSourceEvidence | None,
    ]:
        return self.heating_host.frontend_api_operational_evidence

    @property
    def frontend_api_setup_ready(self) -> bool:
        return self.heating_host.frontend_api_setup_ready

    @property
    def frontend_api_water_safety_evidence(self) -> Any | None:
        if self.water_safety_host is None or not water_safety_core_available():
            return None
        snapshot = self.water_safety_host.frontend_api_water_safety_evidence
        return _water_safety_snapshot_to_evidence(snapshot)


@dataclass(frozen=True, slots=True)
class HomeAssistantFrontendApiEvidenceSourceV1:
    """Map existing HA/application snapshots without entering control paths."""

    host: FrontendApiHostV1
    setup_source: SetupEvidenceSource | None = None

    def snapshot(self) -> FrontendApiEvidenceV1:
        operational, trace, total_trace, events, mode, normal_authority, reported = (
            self.host.frontend_api_operational_evidence
        )
        latest = _latest_decision(trace, operational.zone_id, operational.sensor_id)
        status = _runtime_status(operational)
        water_safety = self.host.frontend_api_water_safety_evidence if water_safety_core_available() else None
        modules = [
            ModuleEvidenceV1(
                module_id="heating",
                status=("active" if status == "active" else "error" if status == "degraded" else "inactive"),
                reason=_module_reason(operational),
            ),
        ]
        if water_safety_core_available():
            modules.append(_water_safety_module(water_safety))
        evidence = FrontendApiEvidenceV1(
            system=SystemEvidenceV1(
                status=status,
                operating_mode=mode[0],
                operating_mode_reason=mode[1],
                operating_mode_since=mode[2],
            ),
            modules=tuple(modules),
            building=BuildingEvidenceV1(
                demand_status=(operational.zone_heat_demand.value if normal_authority else "indeterminate"),
                demand_reason_code=(operational.active_demand_cause.value if normal_authority else None),
                heat_source=HeatSourceEvidenceV1(
                    permission=(_permission(operational.source_control_state) if normal_authority else "unknown"),
                    requested_command=(
                        _requested_command(operational.last_requested_command) if normal_authority else None
                    ),
                    command_outcome=(_command_outcome(operational.last_command_outcome) if normal_authority else None),
                    reported_state=(reported.state.name if reported is not None else "UNKNOWN"),
                    last_decision=latest,
                ),
            ),
            zones=(
                ZoneEvidenceV1(
                    zone_id=operational.zone_id,
                    name=operational.zone_name,
                    target_temperature_c=operational.target_temperature,
                    measurement_temperature_c=operational.current_temperature,
                    measurement_observed_at=(
                        operational.measurement_timestamp if operational.current_temperature is not None else None
                    ),
                    measurement_max_age=timedelta(seconds=operational.primary_measurement_max_age_seconds),
                    demand_requires_heat=(
                        _zone_requires_heat(operational.zone_heat_demand) if normal_authority else None
                    ),
                    demand_observed_at=(operational.last_decision_timestamp if normal_authority else None),
                    demand_reason_code=(operational.active_demand_cause.value if normal_authority else None),
                    last_decision=latest,
                ),
            ),
            event_stream=_event_stream(events),
            latest_decision=latest,
            retained_decision_count=len(trace),
            total_decisions=total_trace,
            setup=(
                self.setup_source()
                if self.setup_source is not None
                else SetupEvidenceV1(
                    state="ready" if self.host.frontend_api_setup_ready else "unknown",
                    reason_code=(None if self.host.frontend_api_setup_ready else "runtime_readiness_unknown"),
                )
            ),
        )
        if water_safety_core_available() and water_safety is not None and hasattr(evidence, "water_safety"):
            return replace(evidence, water_safety=water_safety)
        return evidence


def create_unconfigured_frontend_api_provider_v1() -> FrontendApiProviderV1:
    """Compose a passive provider for a fresh, unconfigured Controlel entry."""

    return FrontendApiProviderV1(
        source=UnconfiguredFrontendApiEvidenceSourceV1(),
        clock=SystemClock(),
    )


def create_frontend_api_provider_v1(
    host: FrontendApiHostV1,
    *,
    water_safety_host: object | None = None,
    setup_source: SetupEvidenceSource | None = None,
) -> FrontendApiProviderV1:
    """Compose the host-independent provider over one loaded HA entry."""

    bridge = (
        host
        if isinstance(host, HomeAssistantFrontendApiHostBridge)
        else HomeAssistantFrontendApiHostBridge(
            heating_host=host,
            water_safety_host=water_safety_host,
        )
    )
    source = HomeAssistantFrontendApiEvidenceSourceV1(
        host=bridge,
        setup_source=setup_source,
    )
    return FrontendApiProviderV1(source=source, clock=SystemClock())


def _water_safety_snapshot_to_evidence(snapshot: WaterSafetyDiagnosticsSnapshotV1) -> WaterSafetyEvidenceV1:
    from controlel.frontend_api.v1 import WaterSafetyEvidenceV1

    actions = snapshot.actions_available
    available: list[str] = []
    if actions.silence:
        available.append("silence")
    if actions.disable:
        available.append("disable")
    if actions.enable:
        available.append("enable")
    if actions.test_notification:
        available.append("test_notification")
    if actions.test_siren:
        available.append("test_siren")
    return WaterSafetyEvidenceV1(
        state=snapshot.state,
        assessment_status=snapshot.assessment_status,
        sensor_condition=snapshot.sensor_condition,
        area_name=snapshot.area_name,
        zone_name=snapshot.zone_name,
        active_incident=snapshot.active_incident,
        incident_silenced=snapshot.incident_silenced,
        processing_enabled=snapshot.processing_enabled,
        owned_siren_count=snapshot.owned_siren_count,
        last_siren_command_outcome=snapshot.last_siren_command_outcome,
        actions_available=tuple(sorted(available)),
    )


def _runtime_status(snapshot: OperationalSnapshot) -> str:
    if snapshot.runtime_status is RuntimeStatus.STOPPED:
        return "stopped"
    if snapshot.runtime_status is RuntimeStatus.ACTIVE and not (
        snapshot.recoverable_failure_active or snapshot.fatal_failure_active
    ):
        return "active"
    return "degraded"


def _module_reason(snapshot: OperationalSnapshot) -> str | None:
    if snapshot.fatal_failure_active:
        return "fatal_runtime_failure"
    if snapshot.recoverable_failure_active:
        return "recoverable_runtime_failure"
    if snapshot.runtime_status is RuntimeStatus.STOPPED:
        return "runtime_stopped"
    if snapshot.runtime_status is RuntimeStatus.STARTING:
        return "runtime_starting"
    return None


def _water_safety_module(evidence: Any | None) -> ModuleEvidenceV1:
    if evidence is None:
        return ModuleEvidenceV1(module_id="water_safety", status="inactive", reason="water_safety_not_configured")
    if not evidence.processing_enabled or evidence.state == "DISABLED":
        return ModuleEvidenceV1(module_id="water_safety", status="inactive", reason="water_safety_disabled")
    if evidence.state in {"WET", "SENSOR_FAULT"}:
        return ModuleEvidenceV1(module_id="water_safety", status="error", reason=evidence.state.lower())
    return ModuleEvidenceV1(module_id="water_safety", status="active", reason=None)


def _permission(state: SourceControlState) -> str:
    if state in {
        SourceControlState.HEATING_REQUESTED_AND_ALLOWED,
        SourceControlState.HEATING_ACTIVE_REQUEST,
        SourceControlState.HEATING_NOT_REQUESTED_WAITING_MINIMUM_ON,
    }:
        return "enabled"
    if state in {
        SourceControlState.HEATING_NOT_REQUESTED,
        SourceControlState.HEATING_REQUESTED_WAITING_MINIMUM_OFF,
    }:
        return "disabled"
    return "unknown"


def _requested_command(value: str | None) -> str | None:
    return {
        "enable_heating": "enable",
        "disable_heating": "disable",
    }.get(value)


def _command_outcome(value: CommandOutcome) -> str | None:
    if value is CommandOutcome.DISPATCHED:
        return "dispatched"
    if value is CommandOutcome.DEFERRED:
        return "deferred"
    if value is CommandOutcome.HELD:
        return "held"
    if value in {CommandOutcome.FAILED_RECOVERABLE, CommandOutcome.FAILED_FATAL}:
        return "failed"
    if value in {CommandOutcome.SUPPRESSED, CommandOutcome.SUPPRESSED_DUPLICATE}:
        return "suppressed"
    return None


def _zone_requires_heat(value: HeatDemandState) -> bool | None:
    if value is HeatDemandState.HEAT_REQUIRED:
        return True
    if value is HeatDemandState.NO_HEAT_REQUIRED:
        return False
    return None


def _latest_decision(
    trace: tuple[DecisionTraceRecord, ...],
    zone_id: str,
    sensor_id: str,
) -> DecisionEvidenceV1 | None:
    if not trace:
        return None
    item = trace[-1]
    action = {
        "enable_heating": "enable_heating",
        "disable_heating": "disable_heating",
    }.get(item.requested_command, "observe_only")
    evidence = (
        DecisionEvidenceItemV1("measurement_temperature_c", item.measured_temperature),
        DecisionEvidenceItemV1("target_temperature_c", item.target_temperature),
        DecisionEvidenceItemV1("resulting_demand", item.resulting_demand.value),
        DecisionEvidenceItemV1("safety_state", item.safety_state.value),
    )
    return DecisionEvidenceV1(
        decision_id=f"decision:{item.sequence}",
        zone_id=zone_id,
        sensor_id=sensor_id,
        action=action,
        observed_at=item.timestamp,
        reason_code=item.reason_code.value,
        evidence=evidence,
    )


def _event_stream(snapshot: OperationalEventStreamSnapshot) -> EventStreamEvidenceV1:
    return EventStreamEvidenceV1(
        events=tuple(_event(item) for item in snapshot.events),
        total_emitted=snapshot.total_emitted,
        dropped=snapshot.dropped_count,
    )


def _event(item: OperationalEvent) -> OperationalEventEvidenceV1:
    if item.zone_id is not None:
        scope = ScopeV1(type="zone", zone_id=item.zone_id)
    elif item.source_id is not None or item.category.value in {"source_control", "source_resilience"}:
        # A source locator may be an HA entity_id. Its presence selects the
        # scope type only; it is deliberately never exposed as public identity.
        scope = ScopeV1(type="source")
    else:
        scope = ScopeV1(type="module", module_id="heating")
    return OperationalEventEvidenceV1(
        event_id=item.event_id,
        timestamp=item.timestamp,
        category=item.category.value,
        severity=item.severity.value,
        event_code=item.event_code.value,
        summary_code=item.summary_code,
        reason_code=item.reason_code,
        scope=scope,
        previous_state=item.previous_state,
        new_state=item.new_state,
        requested_command=_requested_command(item.requested_command),
        command_outcome=_event_command_outcome(item.command_outcome),
    )


def _event_command_outcome(value: str | None) -> str | None:
    if value == "dispatched":
        return "dispatched"
    if value == "deferred":
        return "deferred"
    if value == "held":
        return "held"
    if value == "failed":
        return "failed"
    if value in {"suppressed", "suppressed_duplicate"}:
        return "suppressed"
    return None

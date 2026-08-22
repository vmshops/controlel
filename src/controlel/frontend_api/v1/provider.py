"""Passive provider for the four read-only Frontend API v1 domains."""

from datetime import datetime, timedelta
from typing import Protocol

from controlel.frontend_api.v1.models import (
    AttentionEvidenceV1,
    AttentionV1,
    BuildingV1,
    DecisionEvidenceV1,
    DecisionSummaryV1,
    DecisionTraceV1,
    DemandStatus,
    DiagnosticsResponseV1,
    EventCommandV1,
    EventStreamHealthV1,
    FrontendApiEvidenceV1,
    HealthV1,
    HeatingResponseV1,
    HeatSourceV1,
    MeasurementState,
    MissingConfigurationV1,
    ModuleV1,
    OperationalEventEvidenceV1,
    OperationalEventV1,
    OverviewResponseV1,
    ReadinessV1,
    SetupResponseV1,
    SystemV1,
    ValidationMessageV1,
    ZoneEvidenceV1,
    ZoneV1,
)

FRONTEND_API_VERSION = 1
DEFAULT_ATTENTION_LIMIT = 50
DEFAULT_RECENT_EVENT_LIMIT = 50
DEFAULT_SETUP_ITEM_LIMIT = 100
DEFAULT_DECISION_EVIDENCE_LIMIT = 20
DEFAULT_MODULE_LIMIT = 32
DEFAULT_ZONE_LIMIT = 64


class FrontendApiEvidenceSourceV1(Protocol):
    """Host-owned source for an immutable, internally consistent snapshot."""

    def snapshot(self) -> FrontendApiEvidenceV1: ...


class FrontendApiClock(Protocol):
    def now(self) -> datetime: ...


class FrontendApiProviderV1:
    """Project host evidence without commands, callbacks, or runtime mutation."""

    def __init__(
        self,
        *,
        source: FrontendApiEvidenceSourceV1,
        clock: FrontendApiClock,
        recent_event_limit: int = DEFAULT_RECENT_EVENT_LIMIT,
    ) -> None:
        if recent_event_limit < 1:
            raise ValueError("recent_event_limit must be positive")
        self._source = source
        self._clock = clock
        self._recent_event_limit = recent_event_limit

    def overview(self) -> OverviewResponseV1:
        evidence, now = self._read()
        system = evidence.system
        return OverviewResponseV1(
            frontend_api_version=FRONTEND_API_VERSION,
            generated_at=now.isoformat(),
            system=SystemV1(
                status=system.status,
                operating_mode=system.operating_mode,
                operating_mode_reason=system.operating_mode_reason,
                operating_mode_since=_timestamp(system.operating_mode_since),
            ),
            modules=tuple(
                ModuleV1(module_id=item.module_id, status=item.status, reason=item.reason)
                for item in sorted(evidence.modules, key=lambda item: item.module_id)[:DEFAULT_MODULE_LIMIT]
            ),
            attention=tuple(_attention(item) for item in evidence.attention[:DEFAULT_ATTENTION_LIMIT]),
        )

    def heating(self) -> HeatingResponseV1:
        evidence, now = self._read()
        source = evidence.building.heat_source
        return HeatingResponseV1(
            frontend_api_version=FRONTEND_API_VERSION,
            generated_at=now.isoformat(),
            building=BuildingV1(
                demand_status=evidence.building.demand_status,
                demand_reason_code=evidence.building.demand_reason_code,
                heat_source=HeatSourceV1(
                    permission=source.permission,
                    requested_command=source.requested_command,
                    command_outcome=source.command_outcome,
                    reported_state=source.reported_state,
                    # No physical heat-source evidence exists in v1. Permission,
                    # dispatch, and controller reports cannot establish it.
                    physical_state="unknown",
                    last_decision_summary=_decision_summary(source.last_decision),
                ),
            ),
            zones=tuple(
                _zone(zone, now) for zone in sorted(evidence.zones, key=lambda item: item.zone_id)[:DEFAULT_ZONE_LIMIT]
            ),
        )

    def diagnostics(self) -> DiagnosticsResponseV1:
        evidence, now = self._read()
        stream = evidence.event_stream
        newest = sorted(stream.events, key=lambda item: (item.timestamp, item.event_id), reverse=True)
        latest = evidence.latest_decision
        decision_trace = None
        if latest is not None:
            decision_trace = DecisionTraceV1(
                decision_id=latest.decision_id,
                zone_id=latest.zone_id,
                sensor_id=latest.sensor_id,
                action=latest.action,
                observed_at=latest.observed_at.isoformat(),
                reason_code=latest.reason_code,
                evidence=latest.evidence[:DEFAULT_DECISION_EVIDENCE_LIMIT],
                retained_count=evidence.retained_decision_count,
                total_decisions=evidence.total_decisions,
            )
        return DiagnosticsResponseV1(
            frontend_api_version=FRONTEND_API_VERSION,
            generated_at=now.isoformat(),
            health=HealthV1(
                runtime_status=evidence.system.status,
                operating_mode=evidence.system.operating_mode,
                event_stream=EventStreamHealthV1(
                    total_emitted=stream.total_emitted,
                    retained=len(stream.events),
                    dropped=stream.dropped,
                ),
            ),
            recent_events=tuple(_event(item) for item in newest[: self._recent_event_limit]),
            decision_trace=decision_trace,
        )

    def setup(self) -> SetupResponseV1:
        evidence, now = self._read()
        setup = evidence.setup
        return SetupResponseV1(
            frontend_api_version=FRONTEND_API_VERSION,
            generated_at=now.isoformat(),
            readiness=ReadinessV1(state=setup.state, reason_code=setup.reason_code),
            missing_configuration=tuple(
                MissingConfigurationV1(code=item.code, scope=item.scope, severity=item.severity)
                for item in setup.missing_configuration[:DEFAULT_SETUP_ITEM_LIMIT]
            ),
            validation_messages=tuple(
                ValidationMessageV1(
                    code=item.code,
                    severity=item.severity,
                    scope=item.scope,
                    summary=item.summary,
                )
                for item in setup.validation_messages[:DEFAULT_SETUP_ITEM_LIMIT]
            ),
        )

    def _read(self) -> tuple[FrontendApiEvidenceV1, datetime]:
        evidence = self._source.snapshot()
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Frontend API clock must return a timezone-aware datetime")
        return evidence, now


def _zone(zone: ZoneEvidenceV1, now: datetime) -> ZoneV1:
    measurement_state, age = _measurement_state(zone, now)
    demand_state: DemandStatus = "indeterminate"
    if zone.demand_requires_heat is not None and _is_current(zone.demand_observed_at, zone.measurement_max_age, now):
        demand_state = "heat_required" if zone.demand_requires_heat else "no_heat_required"
    return ZoneV1(
        zone_id=zone.zone_id,
        name=zone.name,
        current_temperature_c=zone.measurement_temperature_c,
        measurement_state=measurement_state,
        measurement_age_seconds=age,
        target_temperature_c=zone.target_temperature_c,
        demand_state=demand_state,
        demand_reason_code=zone.demand_reason_code,
        last_decision=_decision_summary(zone.last_decision),
    )


def _measurement_state(zone: ZoneEvidenceV1, now: datetime) -> tuple[MeasurementState, float | None]:
    observed_at = zone.measurement_observed_at
    if zone.measurement_temperature_c is None or observed_at is None:
        return "missing", None
    age = (now - observed_at).total_seconds()
    if age < 0:
        return "future_dated", age
    if zone.measurement_max_age is None or age > zone.measurement_max_age.total_seconds():
        return "expired", age
    return "fresh", age


def _is_current(observed_at: datetime | None, max_age: timedelta | None, now: datetime) -> bool:
    if observed_at is None or max_age is None:
        return False
    age = (now - observed_at).total_seconds()
    return 0 <= age <= max_age.total_seconds()


def _decision_summary(decision: DecisionEvidenceV1 | None) -> DecisionSummaryV1 | None:
    if decision is None:
        return None
    return DecisionSummaryV1(
        decision_id=decision.decision_id,
        action=decision.action,
        observed_at=decision.observed_at.isoformat(),
        reason_code=decision.reason_code,
    )


def _attention(item: AttentionEvidenceV1) -> AttentionV1:
    return AttentionV1(
        attention_id=item.attention_id,
        severity=item.severity,
        code=item.code,
        scope=item.scope,
        summary=item.summary,
        first_seen_at=item.first_seen_at.isoformat(),
    )


def _event(item: OperationalEventEvidenceV1) -> OperationalEventV1:
    command = None
    if item.requested_command is not None or item.command_outcome is not None:
        command = EventCommandV1(action=item.requested_command, outcome=item.command_outcome)
    return OperationalEventV1(
        event_id=item.event_id,
        timestamp=item.timestamp.isoformat(),
        category=item.category,
        severity=item.severity,
        event_code=item.event_code,
        summary_code=item.summary_code,
        reason_code=item.reason_code,
        scope=item.scope,
        previous_state=item.previous_state,
        new_state=item.new_state,
        command=command,
    )


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

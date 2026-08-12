"""Immutable state for bounded source-controller reconciliation."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.source_control import ReportedSourceEvidence, SourceOwnership


class SourceReconciliationStatus(StrEnum):
    OBSERVED_EXTERNAL = "observed_external"
    EXPECTED_UNKNOWN = "expected_unknown"
    REPORTED_INDETERMINATE = "reported_indeterminate"
    AGREED = "agreed"
    DRIFT_HOLDING = "drift_holding"
    CORRECTION_REQUIRED = "correction_required"
    CORRECTION_PENDING = "correction_pending"


class SourceReconciliationReason(StrEnum):
    EXTERNAL_OWNERSHIP = "external_ownership"
    EXPECTED_STATE_UNKNOWN = "expected_state_unknown"
    REPORTED_STATE_UNKNOWN = "reported_state_unknown"
    REPORTED_STATE_UNAVAILABLE = "reported_state_unavailable"
    REPORTED_STATE_AGREES = "reported_state_agrees"
    UNKNOWN_TRANSITION_AGE_HOLD = "unknown_transition_age_hold"
    KNOWN_TRANSITION_DRIFT = "known_transition_drift"
    CONSERVATIVE_HOLD_EXPIRED = "conservative_hold_expired"
    AWAITING_REPORTED_AGREEMENT = "awaiting_reported_agreement"
    CORRECTIVE_COMMAND_FAILED_RETRY_WAIT = "corrective_command_failed_retry_wait"
    CORRECTIVE_RETRY_DUE = "corrective_retry_due"


@dataclass(frozen=True)
class SourceReconciliationState:
    ownership: SourceOwnership
    desired_command: HeatingAction | None
    last_successful_command: HeatingAction | None
    reported: ReportedSourceEvidence | None
    status: SourceReconciliationStatus
    reason: SourceReconciliationReason
    drift_detected_at: datetime | None
    conservative_hold_deadline: datetime | None
    corrective_intent: HeatingAction | None
    next_reevaluation_at: datetime | None
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        for value, expected, label in (
            (self.ownership, SourceOwnership, "ownership"),
            (self.status, SourceReconciliationStatus, "status"),
            (self.reason, SourceReconciliationReason, "reason"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"{label} must be a {expected.__name__}")
        for label, value in (
            ("desired_command", self.desired_command),
            ("last_successful_command", self.last_successful_command),
            ("corrective_intent", self.corrective_intent),
        ):
            if value is not None and not isinstance(value, HeatingAction):
                raise TypeError(f"{label} must be a HeatingAction or None")
        for label, value in (
            ("drift_detected_at", self.drift_detected_at),
            ("conservative_hold_deadline", self.conservative_hold_deadline),
            ("next_reevaluation_at", self.next_reevaluation_at),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")


@dataclass(frozen=True)
class SourceReconciliationAssessment:
    state: SourceReconciliationState
    status: SourceReconciliationStatus
    reason: SourceReconciliationReason
    corrective_command: HeatingAction | None
    next_reevaluation_at: datetime | None

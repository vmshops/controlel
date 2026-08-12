"""Explicit bounded runtime recovery state."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SourceRecoveryStatus(StrEnum):
    WAITING = "waiting"
    COMPLETE = "complete"


class SourceRecoveryReason(StrEnum):
    RECOVERY_STARTED = "recovery_started"
    WAITING_FOR_DEMAND = "waiting_for_demand"
    WAITING_FOR_REPORTED_SOURCE = "waiting_for_reported_source"
    WAITING_FOR_DEMAND_AND_REPORTED_SOURCE = "waiting_for_demand_and_reported_source"
    EVIDENCE_READY = "evidence_ready"
    DEADLINE_ELAPSED_WITH_INCOMPLETE_EVIDENCE = "deadline_elapsed_with_incomplete_evidence"


@dataclass(frozen=True)
class SourceRecoveryState:
    status: SourceRecoveryStatus
    reason: SourceRecoveryReason
    started_at: datetime
    deadline: datetime
    demand_known: bool
    reported_source_known: bool
    completed_at: datetime | None
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("started_at", self.started_at),
            ("deadline", self.deadline),
            ("completed_at", self.completed_at),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        if self.deadline < self.started_at:
            raise ValueError("deadline must not precede started_at")
        if self.status is SourceRecoveryStatus.COMPLETE and self.completed_at is None:
            raise ValueError("complete recovery requires completed_at")
        if self.status is SourceRecoveryStatus.WAITING and self.completed_at is not None:
            raise ValueError("waiting recovery cannot have completed_at")


@dataclass(frozen=True)
class SourceRecoveryAssessment:
    state: SourceRecoveryState
    status: SourceRecoveryStatus
    reason: SourceRecoveryReason
    blocks_source_commands: bool
    deadline: datetime | None

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.domain.commands.heating_action import HeatingAction


class FatalShutdownEmergencyOutcome(StrEnum):
    DISABLE_DISPATCHED = "fatal_shutdown_disable_dispatched"
    DISABLE_FAILED = "fatal_shutdown_disable_failed"
    DISABLE_SKIPPED_ALREADY_FAILED = "fatal_shutdown_disable_skipped_already_failed"


@dataclass(frozen=True)
class FatalShutdownResult:
    emergency_disable_attempted: bool
    emergency_disable_outcome: FatalShutdownEmergencyOutcome
    timestamp: datetime
    original_failed_action: HeatingAction | None
    emergency_failure_type: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("fatal shutdown timestamp must be timezone-aware")
        if self.original_failed_action is not None and not isinstance(
            self.original_failed_action,
            HeatingAction,
        ):
            raise TypeError("original_failed_action must be a HeatingAction or None")
        attempted_outcomes = {
            FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED,
            FatalShutdownEmergencyOutcome.DISABLE_FAILED,
        }
        if self.emergency_disable_attempted != (self.emergency_disable_outcome in attempted_outcomes):
            raise ValueError("emergency attempt flag does not match outcome")
        if (self.emergency_disable_outcome is FatalShutdownEmergencyOutcome.DISABLE_FAILED) != (
            self.emergency_failure_type is not None
        ):
            raise ValueError("emergency failure type must exist only for a failed attempt")

"""Immutable contracts for bounded runtime supervision."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class CommandAuthority(StrEnum):
    NORMAL = "normal"
    FAILSAFE = "failsafe"
    NONE = "none"


class SupervisorPhase(StrEnum):
    NORMAL = "normal"
    FAILSAFE = "failsafe"
    RESTART_WAIT = "restart_wait"
    RESTART_EXHAUSTED = "restart_exhausted"


class FailsafeReason(StrEnum):
    VALID_TRUSTED_EVIDENCE = "valid_trusted_evidence"
    TRUSTED_EVIDENCE_UNAVAILABLE = "trusted_evidence_unavailable"
    MANUAL_RECOVERY = "manual_recovery"


class FatalCauseCode(StrEnum):
    INVALID_RUNTIME_STATE = "invalid_runtime_state"
    RUNTIME_FAILURE = "runtime_failure"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    FAILSAFE_DISPATCH_FAILED = "failsafe_dispatch_failed"


@dataclass(frozen=True)
class RestartPolicy:
    """Finite deterministic restart campaign configuration."""

    attempt_limit: int = 3
    retry_interval: timedelta = timedelta(minutes=5)
    manual_recovery_duration: timedelta = timedelta(hours=2)

    def __post_init__(self) -> None:
        if isinstance(self.attempt_limit, bool) or self.attempt_limit < 1:
            raise ValueError("attempt_limit must be a positive integer")
        if self.retry_interval <= timedelta(0):
            raise ValueError("retry_interval must be positive")
        if self.manual_recovery_duration <= timedelta(0):
            raise ValueError("manual_recovery_duration must be positive")

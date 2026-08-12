"""Immutable active operating-mode state."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.domain.operating_mode import OperatingMode


class OperatingModeReason(StrEnum):
    NORMAL_OPERATION = "normal_operation"
    USER_SELECTED = "user_selected"
    SAFE_HEATING_PREFERRED_EVIDENCE = "safe_heating_preferred_evidence"
    SAFE_HEATING_FALLBACK_EVIDENCE = "safe_heating_fallback_evidence"
    SAFE_HEATING_EVIDENCE_UNAVAILABLE = "safe_heating_evidence_unavailable"
    EMERGENCY_OFF_ACTIVE = "emergency_off_active"
    MANUAL_RECOVERY_ACTIVE = "manual_recovery_active"
    MANUAL_RECOVERY_EXPIRED = "manual_recovery_expired"
    MANUAL_RECOVERY_CANCELLED_RELOAD = "manual_recovery_cancelled_reload"


@dataclass(frozen=True)
class OperatingModeState:
    mode: OperatingMode
    reason: OperatingModeReason
    activated_at: datetime
    manual_recovery_deadline: datetime | None
    safe_heating_requires_heat: bool | None
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OperatingMode):
            raise TypeError("mode must be an OperatingMode")
        if not isinstance(self.reason, OperatingModeReason):
            raise TypeError("reason must be an OperatingModeReason")
        for label, value in (
            ("activated_at", self.activated_at),
            ("manual_recovery_deadline", self.manual_recovery_deadline),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        if self.mode is OperatingMode.MANUAL_RECOVERY_HEAT:
            if self.manual_recovery_deadline is None:
                raise ValueError("manual recovery requires a deadline")
        elif self.manual_recovery_deadline is not None:
            raise ValueError("only manual recovery may have a deadline")

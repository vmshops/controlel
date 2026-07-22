from dataclasses import dataclass
from enum import StrEnum

from controlel.domain.commands.command import Command
from controlel.domain.events.decision_event import DecisionCreatedEvent


class RuntimeProcessingStatus(StrEnum):
    NO_DECISION = "no_decision"
    DECISION_WITHOUT_COMMAND = "decision_without_command"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_SUPPRESSED = "command_suppressed"


class TemperatureNoDecisionReason(StrEnum):
    TIMESTAMP_ADMISSION_REJECTED = "timestamp_admission_rejected"
    OUT_OF_ORDER = "out_of_order"
    SECONDARY_MEASUREMENT = "secondary_measurement"
    PRIMARY_MEASUREMENT_MISSING = "primary_measurement_missing"
    PRIMARY_MEASUREMENT_EXPIRED = "primary_measurement_expired"
    PRIMARY_MEASUREMENT_FUTURE_DATED = "primary_measurement_future_dated"


@dataclass(frozen=True)
class RuntimeProcessingResult:
    status: RuntimeProcessingStatus
    reason: TemperatureNoDecisionReason | None = None
    decision_event: DecisionCreatedEvent | None = None
    command: Command | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProcessingStatus):
            raise TypeError("status must be a RuntimeProcessingStatus")
        if self.reason is not None and not isinstance(self.reason, TemperatureNoDecisionReason):
            raise TypeError("reason must be a TemperatureNoDecisionReason or None")
        if self.decision_event is not None and not isinstance(self.decision_event, DecisionCreatedEvent):
            raise TypeError("decision_event must be a DecisionCreatedEvent or None")
        if self.command is not None and not isinstance(self.command, Command):
            raise TypeError("command must be a Command or None")

        if self.status is RuntimeProcessingStatus.NO_DECISION:
            if self.reason is None or self.decision_event is not None or self.command is not None:
                raise ValueError("NO_DECISION requires only a reason")
            return

        if self.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND:
            if self.reason is not None or self.decision_event is None or self.command is not None:
                raise ValueError("DECISION_WITHOUT_COMMAND requires only a decision_event")
            return

        if self.reason is not None or self.decision_event is None or self.command is None:
            raise ValueError(f"{self.status.name} requires a decision_event and command without a reason")

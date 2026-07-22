from dataclasses import FrozenInstanceError

import pytest

from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.domain.commands.command import Command
from controlel.domain.decisions.decision import Decision
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def create_decision_event() -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            sensor_id=SensorId(value="living_room_temperature"),
            zone_id=ZoneId(value="living_room"),
            action="enable_heating",
        )
    )


def create_command() -> Command:
    return Command(
        zone_id=ZoneId(value="living_room"),
        command_type="heating",
        action="enable_heating",
    )


def test_runtime_processing_status_has_stable_string_values():
    assert {status.name: status.value for status in RuntimeProcessingStatus} == {
        "NO_DECISION": "no_decision",
        "DECISION_WITHOUT_COMMAND": "decision_without_command",
        "COMMAND_EXECUTED": "command_executed",
        "COMMAND_SUPPRESSED": "command_suppressed",
    }
    assert all(isinstance(status, str) for status in RuntimeProcessingStatus)


def test_temperature_no_decision_reason_has_stable_string_values():
    assert {reason.name: reason.value for reason in TemperatureNoDecisionReason} == {
        "TIMESTAMP_ADMISSION_REJECTED": "timestamp_admission_rejected",
        "OUT_OF_ORDER": "out_of_order",
        "SECONDARY_MEASUREMENT": "secondary_measurement",
        "PRIMARY_MEASUREMENT_MISSING": "primary_measurement_missing",
        "PRIMARY_MEASUREMENT_EXPIRED": "primary_measurement_expired",
        "PRIMARY_MEASUREMENT_FUTURE_DATED": "primary_measurement_future_dated",
    }
    assert all(isinstance(reason, str) for reason in TemperatureNoDecisionReason)


def test_runtime_processing_result_is_immutable():
    result = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.NO_DECISION,
        reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
    )

    with pytest.raises(FrozenInstanceError):
        result.reason = TemperatureNoDecisionReason.SECONDARY_MEASUREMENT


def test_accepts_every_valid_status_combination():
    decision_event = create_decision_event()
    command = create_command()

    no_decision = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.NO_DECISION,
        reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
    )
    without_command = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
        decision_event=decision_event,
    )
    executed = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.COMMAND_EXECUTED,
        decision_event=decision_event,
        command=command,
    )
    suppressed = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.COMMAND_SUPPRESSED,
        decision_event=decision_event,
        command=command,
    )

    assert no_decision.reason is TemperatureNoDecisionReason.OUT_OF_ORDER
    assert without_command.decision_event is decision_event
    assert executed.command is command
    assert suppressed.command is command


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"decision_event": create_decision_event()},
        {"command": create_command()},
        {
            "reason": TemperatureNoDecisionReason.OUT_OF_ORDER,
            "decision_event": create_decision_event(),
        },
    ],
)
def test_no_decision_rejects_invalid_field_combinations(fields):
    with pytest.raises(ValueError, match="NO_DECISION requires only a reason"):
        RuntimeProcessingResult(status=RuntimeProcessingStatus.NO_DECISION, **fields)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {
            "reason": TemperatureNoDecisionReason.OUT_OF_ORDER,
            "decision_event": create_decision_event(),
        },
        {
            "decision_event": create_decision_event(),
            "command": create_command(),
        },
    ],
)
def test_decision_without_command_rejects_invalid_field_combinations(fields):
    with pytest.raises(
        ValueError,
        match="DECISION_WITHOUT_COMMAND requires only a decision_event",
    ):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
            **fields,
        )


@pytest.mark.parametrize(
    "status",
    [RuntimeProcessingStatus.COMMAND_EXECUTED, RuntimeProcessingStatus.COMMAND_SUPPRESSED],
)
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"decision_event": create_decision_event()},
        {"command": create_command()},
        {
            "reason": TemperatureNoDecisionReason.OUT_OF_ORDER,
            "decision_event": create_decision_event(),
            "command": create_command(),
        },
    ],
)
def test_command_statuses_reject_invalid_field_combinations(status, fields):
    with pytest.raises(ValueError, match="requires a decision_event and command without a reason"):
        RuntimeProcessingResult(status=status, **fields)

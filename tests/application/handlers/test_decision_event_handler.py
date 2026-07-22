from datetime import UTC, datetime

from controlel.application.handlers.decision_event_handler import DecisionEventHandler
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def create_event(action: DecisionAction, **decision_fields) -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            sensor_id=SensorId(value="living_room_temperature"),
            zone_id=ZoneId(value="living_room"),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            action=action,
            **decision_fields,
        )
    )


def test_enable_heating_decision_creates_heating_command():
    command = DecisionEventHandler().handle(create_event(DecisionAction.ENABLE_HEATING))

    assert command is not None
    assert command.command_type is CommandFamily.HEATING
    assert command.action is HeatingAction.ENABLE_HEATING
    assert command.zone_id == ZoneId(value="living_room")


def test_disable_heating_decision_creates_heating_command():
    command = DecisionEventHandler().handle(create_event(DecisionAction.DISABLE_HEATING))

    assert command is not None
    assert command.command_type is CommandFamily.HEATING
    assert command.action is HeatingAction.DISABLE_HEATING
    assert command.zone_id == ZoneId(value="living_room")


def test_observe_only_decision_does_not_create_command():
    command = DecisionEventHandler().handle(create_event(DecisionAction.OBSERVE_ONLY))

    assert command is None


def test_reason_and_metadata_do_not_become_executable_fields():
    command = DecisionEventHandler().handle(
        create_event(
            DecisionAction.ENABLE_HEATING,
            reason="temperature_below_target",
            metadata={"current_temperature": 19},
        )
    )

    assert command is not None
    assert set(command.model_dump()) == {
        "id",
        "created_at",
        "zone_id",
        "command_type",
        "action",
    }

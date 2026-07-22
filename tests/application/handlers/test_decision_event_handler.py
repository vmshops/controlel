from controlel.application.handlers.decision_event_handler import DecisionEventHandler
from controlel.domain.decisions.decision import Decision
from controlel.domain.events.decision_event import DecisionCreatedEvent


def create_event(action: str, **decision_fields) -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            action=action,
            **decision_fields,
        )
    )


def test_enable_heating_decision_creates_heating_command():
    command = DecisionEventHandler().handle(create_event("enable_heating"))

    assert command is not None
    assert command.command_type == "heating"
    assert command.action == "enable_heating"


def test_disable_heating_decision_creates_heating_command():
    command = DecisionEventHandler().handle(create_event("disable_heating"))

    assert command is not None
    assert command.command_type == "heating"
    assert command.action == "disable_heating"


def test_unsupported_decision_does_not_create_command():
    command = DecisionEventHandler().handle(create_event("observe_only"))

    assert command is None


def test_reason_and_metadata_do_not_become_executable_fields():
    command = DecisionEventHandler().handle(
        create_event(
            "enable_heating",
            reason="temperature_below_target",
            metadata={"current_temperature": 19},
        )
    )

    assert command is not None
    assert set(command.model_dump()) == {
        "id",
        "created_at",
        "command_type",
        "action",
    }

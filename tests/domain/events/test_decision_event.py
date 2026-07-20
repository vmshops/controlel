from controlel.domain.decisions.decision import Decision
from controlel.domain.events.decision_event import DecisionCreatedEvent


def test_decision_created_event_contains_decision():
    decision = Decision(
        action="enable_heating",
        reason="temperature_below_target",
    )

    event = DecisionCreatedEvent(
        decision=decision,
    )

    assert event.decision == decision

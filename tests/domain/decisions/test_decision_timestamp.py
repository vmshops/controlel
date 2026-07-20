from datetime import UTC, datetime

from controlel.domain.decisions.decision import Decision


def test_decision_contains_timestamp():
    decision = Decision(
        action="enable_heating",
        reason="temperature_below_target",
    )

    assert isinstance(decision.timestamp, datetime)
    assert decision.timestamp.tzinfo == UTC

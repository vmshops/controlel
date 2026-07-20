from controlel.domain.decisions.decision import Decision


def test_decision_contains_reason():
    decision = Decision(
        action="enable_heating",
        reason="temperature_below_target",
    )

    assert decision.reason == "temperature_below_target"

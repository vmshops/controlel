from controlel.domain.decisions.decision import Decision


def test_decision_contains_metadata():
    decision = Decision(
        action="enable_heating",
        reason="temperature_below_target",
        metadata={
            "current_temperature": 20,
            "target_temperature": 22,
        },
    )

    assert decision.metadata["current_temperature"] == 20
    assert decision.metadata["target_temperature"] == 22

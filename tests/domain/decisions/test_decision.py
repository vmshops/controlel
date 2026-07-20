from controlel.domain.decisions.decision import Decision


def test_decision_creation():
    decision = Decision(
        action="enable_heating",
    )

    assert decision.action == "enable_heating"

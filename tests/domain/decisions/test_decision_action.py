from enum import StrEnum

from controlel.domain.decisions.decision_action import DecisionAction


def test_decision_action_has_exact_stable_values_without_aliases():
    assert list(DecisionAction) == [
        DecisionAction.ENABLE_HEATING,
        DecisionAction.DISABLE_HEATING,
        DecisionAction.OBSERVE_ONLY,
    ]
    assert [action.value for action in DecisionAction] == [
        "enable_heating",
        "disable_heating",
        "observe_only",
    ]
    assert len(DecisionAction.__members__) == len(DecisionAction)


def test_decision_action_is_string_backed():
    assert issubclass(DecisionAction, StrEnum)
    assert isinstance(DecisionAction.ENABLE_HEATING, str)

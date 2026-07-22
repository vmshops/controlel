from enum import StrEnum

from controlel.domain.commands.heating_action import HeatingAction


def test_heating_action_has_exact_stable_values_without_aliases():
    assert list(HeatingAction) == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert [action.value for action in HeatingAction] == [
        "enable_heating",
        "disable_heating",
    ]
    assert len(HeatingAction.__members__) == len(HeatingAction)


def test_heating_action_is_string_backed_and_excludes_observe_only():
    assert issubclass(HeatingAction, StrEnum)
    assert isinstance(HeatingAction.ENABLE_HEATING, str)
    assert not hasattr(HeatingAction, "OBSERVE_ONLY")

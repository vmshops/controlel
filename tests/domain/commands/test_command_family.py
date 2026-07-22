from enum import StrEnum

from controlel.domain.commands.command_family import CommandFamily


def test_command_family_has_exact_stable_value_without_aliases():
    assert list(CommandFamily) == [CommandFamily.HEATING]
    assert CommandFamily.HEATING.value == "heating"
    assert len(CommandFamily.__members__) == len(CommandFamily)


def test_command_family_is_string_backed():
    assert issubclass(CommandFamily, StrEnum)
    assert isinstance(CommandFamily.HEATING, str)

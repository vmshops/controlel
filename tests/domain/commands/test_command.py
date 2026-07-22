from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.commands.command import Command
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.zone_id import ZoneId

ZONE_ID = ZoneId(value="living_room")


def create_command(
    action: HeatingAction | str = HeatingAction.ENABLE_HEATING,
    command_type: CommandFamily | str = CommandFamily.HEATING,
) -> Command:
    return Command(
        zone_id=ZONE_ID,
        command_type=command_type,
        action=action,
    )


@pytest.mark.parametrize("action", list(HeatingAction))
def test_command_accepts_and_retains_each_typed_heating_action(action: HeatingAction):
    command = create_command(action=action)

    assert command.action is action
    assert command.command_type is CommandFamily.HEATING


@pytest.mark.parametrize("action", list(HeatingAction))
def test_command_parses_valid_serialized_values(action: HeatingAction):
    command = create_command(action=action.value, command_type="heating")

    assert type(command.action) is HeatingAction
    assert command.action is action
    assert type(command.command_type) is CommandFamily
    assert command.command_type is CommandFamily.HEATING


@pytest.mark.parametrize("invalid_action", ["observe_only", "unknown", "enable_heatin"])
def test_command_rejects_non_executable_unknown_or_misspelled_action(invalid_action: str):
    with pytest.raises(ValidationError, match="action"):
        create_command(action=invalid_action)


def test_command_rejects_unknown_command_family():
    with pytest.raises(ValidationError, match="command_type"):
        create_command(command_type="cooling")


def test_command_creation_generates_identity_and_aware_timestamp():
    command = create_command()

    assert command.id is not None
    assert isinstance(command.created_at, datetime)
    assert command.created_at.tzinfo == UTC
    assert command.zone_id is ZONE_ID


def test_command_serialization_preserves_types_in_python_and_values_in_json():
    command = create_command()

    python_data = command.model_dump()
    json_data = command.model_dump(mode="json")

    assert python_data["command_type"] is CommandFamily.HEATING
    assert python_data["action"] is HeatingAction.ENABLE_HEATING
    assert json_data["command_type"] == "heating"
    assert json_data["action"] == "enable_heating"


def test_command_zone_id_is_required():
    with pytest.raises(ValidationError, match="zone_id"):
        Command(
            command_type=CommandFamily.HEATING,
            action=HeatingAction.ENABLE_HEATING,
        )


def test_command_type_is_required():
    with pytest.raises(ValidationError, match="command_type"):
        Command(zone_id=ZONE_ID, action=HeatingAction.ENABLE_HEATING)


def test_command_action_is_required():
    with pytest.raises(ValidationError, match="action"):
        Command(zone_id=ZONE_ID, command_type=CommandFamily.HEATING)

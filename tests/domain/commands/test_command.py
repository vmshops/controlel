from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.commands.command import Command
from controlel.domain.value_objects.zone_id import ZoneId


def test_command_creation_generates_identity_and_aware_timestamp():
    command = Command(
        zone_id=ZoneId(value="living_room"),
        command_type="heating",
        action="enable_heating",
    )

    assert command.id is not None
    assert isinstance(command.created_at, datetime)
    assert command.created_at.tzinfo == UTC
    assert command.zone_id == ZoneId(value="living_room")


def test_command_zone_id_is_required():
    with pytest.raises(ValidationError, match="zone_id"):
        Command(
            command_type="heating",
            action="enable_heating",
        )


def test_command_type_is_required():
    with pytest.raises(ValidationError, match="command_type"):
        Command(
            zone_id=ZoneId(value="living_room"),
            action="enable_heating",
        )


def test_command_action_is_required():
    with pytest.raises(ValidationError, match="action"):
        Command(
            zone_id=ZoneId(value="living_room"),
            command_type="heating",
        )

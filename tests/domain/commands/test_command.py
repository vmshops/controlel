from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.commands.command import Command


def test_command_creation_generates_identity_and_aware_timestamp():
    command = Command(
        command_type="heating",
        action="enable_heating",
    )

    assert command.id is not None
    assert isinstance(command.created_at, datetime)
    assert command.created_at.tzinfo == UTC


def test_command_type_is_required():
    with pytest.raises(ValidationError, match="command_type"):
        Command(action="enable_heating")


def test_command_action_is_required():
    with pytest.raises(ValidationError, match="action"):
        Command(command_type="heating")

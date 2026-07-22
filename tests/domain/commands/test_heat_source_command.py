from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction


def test_heat_source_command_has_typed_fields_and_no_zone_id():
    command = HeatSourceCommand(
        command_type=CommandFamily.HEATING,
        action=HeatingAction.ENABLE_HEATING,
    )

    assert command.command_type is CommandFamily.HEATING
    assert command.action is HeatingAction.ENABLE_HEATING
    assert command.created_at.tzinfo == UTC
    assert "zone_id" not in HeatSourceCommand.model_fields
    assert command.model_dump(mode="json")["command_type"] == "heating"
    assert command.model_dump(mode="json")["action"] == "enable_heating"


def test_heat_source_command_requires_command_type_and_action():
    with pytest.raises(ValidationError, match="command_type"):
        HeatSourceCommand(action=HeatingAction.ENABLE_HEATING)
    with pytest.raises(ValidationError, match="action"):
        HeatSourceCommand(command_type=CommandFamily.HEATING)


def test_heat_source_command_rejects_naive_created_at():
    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        HeatSourceCommand(
            created_at=datetime(2026, 1, 1),
            command_type=CommandFamily.HEATING,
            action=HeatingAction.ENABLE_HEATING,
        )

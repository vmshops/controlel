from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.states.heat_source_control_state import HeatSourceControlState


def test_heat_source_control_state_is_immutable_and_has_no_zone_id():
    command_id = uuid4()
    state = HeatSourceControlState(
        applied_action=HeatingAction.ENABLE_HEATING,
        command_id=command_id,
    )

    assert state.applied_action is HeatingAction.ENABLE_HEATING
    assert state.command_id == command_id
    assert state.applied_at.tzinfo == UTC
    assert "zone_id" not in HeatSourceControlState.model_fields
    with pytest.raises(ValidationError, match="frozen"):
        state.applied_action = HeatingAction.DISABLE_HEATING


def test_heat_source_control_state_rejects_naive_applied_at():
    with pytest.raises(ValidationError, match="applied_at must be timezone-aware"):
        HeatSourceControlState(
            applied_action=HeatingAction.ENABLE_HEATING,
            command_id=uuid4(),
            applied_at=datetime(2026, 1, 1),
        )

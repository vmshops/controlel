from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from controlel.domain.states.control_state import ControlState
from controlel.domain.value_objects.zone_id import ZoneId


def create_state() -> ControlState:
    return ControlState(
        zone_id=ZoneId(value="living_room"),
        applied_action="enable_heating",
        command_id=uuid4(),
    )


def test_control_state_preserves_applied_zone_action_and_command_identity():
    command_id = uuid4()
    state = ControlState(
        zone_id=ZoneId(value="living_room"),
        applied_action="enable_heating",
        command_id=command_id,
    )

    assert state.zone_id == ZoneId(value="living_room")
    assert state.applied_action == "enable_heating"
    assert state.command_id == command_id
    assert isinstance(state.applied_at, datetime)
    assert state.applied_at.tzinfo == UTC


def test_control_state_requires_zone_id():
    with pytest.raises(ValidationError, match="zone_id"):
        ControlState(
            applied_action="enable_heating",
            command_id=uuid4(),
        )


def test_control_state_requires_applied_action():
    with pytest.raises(ValidationError, match="applied_action"):
        ControlState(
            zone_id=ZoneId(value="living_room"),
            command_id=uuid4(),
        )


def test_control_state_requires_command_id():
    with pytest.raises(ValidationError, match="command_id"):
        ControlState(
            zone_id=ZoneId(value="living_room"),
            applied_action="enable_heating",
        )


def test_applied_at_is_generated_independently_per_instance():
    first = create_state()
    second = create_state()

    assert first.applied_at is not second.applied_at
    assert first.applied_at.tzinfo == UTC
    assert second.applied_at.tzinfo == UTC


def test_applied_at_must_be_timezone_aware():
    with pytest.raises(ValidationError, match="applied_at must be timezone-aware"):
        ControlState(
            zone_id=ZoneId(value="living_room"),
            applied_action="enable_heating",
            command_id=uuid4(),
            applied_at=datetime(2026, 1, 1),
        )


def test_control_state_is_immutable():
    state = create_state()

    with pytest.raises(ValidationError):
        state.applied_action = "disable_heating"


def test_control_state_contains_no_measurement_or_target_fields():
    assert "current_temperature" not in ControlState.model_fields
    assert "target_temperature" not in ControlState.model_fields
    assert "heating_active" not in ControlState.model_fields

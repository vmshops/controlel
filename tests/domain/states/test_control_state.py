from datetime import UTC, datetime

from controlel.domain.states.control_state import ControlState
from controlel.domain.value_objects.temperature import Temperature


def test_control_state_creation():
    state = ControlState(
        current_temperature=Temperature(19),
        target_temperature=Temperature(22),
    )

    assert state.heating_enabled is False
    assert isinstance(state.updated_at, datetime)
    assert state.updated_at.tzinfo == UTC

from controlel.domain.states.state import State


def test_state_creation():
    state = State(state_type="test_state")

    assert state.state_type == "test_state"
    assert state.id is not None
    assert state.updated_at is not None

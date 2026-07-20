from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.states.control_state import ControlState
from controlel.domain.value_objects.temperature import Temperature


def test_state_repository_stores_state():
    repository = StateRepository()

    state = ControlState(
        current_temperature=Temperature(19),
        target_temperature=Temperature(22),
    )

    repository.save(state)

    result = repository.get()

    assert result == state

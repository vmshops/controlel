from uuid import uuid4

from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.states.control_state import ControlState
from controlel.domain.value_objects.zone_id import ZoneId


def create_state(zone_id: str, action: str) -> ControlState:
    return ControlState(
        zone_id=ZoneId(value=zone_id),
        applied_action=action,
        command_id=uuid4(),
    )


def test_empty_zone_lookup_returns_none():
    repository = StateRepository()

    assert repository.get(ZoneId(value="living_room")) is None


def test_saves_and_returns_exact_state_by_zone_id():
    repository = StateRepository()
    state = create_state("living_room", "enable_heating")

    repository.save(state)

    assert repository.get(state.zone_id) is state


def test_different_zones_remain_independent():
    repository = StateRepository()
    living_room = create_state("living_room", "enable_heating")
    bedroom = create_state("bedroom", "disable_heating")

    repository.save(living_room)
    repository.save(bedroom)

    assert repository.get(living_room.zone_id) is living_room
    assert repository.get(bedroom.zone_id) is bedroom


def test_replacing_one_zone_does_not_change_another_zone():
    repository = StateRepository()
    living_room_first = create_state("living_room", "enable_heating")
    living_room_second = create_state("living_room", "disable_heating")
    bedroom = create_state("bedroom", "enable_heating")
    repository.save(living_room_first)
    repository.save(bedroom)

    repository.save(living_room_second)

    assert repository.get(living_room_second.zone_id) is living_room_second
    assert repository.get(bedroom.zone_id) is bedroom

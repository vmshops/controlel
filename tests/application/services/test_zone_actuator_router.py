import pytest

from controlel.application.services.zone_actuator_router import (
    ActuatorRouteNotFoundError,
    ZoneActuatorRouter,
)
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.value_objects.zone_id import ZoneId


class RecordingActuator(ActuatorPort):
    def __init__(self):
        self.commands: list[Command] = []

    def execute(self, command: Command) -> None:
        self.commands.append(command)


def test_resolves_exact_configured_port_for_typed_zone_id():
    zone_id = ZoneId(value="living_room")
    actuator = RecordingActuator()
    router = ZoneActuatorRouter({zone_id: actuator})

    resolved = router.resolve(zone_id)

    assert resolved is actuator


def test_missing_route_raises_explicit_error_without_default():
    zone_id = ZoneId(value="living_room")
    router = ZoneActuatorRouter({})

    with pytest.raises(
        ActuatorRouteNotFoundError,
        match="No actuator route is configured for zone 'living_room'",
    ) as raised:
        router.resolve(zone_id)

    assert raised.value.zone_id is zone_id


def test_different_zones_resolve_to_different_ports():
    living_room_id = ZoneId(value="living_room")
    bedroom_id = ZoneId(value="bedroom")
    living_room_actuator = RecordingActuator()
    bedroom_actuator = RecordingActuator()
    router = ZoneActuatorRouter(
        {
            living_room_id: living_room_actuator,
            bedroom_id: bedroom_actuator,
        }
    )

    assert router.resolve(living_room_id) is living_room_actuator
    assert router.resolve(bedroom_id) is bedroom_actuator


def test_multiple_zones_can_resolve_to_same_port():
    living_room_id = ZoneId(value="living_room")
    bedroom_id = ZoneId(value="bedroom")
    shared_actuator = RecordingActuator()
    router = ZoneActuatorRouter(
        {
            living_room_id: shared_actuator,
            bedroom_id: shared_actuator,
        }
    )

    assert router.resolve(living_room_id) is shared_actuator
    assert router.resolve(bedroom_id) is shared_actuator


def test_external_mapping_mutation_does_not_change_routes():
    zone_id = ZoneId(value="living_room")
    original_actuator = RecordingActuator()
    replacement_actuator = RecordingActuator()
    routes = {zone_id: original_actuator}
    router = ZoneActuatorRouter(routes)

    routes[zone_id] = replacement_actuator
    routes.clear()

    assert router.resolve(zone_id) is original_actuator


def test_resolving_route_does_not_change_other_configuration():
    living_room_id = ZoneId(value="living_room")
    bedroom_id = ZoneId(value="bedroom")
    living_room_actuator = RecordingActuator()
    bedroom_actuator = RecordingActuator()
    router = ZoneActuatorRouter(
        {
            living_room_id: living_room_actuator,
            bedroom_id: bedroom_actuator,
        }
    )

    assert router.resolve(living_room_id) is living_room_actuator
    assert router.resolve(living_room_id) is living_room_actuator
    assert router.resolve(bedroom_id) is bedroom_actuator

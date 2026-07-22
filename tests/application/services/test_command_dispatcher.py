import pytest

from controlel.application.services.command_dispatcher import CommandDispatcher
from controlel.application.services.zone_actuator_router import (
    ActuatorRouteNotFoundError,
    ZoneActuatorRouter,
)
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.value_objects.zone_id import ZoneId

LIVING_ROOM_ID = ZoneId(value="living_room")
BEDROOM_ID = ZoneId(value="bedroom")


class RecordingActuator(ActuatorPort):
    def __init__(self):
        self.executed_commands = []

    def execute(self, command: Command) -> None:
        self.executed_commands.append(command)


class ActuatorFailure(Exception):
    pass


class FailingActuator(ActuatorPort):
    def __init__(self, error: Exception):
        self.error = error
        self.attempted_commands = []

    def execute(self, command: Command) -> None:
        self.attempted_commands.append(command)
        raise self.error


class FailOnceActuator(ActuatorPort):
    def __init__(self, error: Exception):
        self.error = error
        self.attempted_commands = []

    def execute(self, command: Command) -> None:
        self.attempted_commands.append(command)
        if len(self.attempted_commands) == 1:
            raise self.error


def create_command(
    action: HeatingAction = HeatingAction.ENABLE_HEATING,
    zone_id: str = "living_room",
) -> Command:
    return Command(
        zone_id=ZoneId(value=zone_id),
        command_type=CommandFamily.HEATING,
        action=action,
    )


def create_dispatcher(
    routes: dict[ZoneId, ActuatorPort],
    repository: StateRepository,
) -> CommandDispatcher:
    return CommandDispatcher(
        actuator_router=ZoneActuatorRouter(routes),
        state_repository=repository,
    )


def test_first_action_executes_exact_command_and_records_applied_state():
    actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher({LIVING_ROOM_ID: actuator}, repository)
    command = create_command()

    executed = dispatcher.dispatch(command)

    state = repository.get(command.zone_id)
    assert executed is True
    assert actuator.executed_commands == [command]
    assert state is not None
    assert state.zone_id == command.zone_id
    assert state.applied_action is command.action
    assert state.command_id == command.id


def test_identical_applied_action_for_same_zone_is_suppressed_without_state_change():
    actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher({LIVING_ROOM_ID: actuator}, repository)
    first = create_command()
    duplicate = create_command()
    dispatcher.dispatch(first)
    applied_state = repository.get(first.zone_id)

    executed = dispatcher.dispatch(duplicate)

    assert executed is False
    assert actuator.executed_commands == [first]
    assert repository.get(first.zone_id) is applied_state


def test_same_action_for_another_zone_executes():
    actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher(
        {
            LIVING_ROOM_ID: actuator,
            BEDROOM_ID: actuator,
        },
        repository,
    )
    living_room = create_command(zone_id="living_room")
    bedroom = create_command(zone_id="bedroom")

    assert dispatcher.dispatch(living_room) is True
    assert dispatcher.dispatch(bedroom) is True
    assert actuator.executed_commands == [living_room, bedroom]
    assert repository.get(living_room.zone_id).command_id == living_room.id
    assert repository.get(bedroom.zone_id).command_id == bedroom.id


def test_opposite_action_executes_and_replaces_zone_state():
    actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher({LIVING_ROOM_ID: actuator}, repository)
    enable = create_command(action=HeatingAction.ENABLE_HEATING)
    disable = create_command(action=HeatingAction.DISABLE_HEATING)
    dispatcher.dispatch(enable)

    executed = dispatcher.dispatch(disable)

    state = repository.get(enable.zone_id)
    assert executed is True
    assert actuator.executed_commands == [enable, disable]
    assert state.applied_action is HeatingAction.DISABLE_HEATING
    assert state.command_id == disable.id


def test_failed_initial_execution_propagates_exact_error_and_records_no_state():
    error = ActuatorFailure("execution failed")
    actuator = FailingActuator(error)
    repository = StateRepository()
    dispatcher = create_dispatcher({LIVING_ROOM_ID: actuator}, repository)
    command = create_command()

    with pytest.raises(ActuatorFailure) as raised:
        dispatcher.dispatch(command)

    assert raised.value is error
    assert actuator.attempted_commands == [command]
    assert repository.get(command.zone_id) is None


def test_failed_transition_preserves_previous_applied_state():
    repository = StateRepository()
    successful_actuator = RecordingActuator()
    enable = create_command(action=HeatingAction.ENABLE_HEATING)
    create_dispatcher({LIVING_ROOM_ID: successful_actuator}, repository).dispatch(enable)
    applied_state = repository.get(enable.zone_id)
    error = ActuatorFailure("transition failed")
    disable = create_command(action=HeatingAction.DISABLE_HEATING)

    with pytest.raises(ActuatorFailure) as raised:
        create_dispatcher(
            {LIVING_ROOM_ID: FailingActuator(error)},
            repository,
        ).dispatch(disable)

    assert raised.value is error
    assert repository.get(enable.zone_id) is applied_state


def test_later_dispatch_retries_action_that_was_not_recorded_after_failure():
    error = ActuatorFailure("temporary failure")
    actuator = FailOnceActuator(error)
    repository = StateRepository()
    dispatcher = create_dispatcher({LIVING_ROOM_ID: actuator}, repository)
    first = create_command()
    retry = create_command()

    with pytest.raises(ActuatorFailure):
        dispatcher.dispatch(first)

    assert dispatcher.dispatch(retry) is True
    assert actuator.attempted_commands == [first, retry]
    assert repository.get(retry.zone_id).command_id == retry.id


def test_different_zones_execute_only_on_their_resolved_ports():
    living_room_actuator = RecordingActuator()
    bedroom_actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher(
        {
            LIVING_ROOM_ID: living_room_actuator,
            BEDROOM_ID: bedroom_actuator,
        },
        repository,
    )
    living_room = create_command(zone_id="living_room")
    bedroom = create_command(zone_id="bedroom")

    assert dispatcher.dispatch(living_room) is True
    assert dispatcher.dispatch(bedroom) is True
    assert living_room_actuator.executed_commands == [living_room]
    assert bedroom_actuator.executed_commands == [bedroom]


def test_missing_route_calls_no_port_and_records_no_state():
    unrelated_actuator = RecordingActuator()
    repository = StateRepository()
    dispatcher = create_dispatcher({BEDROOM_ID: unrelated_actuator}, repository)
    command = create_command(zone_id="living_room")

    with pytest.raises(ActuatorRouteNotFoundError) as raised:
        dispatcher.dispatch(command)

    assert raised.value.zone_id == LIVING_ROOM_ID
    assert unrelated_actuator.executed_commands == []
    assert repository.get(LIVING_ROOM_ID) is None


def test_missing_route_is_detected_before_matching_state_suppression():
    successful_actuator = RecordingActuator()
    unrelated_actuator = RecordingActuator()
    repository = StateRepository()
    first = create_command(zone_id="living_room")
    create_dispatcher({LIVING_ROOM_ID: successful_actuator}, repository).dispatch(first)
    applied_state = repository.get(LIVING_ROOM_ID)
    duplicate = create_command(zone_id="living_room")
    dispatcher_without_route = create_dispatcher(
        {BEDROOM_ID: unrelated_actuator},
        repository,
    )

    with pytest.raises(ActuatorRouteNotFoundError):
        dispatcher_without_route.dispatch(duplicate)

    assert unrelated_actuator.executed_commands == []
    assert repository.get(LIVING_ROOM_ID) is applied_state

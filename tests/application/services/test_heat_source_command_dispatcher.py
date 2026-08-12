import pytest

from controlel.application.services.heat_source_command_dispatcher import (
    HeatSourceCommandDispatcher,
)
from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction


class RecordingHeatSource:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.commands = []
        self.error = RuntimeError("source execution failed")

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if len(self.commands) <= self.failures:
            raise self.error


def create_command(action: HeatingAction) -> HeatSourceCommand:
    return HeatSourceCommand(command_type=CommandFamily.HEATING, action=action)


def test_execute_suppress_and_transition_update_singleton_state():
    port = RecordingHeatSource()
    store = HeatSourceStateStore()
    dispatcher = HeatSourceCommandDispatcher(port, store)
    first = create_command(HeatingAction.ENABLE_HEATING)
    duplicate = create_command(HeatingAction.ENABLE_HEATING)
    disable = create_command(HeatingAction.DISABLE_HEATING)

    assert dispatcher.dispatch(first) is True
    first_state = store.get()
    assert first_state.command_id == first.id
    assert dispatcher.dispatch(duplicate) is False
    assert store.get() is first_state
    assert dispatcher.dispatch(disable) is True
    assert port.commands == [first, disable]
    assert store.get().applied_action is HeatingAction.DISABLE_HEATING
    assert store.get().command_id == disable.id


def test_failure_preserves_state_and_later_dispatch_retries_exact_action():
    port = RecordingHeatSource(failures=1)
    store = HeatSourceStateStore()
    dispatcher = HeatSourceCommandDispatcher(port, store)
    failed = create_command(HeatingAction.ENABLE_HEATING)
    retry = create_command(HeatingAction.ENABLE_HEATING)

    with pytest.raises(RuntimeError) as raised:
        dispatcher.dispatch(failed)

    assert raised.value is port.error
    assert store.get() is None
    assert dispatcher.dispatch(retry) is True
    assert port.commands == [failed, retry]
    assert store.get().command_id == retry.id


def test_failed_transition_preserves_previous_state():
    store = HeatSourceStateStore()
    successful_port = RecordingHeatSource()
    enabled = create_command(HeatingAction.ENABLE_HEATING)
    HeatSourceCommandDispatcher(successful_port, store).dispatch(enabled)
    previous_state = store.get()
    failing_port = RecordingHeatSource(failures=1)

    with pytest.raises(RuntimeError):
        HeatSourceCommandDispatcher(failing_port, store).dispatch(create_command(HeatingAction.DISABLE_HEATING))

    assert store.get() is previous_state


def test_corrective_dispatch_bypasses_only_dispatcher_duplicate_cache():
    port = RecordingHeatSource()
    store = HeatSourceStateStore()
    dispatcher = HeatSourceCommandDispatcher(port, store)
    first = create_command(HeatingAction.DISABLE_HEATING)
    corrective = create_command(HeatingAction.DISABLE_HEATING)

    assert dispatcher.dispatch(first) is True
    assert dispatcher.dispatch(corrective, corrective_reconciliation=True) is True
    assert port.commands == [first, corrective]
    assert store.get().command_id == corrective.id

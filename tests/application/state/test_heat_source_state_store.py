from uuid import uuid4

from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.states.heat_source_control_state import HeatSourceControlState


def create_state(action: HeatingAction) -> HeatSourceControlState:
    return HeatSourceControlState(applied_action=action, command_id=uuid4())


def test_store_is_empty_then_holds_and_replaces_exact_singleton_state():
    store = HeatSourceStateStore()
    enabled = create_state(HeatingAction.ENABLE_HEATING)
    disabled = create_state(HeatingAction.DISABLE_HEATING)

    assert store.get() is None
    store.save(enabled)
    assert store.get() is enabled
    store.save(disabled)
    assert store.get() is disabled

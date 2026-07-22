from datetime import UTC, datetime

from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.heating import HeatingStrategy
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_heating_strategy_enable_heating():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(20),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    strategy = HeatingStrategy()

    decision = strategy.evaluate(context)

    assert decision.action is DecisionAction.ENABLE_HEATING
    assert decision.sensor_id == context.sensor_id
    assert decision.zone_id == context.zone_id
    assert decision.observed_at == context.observed_at


def test_heating_strategy_disable_heating():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(22),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    strategy = HeatingStrategy()

    decision = strategy.evaluate(context)

    assert decision.action is DecisionAction.DISABLE_HEATING
    assert decision.sensor_id == context.sensor_id
    assert decision.zone_id == context.zone_id
    assert decision.observed_at == context.observed_at

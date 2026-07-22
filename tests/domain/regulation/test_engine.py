from datetime import UTC, datetime

from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.engine import RegulationEngine
from controlel.domain.regulation.heating import HeatingStrategy
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_engine_enables_heating_when_temperature_is_low():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(21),
        target_temperature=Temperature(22),
    )

    engine = RegulationEngine(
        strategy=HeatingStrategy(),
    )

    decision = engine.evaluate(context)

    assert decision.action is DecisionAction.ENABLE_HEATING


def test_engine_respects_hysteresis():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(21.8),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    engine = RegulationEngine(
        strategy=HeatingStrategy(),
    )

    decision = engine.evaluate(context)

    assert decision.action is DecisionAction.DISABLE_HEATING

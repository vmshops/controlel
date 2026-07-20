from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.engine import RegulationEngine
from controlel.domain.regulation.heating import HeatingStrategy
from controlel.domain.value_objects.temperature import Temperature


def test_engine_uses_provided_strategy():
    context = ControlContext(
        current_temperature=Temperature(20),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    engine = RegulationEngine(
        strategy=HeatingStrategy(),
    )

    decision = engine.evaluate(context)

    assert decision.action == "enable_heating"

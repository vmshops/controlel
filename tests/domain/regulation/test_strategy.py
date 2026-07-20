from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.heating import HeatingStrategy
from controlel.domain.value_objects.temperature import Temperature


def test_heating_strategy_enable_heating():
    context = ControlContext(
        current_temperature=Temperature(20),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    strategy = HeatingStrategy()

    decision = strategy.evaluate(context)

    assert decision.action == "enable_heating"


def test_heating_strategy_disable_heating():
    context = ControlContext(
        current_temperature=Temperature(22),
        target_temperature=Temperature(22),
        hysteresis=Temperature(0.3),
    )

    strategy = HeatingStrategy()

    decision = strategy.evaluate(context)

    assert decision.action == "disable_heating"

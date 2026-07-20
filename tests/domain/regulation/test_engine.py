from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.engine import RegulationEngine
from controlel.domain.value_objects.temperature import Temperature


def test_engine_enables_heating_when_temperature_is_low():
    context = ControlContext(
        current_temperature=Temperature(21),
        target_temperature=Temperature(22),
    )

    decision = RegulationEngine.evaluate(context)

    assert decision.action == "enable_heating"

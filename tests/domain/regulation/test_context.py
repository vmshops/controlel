from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


def test_control_context_creation():
    context = ControlContext(
        current_temperature=Temperature(21.2),
        target_temperature=Temperature(22),
    )

    assert context.current_temperature.value == 21.2
    assert context.target_temperature.value == 22

from controlel.application.services.regulation_service import RegulationService
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


def test_regulation_service_returns_decision():
    context = ControlContext(
        current_temperature=Temperature(20),
        target_temperature=Temperature(22),
    )

    service = RegulationService()

    decision = service.evaluate(context)

    assert decision.action == "enable_heating"

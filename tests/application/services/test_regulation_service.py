from datetime import UTC, datetime

from controlel.application.services.regulation_service import RegulationService
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_regulation_service_returns_decision():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(20),
        target_temperature=Temperature(22),
    )

    service = RegulationService()

    decision = service.evaluate(context)

    assert decision.action is DecisionAction.ENABLE_HEATING

from controlel.application.handlers.temperature_event_handler import TemperatureEventHandler
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


def test_temperature_event_handler_creates_result():
    measurement = Measurement(
        value=Temperature(19),
    )

    event = TemperatureMeasuredEvent(
        measurement=measurement,
    )

    handler = TemperatureEventHandler()

    result = handler.handle(event)

    assert result is not None

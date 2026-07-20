from controlel.domain.events.event import Event
from controlel.domain.measurements.measurement import Measurement


class TemperatureMeasuredEvent(Event):
    """
    Event raised when a temperature measurement is received.
    """

    event_type: str = "temperature_measured"

    measurement: Measurement

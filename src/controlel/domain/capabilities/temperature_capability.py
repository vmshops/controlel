from controlel.domain.capabilities.capability import Capability


class TemperatureCapability(Capability):
    """
    Capability for measuring temperature.
    """

    name: str = "temperature"

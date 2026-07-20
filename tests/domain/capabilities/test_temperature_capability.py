from controlel.domain.capabilities.temperature_capability import TemperatureCapability


def test_temperature_capability_creation():
    capability = TemperatureCapability()

    assert capability.name == "temperature"

from pytest import raises

from controlel.domain.value_objects.temperature import Temperature


def test_temperature_creation():
    temperature = Temperature(22.5)

    assert temperature.value == 22.5


def test_temperature_negative_value():
    temperature = Temperature(-10)

    assert temperature.value == -10


def test_temperature_is_immutable():
    temperature = Temperature(22)

    with raises(Exception):
        temperature.value = 25

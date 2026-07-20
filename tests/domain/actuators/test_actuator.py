from controlel.domain.actuators.actuator import Actuator


def test_actuator_creation():
    actuator = Actuator(
        name="Heating relay",
    )

    assert actuator.name == "Heating relay"


def test_actuator_enabled_by_default():
    actuator = Actuator(
        name="Heating relay",
    )

    assert actuator.enabled is True

from controlel.domain.capabilities.capability import Capability


def test_capability_creation():
    capability = Capability(
        name="temperature",
    )

    assert capability.name == "temperature"


def test_capability_is_immutable():
    capability = Capability(
        name="temperature",
    )

    try:
        capability.name = "humidity"
        assert False
    except Exception:
        assert True

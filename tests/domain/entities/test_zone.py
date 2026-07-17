from controlel.domain.entities.zone import Zone


def test_zone_creation():
    zone = Zone(
        name="Living Room",
        target_temperature=22.0,
    )

    assert zone.name == "Living Room"
    assert zone.target_temperature == 22.0
    assert zone.heating_active is False

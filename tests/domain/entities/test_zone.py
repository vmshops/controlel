from datetime import timedelta

import pytest
from pydantic import ValidationError

from controlel.domain.entities.zone import Zone
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_zone_has_typed_identity_and_target_configuration_only():
    zone = Zone(
        zone_id=ZoneId(value="living_room"),
        primary_sensor_id=SensorId(value="living_room_temperature"),
        primary_measurement_max_age=timedelta(minutes=5),
        name="Living Room",
        target_temperature=Temperature(22),
    )

    assert zone.zone_id == ZoneId(value="living_room")
    assert zone.primary_sensor_id == SensorId(value="living_room_temperature")
    assert zone.primary_measurement_max_age == timedelta(minutes=5)
    assert zone.name == "Living Room"
    assert zone.target_temperature == Temperature(22)
    assert not hasattr(zone, "current_temperature")
    assert not hasattr(zone, "heating_active")


def test_zone_id_is_required():
    with pytest.raises(ValidationError, match="zone_id"):
        Zone(
            primary_sensor_id=SensorId(value="living_room_temperature"),
            primary_measurement_max_age=timedelta(minutes=5),
            name="Living Room",
            target_temperature=Temperature(22),
        )


def test_primary_sensor_id_is_required():
    with pytest.raises(ValidationError, match="primary_sensor_id"):
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_measurement_max_age=timedelta(minutes=5),
            name="Living Room",
            target_temperature=Temperature(22),
        )


def test_typed_target_temperature_is_required():
    with pytest.raises(ValidationError, match="target_temperature"):
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_sensor_id=SensorId(value="living_room_temperature"),
            primary_measurement_max_age=timedelta(minutes=5),
            name="Living Room",
        )


def test_primary_measurement_max_age_is_required_with_no_implicit_default():
    with pytest.raises(ValidationError, match="primary_measurement_max_age"):
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_sensor_id=SensorId(value="living_room_temperature"),
            name="Living Room",
            target_temperature=Temperature(22),
        )


@pytest.mark.parametrize("maximum_age", [timedelta(0), timedelta(microseconds=-1)])
def test_primary_measurement_max_age_must_be_strictly_positive(maximum_age):
    with pytest.raises(
        ValidationError,
        match="primary_measurement_max_age must be greater than zero",
    ):
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_sensor_id=SensorId(value="living_room_temperature"),
            primary_measurement_max_age=maximum_age,
            name="Living Room",
            target_temperature=Temperature(22),
        )


def test_primary_measurement_max_age_requires_timedelta():
    with pytest.raises(
        ValidationError,
        match="primary_measurement_max_age must be a timedelta",
    ):
        Zone(
            zone_id=ZoneId(value="living_room"),
            primary_sensor_id=SensorId(value="living_room_temperature"),
            primary_measurement_max_age=300,
            name="Living Room",
            target_temperature=Temperature(22),
        )

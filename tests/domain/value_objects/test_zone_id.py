import pytest
from pydantic import ValidationError

from controlel.domain.value_objects.zone_id import ZoneId


def test_zone_id_compares_by_value():
    assert ZoneId(value="living_room") == ZoneId(value="living_room")
    assert ZoneId(value="living_room") != ZoneId(value="bedroom")


def test_zone_id_is_immutable():
    zone_id = ZoneId(value="living_room")

    with pytest.raises(ValidationError):
        zone_id.value = "bedroom"

from controlel.domain.entities.zone import Zone
from controlel.domain.value_objects.zone_id import ZoneId


class DuplicateZoneIdError(ValueError):
    """Raised when a zone with the same domain identifier is registered twice."""

    def __init__(self, zone_id: ZoneId):
        super().__init__(f"Zone with id '{zone_id.value}' is already registered")


class ZoneRepository:
    def __init__(self):
        self._items: dict[ZoneId, Zone] = {}

    def add(self, zone: Zone) -> None:
        if zone.zone_id in self._items:
            raise DuplicateZoneIdError(zone.zone_id)

        self._items[zone.zone_id] = zone

    def get(self, zone_id: ZoneId) -> Zone:
        return self._items[zone_id]

    def list_all(self) -> list[Zone]:
        return list(self._items.values())

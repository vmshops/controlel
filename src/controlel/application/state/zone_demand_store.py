from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.value_objects.zone_id import ZoneId


class ZoneDemandStore:
    """Stores the latest requested heating demand for each zone."""

    def __init__(self) -> None:
        self._demands: dict[ZoneId, ZoneDemand] = {}

    def record(self, demand: ZoneDemand) -> None:
        self._demands[demand.zone_id] = demand

    def get(self, zone_id: ZoneId) -> ZoneDemand | None:
        return self._demands.get(zone_id)

    def list_current(self) -> list[ZoneDemand]:
        return list(self._demands.values())

    def clear(self) -> None:
        self._demands.clear()

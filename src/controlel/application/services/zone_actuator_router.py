from collections.abc import Mapping
from types import MappingProxyType

from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.value_objects.zone_id import ZoneId


class ActuatorRouteNotFoundError(LookupError):
    """Raised when no actuator port is configured for a zone."""

    def __init__(self, zone_id: ZoneId):
        self.zone_id = zone_id
        super().__init__(f"No actuator route is configured for zone '{zone_id.value}'")


class ZoneActuatorRouter:
    """Resolves runtime actuator ports by logical zone identity."""

    def __init__(
        self,
        routes: Mapping[ZoneId, ActuatorPort],
    ) -> None:
        self._routes = MappingProxyType(dict(routes))

    def resolve(
        self,
        zone_id: ZoneId,
    ) -> ActuatorPort:
        try:
            return self._routes[zone_id]
        except KeyError:
            raise ActuatorRouteNotFoundError(zone_id) from None

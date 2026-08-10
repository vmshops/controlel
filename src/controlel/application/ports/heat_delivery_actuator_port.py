"""Application port for a zone heat-delivery actuator."""

from typing import Protocol

from controlel.domain.heat_delivery import HeatDeliveryCommand


class HeatDeliveryActuatorPort(Protocol):
    def execute(self, command: HeatDeliveryCommand) -> None:
        """Request one actuator command or raise when dispatch fails."""

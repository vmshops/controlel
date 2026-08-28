"""Host ports for Water Safety outputs, state persistence, and evidence."""

from typing import Protocol

from controlel.application.water_safety.model import (
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterSafetyEvent,
)
from controlel.domain.water_safety import WaterSafetySnapshot


class WaterSafetyOutputPort(Protocol):
    def request(self, command: WaterOutputCommand) -> WaterOutputCommandResult:
        """Request an output operation and truthfully report adapter acceptance/failure."""


class WaterSafetyStatePort(Protocol):
    def save(self, snapshot: WaterSafetySnapshot) -> None:
        """Persist the latest restart state."""


class WaterSafetyEvidencePort(Protocol):
    def record(self, event: WaterSafetyEvent) -> None:
        """Append one diagnostics/history event."""

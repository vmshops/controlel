"""Immutable source evidence without inferred physical burner state."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SourceOwnership(StrEnum):
    """Authority for reconciling reported source-controller divergence."""

    CONTROLEL_OWNED = "controlel_owned"
    EXTERNAL = "external"


class SourceCapability(StrEnum):
    """Independent command capabilities advertised by a source adapter."""

    ENABLE_DISABLE = "enable_disable"
    WATER_TARGET = "water_target"


@dataclass(frozen=True)
class SourceCapabilities:
    """Immutable explicit set of supported source command capabilities."""

    values: frozenset[SourceCapability] = field(default_factory=lambda: frozenset({SourceCapability.ENABLE_DISABLE}))

    def __post_init__(self) -> None:
        if not isinstance(self.values, frozenset) or any(
            not isinstance(value, SourceCapability) for value in self.values
        ):
            raise TypeError("values must be a frozenset of SourceCapability values")
        if SourceCapability.ENABLE_DISABLE not in self.values:
            raise ValueError("source capabilities must include ENABLE_DISABLE")

    def supports(self, capability: SourceCapability) -> bool:
        """Return whether the source explicitly advertises one capability."""

        if not isinstance(capability, SourceCapability):
            raise TypeError("capability must be a SourceCapability")
        return capability in self.values


class ReportedSourceState(StrEnum):
    """Reported controller state; never physical burner confirmation."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class TransitionHistoryKnowledge(StrEnum):
    """Whether reported transition timing is supported by explicit evidence."""

    KNOWN = "known"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReportedSourceEvidence:
    """One bounded reported-state observation from a source controller."""

    state: ReportedSourceState
    observed_at: datetime
    transition_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ReportedSourceState):
            raise TypeError("state must be a ReportedSourceState")
        _aware(self.observed_at, "observed_at")
        if self.transition_at is not None:
            _aware(self.transition_at, "transition_at")
            if self.transition_at > self.observed_at:
                raise ValueError("transition_at must not be later than observed_at")

    @property
    def transition_history(self) -> TransitionHistoryKnowledge:
        """Describe timestamp knowledge without manufacturing transition age."""

        return (
            TransitionHistoryKnowledge.KNOWN if self.transition_at is not None else TransitionHistoryKnowledge.UNKNOWN
        )


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

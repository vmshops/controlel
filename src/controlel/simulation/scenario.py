"""Versioned human-authored scenarios and canonical replay representation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import isfinite
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

SCENARIO_SCHEMA_VERSION = 1
CANONICALIZATION_POLICY_VERSION = 1
_DURATION_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s|m|h|d)")
_DURATION_FACTORS = {
    "ms": Decimal("0.001"),
    "s": Decimal(1),
    "m": Decimal(60),
    "h": Decimal(3600),
    "d": Decimal(86400),
}


class FrozenJsonMapping(Mapping[str, object]):
    """Deeply immutable JSON mapping used by validated simulation evidence."""

    __slots__ = ("__values",)

    def __init__(self, values: Mapping[str, object]) -> None:
        self.__values = dict(values)

    def __getitem__(self, key: str) -> object:
        return self.__values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__values)

    def __len__(self) -> int:
        return len(self.__values)

    def __repr__(self) -> str:
        return repr(self.__values)


type ImmutableJsonMapping = Annotated[
    Mapping[str, object],
    PlainSerializer(lambda value: normalize_json(value), return_type=dict),
]


class TimelinePhase(StrEnum):
    BEFORE_DEADLINES = "before_deadlines"
    AFTER_DEADLINES = "after_deadlines"


class ScenarioEvent(BaseModel):
    """One module event supplied to an ordinary public runtime boundary."""

    type: str = Field(min_length=1)
    subject: str | None = None
    payload: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("type")
    @classmethod
    def type_must_be_namespaced(cls, value: str) -> str:
        if "." not in value or not _is_identifier(value, allow_dot=True):
            raise ValueError("event type must be a namespaced ASCII identifier")
        return value

    @field_validator("subject")
    @classmethod
    def subject_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("event subject must not be blank")
        return value

    @field_validator("payload", mode="after")
    @classmethod
    def payload_must_be_json_data(cls, value: object) -> FrozenJsonMapping:
        return _normalized_mapping(value, "event payload")


class ScenarioTimelineItem(BaseModel):
    """One resolved delivery in deterministic document order."""

    delivery_at: datetime
    sequence: int = Field(ge=0)
    phase: TimelinePhase = TimelinePhase.BEFORE_DEADLINES
    event: ScenarioEvent

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("delivery_at")
    @classmethod
    def delivery_at_must_be_aware(cls, value: datetime) -> datetime:
        return _aware(value, "delivery_at")


class ScenarioExpectation(BaseModel):
    """Small v0.1 assertion vocabulary over observable trace records."""

    type: str
    event_code: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def validate_supported_shape(self) -> ScenarioExpectation:
        if self.type in {"operational_event.exists", "operational_event.does_not_exist"}:
            if self.event_code is None or not self.event_code:
                raise ValueError(f"{self.type} requires event_code")
        elif self.type == "run.no_unhandled_error":
            if self.event_code is not None:
                raise ValueError("run.no_unhandled_error does not accept event_code")
        else:
            raise ValueError(f"unsupported expectation type: {self.type}")
        return self


class Scenario(BaseModel):
    """Immutable, single-module Scenario v1 contract."""

    schema_version: int = SCENARIO_SCHEMA_VERSION
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    tags: tuple[str, ...] = ()
    module: str
    module_contract_version: int = Field(ge=1)
    start_at: datetime
    configuration: ImmutableJsonMapping
    initial_state: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    timeline: tuple[ScenarioTimelineItem, ...]
    expectations: tuple[ScenarioExpectation, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: int) -> int:
        if value != SCENARIO_SCHEMA_VERSION:
            raise ValueError(f"unsupported scenario schema version: {value}")
        return value

    @field_validator("scenario_id", "module")
    @classmethod
    def identifiers_must_be_stable(cls, value: str) -> str:
        if not _is_identifier(value):
            raise ValueError("scenario and module identifiers must use ASCII letters, digits, '_' or '-'")
        return value

    @field_validator("start_at")
    @classmethod
    def start_at_must_be_aware(cls, value: datetime) -> datetime:
        return _aware(value, "start_at")

    @field_validator("configuration", "initial_state", mode="after")
    @classmethod
    def mappings_must_be_json_data(cls, value: object, info: object) -> FrozenJsonMapping:
        field_name = getattr(info, "field_name", "scenario mapping")
        return _normalized_mapping(value, str(field_name))

    @model_validator(mode="after")
    def validate_timeline_and_configuration(self) -> Scenario:
        if "fixture" in self.configuration:
            raise ValueError("configuration fixtures are not supported in v0.1; provide resolved configuration")
        sequences = tuple(item.sequence for item in self.timeline)
        if sequences != tuple(range(len(self.timeline))):
            raise ValueError("timeline sequence must match document order starting at zero")
        if any(item.delivery_at < self.start_at for item in self.timeline):
            raise ValueError("timeline delivery cannot precede start_at")
        return self

    @classmethod
    def from_yaml(cls, source: str) -> Scenario:
        """Parse human-readable YAML while rejecting duplicate mapping keys."""

        from controlel.simulation.yaml_authoring import parse_yaml_mapping

        loaded = parse_yaml_mapping(source)
        return cls.from_mapping(loaded)

    @classmethod
    def from_json(cls, source: str) -> Scenario:
        """Parse JSON using the same authoring contract as YAML."""

        return cls.from_mapping(json.loads(source))

    @classmethod
    def from_mapping(cls, source: object) -> Scenario:
        """Resolve authoring times and document-order sequences into Scenario v1."""

        if not isinstance(source, Mapping):
            raise TypeError("scenario document must be a mapping")
        data = dict(source)
        start_at = _parse_datetime(data.get("start_at"), "start_at")
        raw_timeline = data.get("timeline")
        if not isinstance(raw_timeline, Sequence) or isinstance(raw_timeline, str | bytes):
            raise TypeError("timeline must be a sequence")
        timeline: list[dict[str, object]] = []
        for sequence, raw_item in enumerate(raw_timeline):
            if not isinstance(raw_item, Mapping):
                raise TypeError("timeline items must be mappings")
            item = dict(raw_item)
            allowed = {"at", "sequence", "phase", "event"}
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(f"unknown timeline fields: {', '.join(sorted(unknown))}")
            declared_sequence = item.get("sequence", sequence)
            if declared_sequence != sequence:
                raise ValueError("timeline sequence must match document order")
            timeline.append(
                {
                    "delivery_at": _resolve_delivery_at(item.get("at"), start_at),
                    "sequence": sequence,
                    "phase": item.get("phase", TimelinePhase.BEFORE_DEADLINES),
                    "event": item.get("event"),
                }
            )
        data["start_at"] = start_at
        data["timeline"] = timeline
        return cls.model_validate(data)

    def canonical_data(self) -> FrozenJsonMapping:
        """Return the normalized JSON-native replay authority."""

        frozen = freeze_json(
            {
                "schema_version": self.schema_version,
                "scenario_id": self.scenario_id,
                "name": self.name,
                "description": self.description,
                "tags": list(self.tags),
                "module": self.module,
                "module_contract_version": self.module_contract_version,
                "start_at": _canonical_datetime(self.start_at),
                "configuration": normalize_json(self.configuration),
                "initial_state": normalize_json(self.initial_state),
                "timeline": [
                    {
                        "at": _canonical_datetime(item.delivery_at),
                        "sequence": item.sequence,
                        "phase": item.phase.value,
                        "event": {
                            "type": item.event.type,
                            "subject": item.event.subject,
                            "payload": normalize_json(item.event.payload),
                        },
                    }
                    for item in self.timeline
                ],
                "expectations": [expectation.model_dump(mode="json") for expectation in self.expectations],
            }
        )
        if not isinstance(frozen, FrozenJsonMapping):
            raise TypeError("canonical scenario must be a mapping")
        return frozen

    def canonical_json(self) -> str:
        return canonical_json(self.canonical_data())

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    """Serialize normalized JSON deterministically and reject non-finite values."""

    return json.dumps(
        normalize_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def normalize_json(value: object) -> object:
    """Normalize supported data into deterministic JSON-native primitives."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON numeric values must be finite")
        return value
    if isinstance(value, datetime):
        return _canonical_datetime(_aware(value, "datetime value"))
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON mapping keys must be strings")
        for key in sorted(value):
            normalized[key] = normalize_json(value[key])
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [normalize_json(item) for item in value]
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def freeze_json(value: object) -> object:
    """Copy normalized JSON data into recursively immutable containers."""

    normalized = normalize_json(value)
    if isinstance(normalized, dict):
        return FrozenJsonMapping({key: freeze_json(item) for key, item in normalized.items()})
    if isinstance(normalized, list):
        return tuple(freeze_json(item) for item in normalized)
    return normalized


def parse_duration(value: object, label: str) -> timedelta:
    """Parse a small exact human duration vocabulary used by Scenario v1."""

    if isinstance(value, timedelta):
        duration = value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        duration = timedelta(seconds=float(value))
    elif isinstance(value, str):
        position = 0
        seconds = Decimal(0)
        for match in _DURATION_PART.finditer(value):
            if match.start() != position:
                raise ValueError(f"{label} must be a duration such as '10m' or '1h30m'")
            try:
                seconds += Decimal(match.group("value")) * _DURATION_FACTORS[match.group("unit")]
            except InvalidOperation as error:
                raise ValueError(f"{label} contains an invalid duration") from error
            position = match.end()
        if position != len(value) or not value:
            raise ValueError(f"{label} must be a duration such as '10m' or '1h30m'")
        microseconds = seconds * Decimal(1_000_000)
        if microseconds != microseconds.to_integral_value():
            raise ValueError(f"{label} must resolve to whole microseconds")
        duration = timedelta(microseconds=int(microseconds))
    else:
        raise TypeError(f"{label} must be a duration")
    if duration < timedelta(0):
        raise ValueError(f"{label} must not be negative")
    return duration


def _resolve_delivery_at(value: object, start_at: datetime) -> datetime:
    if isinstance(value, datetime):
        return _aware(value, "timeline at")
    if isinstance(value, str) and ("T" in value or value.endswith("Z")):
        return _parse_datetime(value, "timeline at")
    return start_at + parse_duration(value, "timeline at")


def _parse_datetime(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        return _aware(value, label)
    if not isinstance(value, str):
        raise TypeError(f"{label} must be an aware datetime")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO 8601 datetime") from error
    return _aware(parsed, label)


def _canonical_datetime(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    text = utc_value.isoformat(timespec="microseconds")
    if utc_value.microsecond == 0:
        text = utc_value.isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")


def _normalized_mapping(value: object, label: str) -> FrozenJsonMapping:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):
        raise TypeError(f"{label} must be a mapping")
    frozen = freeze_json(normalized)
    if not isinstance(frozen, FrozenJsonMapping):
        raise TypeError(f"{label} must be a mapping")
    return frozen


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _is_identifier(value: str, *, allow_dot: bool = False) -> bool:
    allowed = {"_", "-"}
    if allow_dot:
        allowed.add(".")
    return bool(value) and value.isascii() and all(character.isalnum() or character in allowed for character in value)

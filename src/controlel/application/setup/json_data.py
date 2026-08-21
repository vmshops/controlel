"""Deterministic, deeply immutable JSON values for setup artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated

from pydantic import PlainSerializer


class FrozenJsonMapping(Mapping[str, object]):
    """A copied, recursively immutable JSON mapping."""

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


def canonical_json(value: object) -> str:
    """Serialize supported values using Setup canonicalization policy v1."""

    return json.dumps(
        normalize_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def normalize_json(value: object) -> object:
    """Normalize supported input to deterministic JSON-native values."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON numeric values must be finite")
        return value
    if isinstance(value, datetime):
        return canonical_datetime(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON mapping keys must be strings")
        return {key: normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [normalize_json(item) for item in value]
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def freeze_json(value: object) -> object:
    """Copy supported JSON values into recursively immutable containers."""

    normalized = normalize_json(value)
    if isinstance(normalized, dict):
        return FrozenJsonMapping({key: freeze_json(item) for key, item in normalized.items()})
    if isinstance(normalized, list):
        return tuple(freeze_json(item) for item in normalized)
    return normalized


def immutable_json_mapping(value: object, label: str) -> FrozenJsonMapping:
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenJsonMapping):
        raise TypeError(f"{label} must be a mapping")
    return frozen


def canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def aware_datetime(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value

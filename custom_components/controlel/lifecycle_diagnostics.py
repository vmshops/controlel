"""Small entry-scoped record of setup and activation failures for HA diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .const import DOMAIN

_LIFECYCLE_FAILURES_KEY = f"{DOMAIN}_lifecycle_failures"
_MAX_CHAIN_DEPTH = 4
_MAX_MESSAGE_LENGTH = 500


def record_lifecycle_failure(hass: Any, entry: Any, *, phase: str, error: Exception) -> None:
    """Retain bounded failure evidence without persisting a traceback or secrets."""

    failures = hass.data.setdefault(_LIFECYCLE_FAILURES_KEY, {})
    failures.setdefault(entry.entry_id, {})[phase] = {
        "occurred_at": datetime.now(UTC).isoformat(),
        "config_entry_state": _state_value(getattr(entry, "state", None)),
        "config_entry_reason": _bounded_message(getattr(entry, "reason", None)),
        "exception_chain": _exception_chain(error),
    }


def lifecycle_failures_for_entry(hass: Any, entry_id: str) -> dict[str, object | None]:
    """Return the last bounded setup and activation failure evidence."""

    entry_failures = hass.data.get(_LIFECYCLE_FAILURES_KEY, {}).get(entry_id, {})
    return {
        "setup": entry_failures.get("setup"),
        "activation": entry_failures.get("activation"),
    }


def _exception_chain(error: BaseException) -> list[dict[str, str | None]]:
    chain: list[dict[str, str | None]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN_DEPTH:
        chain.append(
            {
                "exception_type": type(current).__name__,
                "message": _bounded_message(current),
            }
        )
        seen.add(id(current))
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return chain


def _state_value(state: object) -> str | None:
    value = getattr(state, "value", state)
    return _bounded_message(value)


def _bounded_message(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized:
        return None
    return normalized[:_MAX_MESSAGE_LENGTH]

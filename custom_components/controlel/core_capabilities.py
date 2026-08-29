"""Detect optional Controlel core surfaces available at runtime."""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec


@lru_cache(maxsize=1)
def water_safety_core_available() -> bool:
    """Return True when the installed core exposes Water Safety application APIs."""

    return find_spec("controlel.application.water_safety") is not None

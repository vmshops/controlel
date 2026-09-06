"""Home Assistant framework Core composition contract."""

from __future__ import annotations

import os

CHECKED_OUT_WHEEL_COMPOSITION = "checked-out-wheel"
PUBLIC_COMPOSITION = "public"
FRAMEWORK_COMPOSITION_ENV = "CONTROLEL_FRAMEWORK_COMPOSITION"


def resolve_framework_composition(raw: str | None = None) -> str:
    """Return the active framework Core composition mode."""
    value = raw if raw is not None else os.environ.get(FRAMEWORK_COMPOSITION_ENV)
    if value is None:
        value = CHECKED_OUT_WHEEL_COMPOSITION
    if value not in {CHECKED_OUT_WHEEL_COMPOSITION, PUBLIC_COMPOSITION}:
        raise ValueError(
            f"{FRAMEWORK_COMPOSITION_ENV} must be "
            f"{CHECKED_OUT_WHEEL_COMPOSITION!r} or {PUBLIC_COMPOSITION!r}, got {value!r}"
        )
    return value


def resolve_installed_framework_core_version(
    *,
    composition: str,
    installed_version: str,
    manifest_public_version: str,
) -> str:
    """Return the runtime Core version expected by framework assertions.

    checked-out-wheel composition installs the repository Core candidate and may
    therefore differ from the HA release manifest's public pin. Public composition
    requires the installed package to match that public pin exactly.
    """
    if composition == CHECKED_OUT_WHEEL_COMPOSITION:
        return installed_version
    if composition == PUBLIC_COMPOSITION:
        if installed_version != manifest_public_version:
            raise AssertionError(
                "public framework composition requires installed Core "
                f"{installed_version!r} to equal manifest public Core {manifest_public_version!r}"
            )
        return installed_version
    raise ValueError(f"unsupported framework composition: {composition!r}")

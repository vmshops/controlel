"""Framework Core composition keeps manifest pin and installed Core separate."""

from __future__ import annotations

import pytest

from tests.integrations.home_assistant.framework.framework_composition import (
    CHECKED_OUT_WHEEL_COMPOSITION,
    PUBLIC_COMPOSITION,
    resolve_framework_composition,
    resolve_installed_framework_core_version,
)


def test_checked_out_wheel_uses_installed_core_while_manifest_stays_public() -> None:
    assert resolve_framework_composition(CHECKED_OUT_WHEEL_COMPOSITION) == CHECKED_OUT_WHEEL_COMPOSITION
    assert (
        resolve_installed_framework_core_version(
            composition=CHECKED_OUT_WHEEL_COMPOSITION,
            installed_version="0.18.0",
            manifest_public_version="0.17.0",
        )
        == "0.18.0"
    )


def test_public_composition_requires_installed_core_to_match_manifest_pin() -> None:
    assert (
        resolve_installed_framework_core_version(
            composition=PUBLIC_COMPOSITION,
            installed_version="0.17.0",
            manifest_public_version="0.17.0",
        )
        == "0.17.0"
    )
    with pytest.raises(AssertionError, match="equal manifest public Core"):
        resolve_installed_framework_core_version(
            composition=PUBLIC_COMPOSITION,
            installed_version="0.18.0",
            manifest_public_version="0.17.0",
        )


def test_resolve_framework_composition_defaults_to_checked_out_wheel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONTROLEL_FRAMEWORK_COMPOSITION", raising=False)
    assert resolve_framework_composition() == CHECKED_OUT_WHEEL_COMPOSITION

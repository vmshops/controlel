"""Development composition keeps released and unreleased package boundaries explicit."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.packaging.build_development_composition import (
    DevelopmentCompositionError,
    build_development_composition,
    validate_development_composition,
)

ROOT = Path(__file__).parents[2]
CORE_VERSION = "0.16.0"


def _core_wheel(path: Path, *, version: str = CORE_VERSION) -> Path:
    wheel = path / f"controlel-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"controlel-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: controlel\nVersion: {version}\n",
        )
        archive.writestr("controlel/__init__.py", "")
    return wheel


def test_development_bundle_contains_matching_frontend_and_core_without_mutating_release_manifest(
    tmp_path: Path,
) -> None:
    release_manifest_path = ROOT / "custom_components" / "controlel" / "manifest.json"
    release_manifest_before = release_manifest_path.read_bytes()
    wheel = _core_wheel(tmp_path)
    output = tmp_path / "controlel-dev-0.16.0.zip"

    composition = build_development_composition(
        output,
        source_ref="test-source-ref",
        core_wheel=wheel,
    )

    assert release_manifest_path.read_bytes() == release_manifest_before
    assert composition["publishable"] is False
    assert composition["core"]["version"] == CORE_VERSION
    assert composition["integration"]["release_source_requirement"] == "controlel==0.15.0"
    assert composition["integration"]["development_requirement"] == "controlel==0.16.0"
    validated = validate_development_composition(output, expected_core_version=CORE_VERSION)
    assert validated == composition

    with zipfile.ZipFile(output) as bundle:
        assert bundle.namelist() == [
            "INSTALL.md",
            "composition.json",
            f"core/{wheel.name}",
            "integration/controlel.zip",
        ]
        with zipfile.ZipFile(io.BytesIO(bundle.read("integration/controlel.zip"))) as integration:
            manifest = json.loads(integration.read("manifest.json"))
            assert manifest["requirements"] == ["controlel==0.16.0"]
            assert manifest["version"] == "0.13.0"
            assert not any(name.startswith("controlel/") for name in integration.namelist())


def test_development_bundle_is_deterministic_for_the_same_inputs(tmp_path: Path) -> None:
    wheel = _core_wheel(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    build_development_composition(first, source_ref="same-ref", core_wheel=wheel)
    build_development_composition(second, source_ref="same-ref", core_wheel=wheel)

    assert first.read_bytes() == second.read_bytes()


def test_development_bundle_rejects_a_relabelled_or_mismatched_core(tmp_path: Path) -> None:
    wrong_wheel = _core_wheel(tmp_path, version="0.14.0")

    with pytest.raises(DevelopmentCompositionError, match="expected controlel 0.16.0"):
        build_development_composition(
            tmp_path / "wrong.zip",
            source_ref="test-source-ref",
            core_wheel=wrong_wheel,
        )

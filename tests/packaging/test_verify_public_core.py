"""Composition modes for scripts/ci/verify_public_core.py."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci.verify_public_core import (
    CORE_VERSION,
    _verify_development_wheel_install,
    composition_expectations,
)

ROOT = Path(__file__).parents[2]


def test_development_wheel_mode_allows_core_candidate_ahead_of_public_manifest_pin() -> None:
    installed, manifest_requirement = composition_expectations(
        development_wheel=True,
        project_version="0.18.0",
        public_core_version="0.17.0",
    )

    assert installed == "0.18.0"
    assert manifest_requirement == "controlel==0.17.0"
    assert installed != manifest_requirement.removeprefix("controlel==")


def test_public_mode_requires_installed_core_to_match_manifest_pin() -> None:
    installed, manifest_requirement = composition_expectations(
        development_wheel=False,
        project_version="0.18.0",
        public_core_version=CORE_VERSION,
    )

    assert installed == "0.18.0"
    assert manifest_requirement == "controlel==0.18.0"
    assert installed == CORE_VERSION


def test_repository_shipped_core_uses_development_expectations() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8"))
    installed, manifest_requirement = composition_expectations(
        development_wheel=True,
        project_version="0.18.0",
    )

    assert 'version = "0.18.0"' in project
    assert manifest["requirements"] == [manifest_requirement] == ["controlel==0.18.0"]
    assert installed == "0.18.0"


def test_wrong_installed_development_wheel_version_is_rejected(tmp_path: Path) -> None:
    wheel_path = tmp_path / "controlel-0.17.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(
            "controlel-0.17.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: controlel\nVersion: 0.17.0\n",
        )
    distribution = SimpleNamespace(read_text=lambda name: None)

    with pytest.raises(AssertionError):
        _verify_development_wheel_install(
            distribution=distribution,
            wheel_path=wheel_path,
            expected_version="0.18.0",
        )

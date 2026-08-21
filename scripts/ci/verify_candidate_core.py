"""Verify the exact local Core candidate required by the HA release candidate."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import sys
import tomllib
from pathlib import Path

import controlel
from controlel.application.setup import (
    ActiveReference,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    ValidationReport,
)
from controlel.infrastructure.home_assistant import (
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    HeatingSetupSessionDTO,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """Fail unless installed Core, package metadata, and HA pin are one candidate."""

    manifest_path = REPOSITORY_ROOT / "custom_components" / "controlel" / "manifest.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    version = project["version"]
    expected_requirement = f"controlel=={version}"
    package_path = Path(controlel.__file__).resolve()
    source_root = (REPOSITORY_ROOT / "src").resolve()
    assert version == "0.12.0"
    assert manifest["version"] == version
    assert manifest["requirements"] == [expected_requirement]
    assert controlel.__version__ == version
    assert importlib.metadata.version("controlel") == version
    assert "site-packages" in package_path.as_posix()
    assert not package_path.is_relative_to(source_root)
    assert source_root not in {Path(entry or ".").resolve() for entry in sys.path}

    setup_contracts = (
        ActiveReference,
        CanonicalConfigurationRevision,
        DiscoverySnapshot,
        DraftRevision,
        ValidationReport,
        ConfigEntryActiveReferenceStore,
        HeatingBindingSelectionRequest,
        HeatingSetupHostService,
        HeatingSetupSessionDTO,
        HomeAssistantDiscoveryAdapter,
        HomeAssistantSetupRepository,
    )
    assert all(
        Path(inspect.getmodule(contract).__file__).resolve().is_relative_to(package_path.parent)
        for contract in setup_contracts
    )
    assert SETUP_STORAGE_VERSION == 1
    assert hasattr(HeatingSetupHostService, "canonicalize_heating_draft")
    assert not hasattr(HeatingSetupHostService, "activate")
    assert not hasattr(HeatingSetupHostService, "activate_heating_draft")

    print(f"Verified local controlel {version} candidate at {package_path}; HA pin {expected_requirement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

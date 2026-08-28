"""Verify Home Assistant CI uses the repository Core candidate with a public manifest pin."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import controlel
from controlel.application.configuration import (
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationRevisionV3,
    migrate_heating_v2_revision_to_v3,
)
from controlel.application.setup import (
    ActiveReference,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    ValidationReport,
)
from controlel.frontend_api.v1 import (
    FRONTEND_API_VERSION,
    BuildingEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    SystemEvidenceV1,
    frontend_response_to_dict,
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
CANDIDATE_CORE_VERSION = "0.16.0"
MANIFEST_CORE_VERSION = "0.15.0"
MANIFEST_CORE_REQUIREMENT = f"controlel=={MANIFEST_CORE_VERSION}"


def _contract_module_path(contract: object) -> Path:
    """Return the concrete module path for an imported public contract."""
    module = inspect.getmodule(contract)
    assert module is not None
    module_file = module.__file__
    assert module_file is not None
    return Path(module_file).resolve()


def main() -> int:
    package_path = Path(controlel.__file__).resolve()
    source_root = (REPOSITORY_ROOT / "src").resolve()
    manifest_path = REPOSITORY_ROOT / "custom_components" / "controlel" / "manifest.json"

    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert project["version"] == CANDIDATE_CORE_VERSION
    assert importlib.metadata.version("controlel") == CANDIDATE_CORE_VERSION
    assert controlel.__version__ == CANDIDATE_CORE_VERSION
    assert package_path.is_relative_to(source_root)
    assert manifest["requirements"] == [MANIFEST_CORE_REQUIREMENT]
    assert importlib.metadata.requires("controlel") == [
        "pydantic>=2.0",
        'PyYAML>=6.0; extra == "simulation"',
    ]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert not any("homeassistant" in dependency.casefold() for dependency in project["dependencies"])

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
    assert all(_contract_module_path(contract).is_relative_to(package_path.parent) for contract in setup_contracts)
    assert SETUP_STORAGE_VERSION == 1
    assert hasattr(HeatingSetupHostService, "canonicalize_heating_draft")
    assert not hasattr(HeatingSetupHostService, "activate")
    assert not hasattr(HeatingSetupHostService, "activate_heating_draft")

    canonical_v3_contracts = (
        CanonicalConfigurationDraftV3,
        CanonicalConfigurationRevisionV3,
        migrate_heating_v2_revision_to_v3,
    )
    assert all(
        _contract_module_path(contract).is_relative_to(package_path.parent) for contract in canonical_v3_contracts
    )

    frontend_api_contracts = (
        BuildingEvidenceV1,
        FrontendApiEvidenceV1,
        FrontendApiProviderV1,
        HeatSourceEvidenceV1,
        SystemEvidenceV1,
        frontend_response_to_dict,
    )
    assert all(
        _contract_module_path(contract).is_relative_to(package_path.parent) for contract in frontend_api_contracts
    )
    assert FRONTEND_API_VERSION == 1

    class FrontendEvidenceSource:
        def snapshot(self) -> FrontendApiEvidenceV1:
            return FrontendApiEvidenceV1(
                system=SystemEvidenceV1(status="active", operating_mode="NORMAL"),
                building=BuildingEvidenceV1(
                    heat_source=HeatSourceEvidenceV1(
                        permission="unknown",
                        command_outcome="held",
                        reported_state="UNKNOWN",
                    )
                ),
            )

    class FrontendClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    frontend_provider = FrontendApiProviderV1(source=FrontendEvidenceSource(), clock=FrontendClock())
    frontend_payloads = tuple(
        frontend_response_to_dict(response)
        for response in (
            frontend_provider.overview(),
            frontend_provider.heating(),
            frontend_provider.diagnostics(),
            frontend_provider.setup(),
        )
    )
    frontend_heating = frontend_payloads[1]
    assert all(payload["frontend_api_version"] == 1 for payload in frontend_payloads)
    assert frontend_heating["building"]["heat_source"]["command_outcome"] == "held"
    assert frontend_heating["building"]["heat_source"]["reported_state"] == "UNKNOWN"
    assert frontend_heating["building"]["heat_source"]["physical_state"] == "unknown"

    print(
        f"Verified Home Assistant candidate core {CANDIDATE_CORE_VERSION} from {package_path} "
        f"with manifest requirement {MANIFEST_CORE_REQUIREMENT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

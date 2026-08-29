"""Verify that Home Assistant CI is using the released Controlel core."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import controlel
from controlel.application.configuration import (
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationRevisionV3,
    migrate_heating_v2_revision_to_v3,
)
from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
    WaterSafetySetupPayload,
)
from controlel.application.services.water_safety_projector import WaterSafetyDiagnosticsProjector
from controlel.application.setup import (
    ActiveReference,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    ValidationReport,
)
from controlel.application.state.water_safety_diagnostics import (
    WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION,
    WaterSafetyActionsAvailableV1,
    WaterSafetyDiagnosticsSnapshotV1,
    water_safety_diagnostics_to_dict,
)
from controlel.application.water_safety import (
    WaterOutputOutcome,
    WaterSafetyDiagnostics,
    WaterSafetyEvidencePort,
    WaterSafetyOutputPort,
    WaterSafetyRuntime,
    WaterSafetyStatePort,
)
from controlel.domain.water_safety import (
    MoistureCondition,
    MoistureObservation,
    WaterIncident,
    WaterIncidentStatus,
    WaterSafetyAssessmentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
)
from controlel.frontend_api.v1 import (
    FRONTEND_API_VERSION,
    BuildingEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    SystemEvidenceV1,
    WaterSafetyEvidenceV1,
    WaterSafetyResponseV1,
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
    WaterSafetyBindingSelectionRequest,
    WaterSafetySetupHostService,
    WaterSafetySetupSessionDTO,
    async_snapshot_with_notify_services,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_VERSION = "0.17.0"
CORE_REQUIREMENT = f"controlel=={CORE_VERSION}"
PUBLIC_WHEEL_FILENAME = "controlel-0.17.0-py3-none-any.whl"
PUBLIC_WHEEL_SIZE = 287_747
PUBLIC_WHEEL_SHA256 = "d818dd403b2aada29061662464ce9c0e3d37a5eea5d9059a1e3780cf13ffd3b6"
PUBLIC_SDIST_FILENAME = "controlel-0.17.0.tar.gz"
PUBLIC_SDIST_SIZE = 203_980
PUBLIC_SDIST_SHA256 = "9020487dd1325ff58ec3ac0e9e3541a78840eaaae803b05f9613f28525bd41bd"
PYPI_METADATA_URL = f"https://pypi.org/pypi/controlel/{CORE_VERSION}/json"


def _contract_module_path(contract: object) -> Path:
    """Return the concrete module path for an imported public contract."""
    module = inspect.getmodule(contract)
    assert module is not None
    module_file = module.__file__
    assert module_file is not None
    return Path(module_file).resolve()


def verify_public_artifact_metadata() -> None:
    """Verify the immutable public wheel and sdist identities for this composition."""

    request = Request(PYPI_METADATA_URL, headers={"User-Agent": "controlel-ci-provenance-check"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS PyPI endpoint
        metadata = json.load(response)
    matching_files = [
        file
        for file in metadata["urls"]
        if file["filename"] == PUBLIC_WHEEL_FILENAME and file["packagetype"] == "bdist_wheel"
    ]
    assert len(matching_files) == 1
    wheel = matching_files[0]
    assert wheel["size"] == PUBLIC_WHEEL_SIZE
    assert wheel["digests"]["sha256"] == PUBLIC_WHEEL_SHA256
    matching_sdists = [
        file
        for file in metadata["urls"]
        if file["filename"] == PUBLIC_SDIST_FILENAME and file["packagetype"] == "sdist"
    ]
    assert len(matching_sdists) == 1
    sdist = matching_sdists[0]
    assert sdist["size"] == PUBLIC_SDIST_SIZE
    assert sdist["digests"]["sha256"] == PUBLIC_SDIST_SHA256


def main() -> int:
    package_path = Path(controlel.__file__).resolve()
    distribution = importlib.metadata.distribution("controlel")
    source_root = (REPOSITORY_ROOT / "src").resolve()
    manifest_path = REPOSITORY_ROOT / "custom_components" / "controlel" / "manifest.json"

    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert importlib.metadata.version("controlel") == CORE_VERSION
    assert controlel.__version__ == CORE_VERSION
    assert "site-packages" in package_path.as_posix()
    assert not package_path.is_relative_to(source_root)
    assert source_root not in {Path(entry or ".").resolve() for entry in sys.path}
    assert distribution.read_text("direct_url.json") is None
    assert not any(
        path.is_file()
        and ("editable" in path.name.casefold() or ("controlel" in path.name.casefold() and path.suffix == ".pth"))
        for path in package_path.parents[1].iterdir()
    )
    assert importlib.metadata.requires("controlel") == [
        "pydantic>=2.0",
        'PyYAML>=6.0; extra == "simulation"',
    ]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert not any("homeassistant" in dependency.casefold() for dependency in project["dependencies"])
    assert manifest["requirements"] == [CORE_REQUIREMENT]

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

    water_setup_contracts = (
        WATER_SAFETY_MODULE_KEY,
        WATER_SAFETY_SETUP_SCHEMA_VERSION,
        WaterSafetySetupAdapter,
        WaterSafetySetupPayload,
        WaterSafetyDiagnosticsProjector,
        WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION,
        WaterSafetyActionsAvailableV1,
        WaterSafetyDiagnosticsSnapshotV1,
        water_safety_diagnostics_to_dict,
        WaterOutputOutcome,
        WaterSafetyDiagnostics,
        WaterSafetyEvidencePort,
        WaterSafetyOutputPort,
        WaterSafetyRuntime,
        WaterSafetyStatePort,
        MoistureCondition,
        MoistureObservation,
        WaterIncident,
        WaterIncidentStatus,
        WaterSafetyAssessmentStatus,
        WaterSafetySnapshot,
        WaterSafetyState,
        WaterSafetyBindingSelectionRequest,
        WaterSafetySetupHostService,
        WaterSafetySetupSessionDTO,
        async_snapshot_with_notify_services,
    )
    assert WATER_SAFETY_MODULE_KEY == "water_safety"
    assert WATER_SAFETY_SETUP_SCHEMA_VERSION == 1
    assert WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION == 1
    assert all(
        isinstance(contract, (str, int)) or _contract_module_path(contract).is_relative_to(package_path.parent)
        for contract in water_setup_contracts
    )

    frontend_api_contracts = (
        BuildingEvidenceV1,
        FrontendApiEvidenceV1,
        FrontendApiProviderV1,
        HeatSourceEvidenceV1,
        SystemEvidenceV1,
        WaterSafetyEvidenceV1,
        WaterSafetyResponseV1,
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
                water_safety=WaterSafetyEvidenceV1(
                    state="SENSOR_FAULT",
                    assessment_status="CONFIRMED",
                    sensor_condition="UNKNOWN",
                    area_name="Utility room",
                    zone_name="Utility",
                    active_incident=False,
                    incident_silenced=False,
                    processing_enabled=True,
                    owned_siren_count=0,
                    last_siren_command_outcome=None,
                    actions_available=("disable", "test_notification"),
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
            frontend_provider.water_safety(),
        )
    )
    frontend_heating = frontend_payloads[1]
    frontend_water_safety = frontend_payloads[4]
    assert all(payload["frontend_api_version"] == 1 for payload in frontend_payloads)
    assert frontend_heating["building"]["heat_source"]["command_outcome"] == "held"
    assert frontend_heating["building"]["heat_source"]["reported_state"] == "UNKNOWN"
    assert frontend_heating["building"]["heat_source"]["physical_state"] == "unknown"
    assert frontend_water_safety["state"] == "SENSOR_FAULT"
    assert frontend_water_safety["sensor_condition"] == "UNKNOWN"
    assert frontend_water_safety["actions_available"] == ["disable", "test_notification"]
    verify_public_artifact_metadata()

    print(
        f"Verified public controlel {CORE_VERSION} at {package_path}; "
        f"{PUBLIC_WHEEL_FILENAME} SHA-256 {PUBLIC_WHEEL_SHA256}; "
        f"{PUBLIC_SDIST_FILENAME} SHA-256 {PUBLIC_SDIST_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

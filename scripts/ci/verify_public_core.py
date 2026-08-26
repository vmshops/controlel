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
CORE_VERSION = "0.15.0"
CORE_REQUIREMENT = f"controlel=={CORE_VERSION}"
PUBLIC_WHEEL_FILENAME = "controlel-0.15.0-py3-none-any.whl"
PUBLIC_WHEEL_SIZE = 239_714
PUBLIC_WHEEL_SHA256 = "e76b984aa62c695bc65e694c42c9d8d817fabcad32e7bfedb9d85dda340b420e"
PUBLIC_SDIST_FILENAME = "controlel-0.15.0.tar.gz"
PUBLIC_SDIST_SIZE = 167_206
PUBLIC_SDIST_SHA256 = "88d5e65fb42f639b8e6a838d5d639ff80ff0683689e36991e9121a64a6bc35cf"
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
    verify_public_artifact_metadata()

    print(
        f"Verified public controlel {CORE_VERSION} at {package_path}; "
        f"{PUBLIC_WHEEL_FILENAME} SHA-256 {PUBLIC_WHEEL_SHA256}; "
        f"{PUBLIC_SDIST_FILENAME} SHA-256 {PUBLIC_SDIST_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

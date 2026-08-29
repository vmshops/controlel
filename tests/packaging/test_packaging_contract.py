import importlib.metadata
import json
import tomllib
from pathlib import Path

import pytest
from trove_classifiers import classifiers

import controlel
from scripts.packaging.validate_artifacts import (
    ArtifactValidationError,
    _assert_no_forbidden_content,
)

ROOT = Path(__file__).parents[2]


def load_pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)


def test_build_backend_and_src_package_discovery_are_explicit() -> None:
    pyproject = load_pyproject()

    assert pyproject["build-system"] == {
        "requires": ["setuptools>=77.0.3"],
        "build-backend": "setuptools.build_meta",
    }
    assert pyproject["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["src"],
        "include": ["controlel*"],
    }
    assert pyproject["tool"]["setuptools"]["include-package-data"] is False


def test_project_metadata_and_runtime_dependencies_match_release_contract() -> None:
    project = load_pyproject()["project"]

    assert project["name"] == "controlel"
    assert project["version"] == "0.17.0"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.13"
    assert project["license"] == "MIT"
    assert project["authors"] == [{"name": "vmshops"}]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert project["optional-dependencies"] == {"simulation": ["PyYAML>=6.0"]}
    assert project["classifiers"] == [
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ]
    assert project["urls"] == {
        "Source": "https://github.com/vmshops/controlel",
        "Issues": "https://github.com/vmshops/controlel/issues",
        "Documentation": "https://github.com/vmshops/controlel/tree/main/docs",
    }
    forbidden = {
        "homeassistant",
        "pytest",
        "ruff",
        "pre-commit",
        "pip-tools",
        "build",
        "twine",
        "pytest-homeassistant-custom-component",
    }
    assert not any(name in dependency.casefold() for name in forbidden for dependency in project["dependencies"])


def test_all_project_classifiers_are_official_trove_classifiers() -> None:
    declared_classifiers = load_pyproject()["project"]["classifiers"]

    assert len(declared_classifiers) == len(set(declared_classifiers))
    assert set(declared_classifiers) <= classifiers


def test_project_version_is_the_only_release_version_source() -> None:
    project_version = load_pyproject()["project"]["version"]
    package_source = (ROOT / "src" / "controlel" / "__init__.py").read_text(encoding="utf-8")
    version_files = [
        path for path in (ROOT / "src" / "controlel").rglob("*.py") if "__version__" in path.read_text(encoding="utf-8")
    ]

    assert project_version == "0.17.0"
    assert controlel.__version__ == project_version
    assert importlib.metadata.version("controlel") == project_version
    assert version_files == [ROOT / "src" / "controlel" / "__init__.py"]
    assert 'version("controlel")' in package_source
    assert "0.0.0+uninstalled" in package_source
    assert project_version not in package_source


def test_core_candidate_remains_separate_from_ha_public_core_pin() -> None:
    manifest = json.loads((ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8"))
    core_version = load_pyproject()["project"]["version"]

    assert core_version == "0.17.0"
    assert manifest["requirements"] == ["controlel==0.16.0"]
    assert manifest["version"] == "0.14.0"
    assert manifest["version"] != core_version
    assert manifest["issue_tracker"] == "https://github.com/vmshops/controlel/issues"


def test_core_artifact_verification_binds_representative_public_contracts() -> None:
    validator = (ROOT / "scripts" / "packaging" / "validate_artifacts.py").read_text(encoding="utf-8")
    clean_install = (ROOT / "scripts" / "packaging" / "verify_clean_install.py").read_text(encoding="utf-8")
    public_core = (ROOT / "scripts" / "ci" / "verify_public_core.py").read_text(encoding="utf-8")

    required_contracts = {
        "SourceOwnership",
        "SourceCapabilities",
        "ReportedSourceEvidence",
        "OperatingMode",
        "SourceReconciliationPolicy",
        "SourceRecoveryPolicy",
        "SourceResilienceDiagnosticsV1",
        "RuntimeSupervisor",
        "FailsafeRuntime",
        "CommandAuthority",
        "SupervisorPhase",
        "RestartPolicy",
        "RuntimeSupervisionState",
        "RuntimeSupervisionDiagnosticsV1",
        "OperationalEvent",
        "OperationalEventCategory",
        "OperationalEventSeverity",
        "OperationalEventCode",
        "OperationalEventStream",
        "OperationalEventRecorder",
        "operational_event_stream_to_dict",
        "NotificationIntent",
        "NotificationDeliveryPort",
        "NotificationDeliveryResult",
        "NotificationDeliveryStatus",
        "NotificationLevel",
        "NotificationPolicy",
        "NotificationRecipient",
        "NotificationPlanner",
        "NotificationState",
        "notification_state_to_dict",
        "notification_level_for_event",
        "ACTIVITY_NOTIFICATION_RULES",
        "notification_rule_for_activity",
        "UserActivity",
        "UserActivityParameter",
        "UserActivityType",
        "UserActivityStatus",
        "UserActivityLevel",
        "UserActivitySnapshot",
        "UserActivityStream",
        "UserActivityComposer",
        "user_activity_snapshot_to_dict",
        "HeatingPerformanceAssessmentCriteria",
        "HeatingPerformanceAssessmentType",
        "HeatingPerformanceStatus",
        "HeatingPerformanceWindowAssessment",
        "HeatingPerformanceSnapshot",
        "HeatingPerformanceAssessor",
        "HeatingPerformanceMonitor",
        "heating_performance_snapshot_to_dict",
        "CanonicalConfigurationRevision",
        "CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3",
        "ActiveCanonicalConfigurationV3",
        "CanonicalConfigurationDraftV3",
        "CanonicalConfigurationLifecycleV3",
        "CanonicalConfigurationRevisionV3",
        "CanonicalConfigurationValidationV3",
        "ConfigurationScopesV3",
        "author_greenfield_heating_scopes_v3",
        "migrate_heating_v2_revision_to_v3",
        "new_configuration_id_v3",
        "DiscoverySnapshot",
        "DraftRevision",
        "ValidationReport",
        "ConfigEntryActiveReferenceStore",
        "HeatingBindingSelectionRequest",
        "HeatingSetupHostService",
        "HeatingSetupSessionDTO",
        "HomeAssistantDiscoveryAdapter",
        "HomeAssistantSetupRepository",
        "HEATING_SETUP_SCHEMA_VERSION",
        "POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION",
        "HeatingDiagnosticPolicy",
        "HeatingNotificationPolicy",
        "HeatingNotificationRecipient",
        "HeatingSetupAdapter",
        "HeatingSetupPayload",
        "ActivationCoordinator",
        "WATER_SAFETY_MODULE_KEY",
        "WATER_SAFETY_SETUP_SCHEMA_VERSION",
        "WaterSafetySetupAdapter",
        "WaterSafetySetupPayload",
        "WaterSafetyDiagnosticsProjector",
        "WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION",
        "WaterSafetyActionsAvailableV1",
        "WaterSafetyDiagnosticsSnapshotV1",
        "water_safety_diagnostics_to_dict",
        "WaterOutputOutcome",
        "WaterSafetyDiagnostics",
        "WaterSafetyEvidencePort",
        "WaterSafetyOutputPort",
        "WaterSafetyRuntime",
        "WaterSafetyStatePort",
        "MoistureCondition",
        "MoistureObservation",
        "WaterIncident",
        "WaterIncidentStatus",
        "WaterSafetyAssessmentStatus",
        "WaterSafetySnapshot",
        "WaterSafetyState",
        "WaterSafetyBindingSelectionRequest",
        "WaterSafetySetupHostService",
        "WaterSafetySetupSessionDTO",
        "async_snapshot_with_notify_services",
        "FRONTEND_API_VERSION",
        "FrontendApiEvidenceV1",
        "FrontendApiProviderV1",
        "HeatSourceEvidenceV1",
        "BuildingEvidenceV1",
        "SystemEvidenceV1",
        "WaterSafetyEvidenceV1",
        "WaterSafetyResponseV1",
        "frontend_response_to_dict",
    }
    assert all(contract in clean_install for contract in required_contracts)
    frontend_api_contracts = {
        "FRONTEND_API_VERSION",
        "FrontendApiEvidenceV1",
        "FrontendApiProviderV1",
        "HeatSourceEvidenceV1",
        "BuildingEvidenceV1",
        "SystemEvidenceV1",
        "frontend_response_to_dict",
    }
    assert all(contract in public_core for contract in frontend_api_contracts)
    for module in (
        "domain/source_control/__init__.py",
        "domain/operating_mode/__init__.py",
        "application/services/source_reconciliation_policy.py",
        "application/services/source_recovery_policy.py",
        "application/state/source_resilience_diagnostics.py",
        "application/runtime/runtime_supervisor.py",
        "application/runtime/failsafe_runtime.py",
        "application/state/runtime_supervision_state.py",
        "domain/runtime_supervision/__init__.py",
        "domain/operational_events/__init__.py",
        "application/services/operational_event_stream.py",
        "application/services/operational_event_recorder.py",
        "application/ports/notification_delivery_port.py",
        "application/services/notification_planner.py",
        "application/services/notification_processor.py",
        "application/services/notification_policy.py",
        "application/state/notification_state.py",
        "domain/notifications/__init__.py",
        "domain/user_activities/__init__.py",
        "application/services/user_activity_stream.py",
        "application/services/user_activity_composer.py",
        "domain/heat_delivery/performance.py",
        "application/services/heating_performance_assessor.py",
        "application/services/heating_performance_monitor.py",
        "application/services/shadow_heating_performance_monitor.py",
        "application/setup/model.py",
        "application/setup/activation.py",
        "application/configuration/heating_setup_adapter.py",
        "application/configuration/canonical_v3.py",
        "application/configuration/canonical_v3_authoring.py",
        "application/configuration/canonical_v3_conversion.py",
        "application/configuration/canonical_v3_lifecycle.py",
        "application/configuration/canonical_v3_migration.py",
        "application/configuration/canonical_defaults.py",
        "application/configuration/__init__.py",
        "application/configuration/water_safety_setup_adapter.py",
        "application/services/water_safety_projector.py",
        "application/state/water_safety_diagnostics.py",
        "application/water_safety/__init__.py",
        "application/water_safety/model.py",
        "application/water_safety/ports.py",
        "application/water_safety/runtime.py",
        "domain/water_safety/__init__.py",
        "domain/water_safety/model.py",
        "infrastructure/home_assistant/setup_discovery.py",
        "infrastructure/home_assistant/setup_host.py",
        "infrastructure/home_assistant/setup_persistence.py",
        "infrastructure/home_assistant/water_safety_discovery.py",
        "infrastructure/home_assistant/water_safety_setup_host.py",
        "frontend_api/__init__.py",
        "frontend_api/v1/__init__.py",
        "frontend_api/v1/models.py",
        "frontend_api/v1/provider.py",
    ):
        assert module in validator


def test_setup_backend_uses_the_versioned_public_core_surface_without_activation() -> None:
    from controlel.infrastructure import home_assistant

    required = {
        "SETUP_STORAGE_VERSION",
        "ConfigEntryActiveReferenceStore",
        "HeatingBindingSelectionRequest",
        "HeatingSetupHostService",
        "HeatingSetupSessionDTO",
        "HomeAssistantDiscoveryAdapter",
        "HomeAssistantSetupRepository",
    }
    backend = (ROOT / "custom_components" / "controlel" / "setup_backend.py").read_text(encoding="utf-8")

    assert required <= set(home_assistant.__all__)
    assert "from controlel.infrastructure.home_assistant import (" in backend
    assert "controlel.infrastructure.home_assistant.setup_" not in backend
    assert not hasattr(home_assistant.HeatingSetupHostService, "activate")
    assert not hasattr(home_assistant.HeatingSetupHostService, "activate_heating_draft")


def test_release_metadata_records_published_core_and_unpublished_ha_boundary() -> None:
    metadata = (ROOT / "release-metadata" / "releases.yaml").read_text(encoding="utf-8")
    candidate_note = (ROOT / "docs" / "releases" / "core-0.17.0.md").read_text(encoding="utf-8")
    normalized_candidate_note = " ".join(candidate_note.split())
    core_note = (ROOT / "docs" / "releases" / "core-0.14.0.md").read_text(encoding="utf-8")
    integration_note = (ROOT / "docs" / "releases" / "home-assistant-0.14.0.md").read_text(encoding="utf-8")
    previous_integration_note = (ROOT / "docs" / "releases" / "home-assistant-0.13.0.md").read_text(encoding="utf-8")

    assert "release_id: controlel-core-0.17.0" in metadata
    assert "release_id: controlel-core-0.14.0" in metadata
    assert "release_id: controlel-core-0.16.0" in metadata
    assert "release_id: controlel-core-0.15.0" in metadata
    assert "release_id: controlel-core-0.13.0" in metadata
    assert "release_id: controlel-core-0.12.0" in metadata
    assert "release_id: controlel-home_assistant-0.14.0" in metadata
    assert "release_id: controlel-home_assistant-0.13.0" in metadata
    assert "release_id: controlel-home_assistant-0.12.0" in metadata
    assert metadata.count('version: "0.17.0"') == 1
    assert metadata.count('version: "0.16.0"') == 1
    assert metadata.count('version: "0.15.0"') == 1
    assert metadata.count('version: "0.14.0"') == 2
    assert metadata.count('version: "0.13.0"') == 2
    assert metadata.count('version: "0.12.0"') == 2
    assert metadata.count("status: published") >= 6
    assert metadata.count("status: candidate") >= 3
    assert 'title: "Controlel Core 0.17.0"' in metadata
    assert 'previous_public_core: "0.16.0"' in metadata
    assert 'tag: "core-v0.16.0"' in metadata
    assert 'title: "Controlel Core 0.16.0"' in metadata
    assert 'title: "Controlel Core 0.15.0"' in metadata
    assert "status: candidate" in metadata
    assert 'commit_sha: "6a587728551a1ae8f9d04b8ddef8f2cde288a469"' in metadata
    assert "1bd604429b8a655f6a4295f8b95378fafa194ff9c070eb884745a620cb3c0b8e" in metadata
    assert "6a132d3af66261b704d07e055305fe81d62c9648bbd075a3c66300c98cd3050a" in metadata
    assert 'tag: "core-v0.14.0"' in metadata
    assert 'commit_sha: "3c42d487a72682068e090097036b2d79cca30b23"' in metadata
    assert "fd7b89b86f3eb1ed74322c4e290d9a168ff67cef1c001a1ee3f9270b171f4f0a" in metadata
    assert "e2af5b6345bfbfa06836d1ffa1f99a196c42bf5f9337937d4935d76dca416978" in metadata
    assert 'tag: "core-v0.13.0"' in metadata
    assert 'commit_sha: "0fdaaa21341e03e9c01f33acfdac8197929fa841"' in metadata
    assert "233f395993dd9b6b0f16fa3cf267b61ec332e2e7f36aa17d84ac37a1fa925ff2" in metadata
    assert "001e69c0f0fd3bdfeecc751472689d2d59d27b6f8ff0e4b3cde7d3b1cd08c164" in metadata
    assert 'tag: "core-v0.12.0"' in metadata
    assert 'commit_sha: "992b291902318f4f0406c4b368282ff3a7ed4dbf"' in metadata
    assert "d8fd95c1534affd4f1c967e6765a8682587e05dc54528b86721332e950aaf78b" in metadata
    assert "6e59c5fae5098a35069458f5c09b2eed8e837cd9a95b7bd7156865a1acdde6a6" in metadata
    assert 'required_core: "0.16.0"' in metadata
    assert 'required_core: "0.14.0"' in metadata
    assert "Status: prepared release candidate" in normalized_candidate_note
    assert "Water Safety V1" in normalized_candidate_note
    assert "canonical configuration v3 behavior remain unchanged" in normalized_candidate_note
    assert "does not confirm the physical output state" in normalized_candidate_note
    assert "separate composition on published Core 0.16.0" in normalized_candidate_note
    assert "HeatingDiagnosticPolicy" in core_note
    assert "HeatingNotificationPolicy" in core_note
    assert "schema-v1 revisions" in core_note
    assert "No legacy converter" in core_note
    assert "Both public files match" in core_note
    assert "canonical configuration v3" in integration_note.casefold()
    assert "Frontend API v1" in previous_integration_note
    assert "authenticated read-only WebSocket" in previous_integration_note
    assert "No write APIs" in previous_integration_note
    core_note_016 = (ROOT / "docs" / "releases" / "core-0.16.0.md").read_text(encoding="utf-8")
    assert "Status: published" in core_note_016
    assert "canonical configuration v3" in core_note_016.casefold()
    previous_candidate_note = (ROOT / "docs" / "releases" / "core-0.15.0.md").read_text(encoding="utf-8")
    assert "unreleased development candidate" in previous_candidate_note
    assert "Published Core 0.14.0 artifacts" in previous_candidate_note


def test_development_composition_matches_the_public_release_boundary() -> None:
    builder = (ROOT / "scripts" / "packaging" / "build_development_composition.py").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["requirements"] == ["controlel==0.16.0"]
    assert 'DEVELOPMENT_CORE_VERSION = "0.17.0"' in builder
    assert '"publishable": False' in builder
    assert '"integration/controlel.zip"' in builder
    assert "development integration manifest has the wrong Core pin" in builder


def test_packaging_tools_are_pinned_and_isolated() -> None:
    requirements = (ROOT / "requirements" / "package-test.txt").read_text(encoding="utf-8").splitlines()

    assert requirements == [
        "build==1.5.0",
        "trove-classifiers==2026.6.1.19",
        "twine==6.2.0",
    ]
    assert not (ROOT / "src" / "controlel" / "py.typed").exists()


def test_artifact_policy_rejects_repository_and_secret_content() -> None:
    with pytest.raises(ArtifactValidationError, match="forbidden path"):
        _assert_no_forbidden_content(["controlel/__init__.py", "tests/test_core.py"], artifact="test.whl")
    with pytest.raises(ArtifactValidationError, match="forbidden file"):
        _assert_no_forbidden_content(["controlel/__init__.py", ".pypirc"], artifact="test.tar.gz")


def test_packaging_ci_builds_and_validates_without_publishing() -> None:
    workflow = (ROOT / ".github" / "workflows" / "packaging.yml").read_text(encoding="utf-8")

    required_commands = {
        "python scripts/packaging/build_core_release.py",
        "python -m twine check dist/*",
        "python scripts/packaging/validate_artifacts.py dist",
        "python scripts/packaging/verify_clean_install.py dist",
    }
    assert all(command in workflow for command in required_commands)
    assert "actions/checkout@v5" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "publish" not in workflow.casefold()
    assert "upload" not in workflow.casefold()
    assert "token" not in workflow.casefold()


def test_ci_validates_ha_public_core_from_pypi() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "tests/domain" in workflow
    assert "tests/application" in workflow
    assert "tests/frontend_api" in workflow
    assert "tests/infrastructure" in workflow
    assert "tests/architecture" in workflow
    assert "tests/packaging" in workflow
    assert "python -m pytest --ignore=tests/integrations/home_assistant/framework" not in workflow
    assert "home-assistant-public:" in workflow
    assert "home-assistant-framework-public:" in workflow
    assert "home-assistant-candidate:" not in workflow
    assert "CONTROLEL_FRAMEWORK_COMPOSITION: public" in workflow
    assert workflow.count("python -m pip install -e .") == 1
    assert workflow.count("python -m pip install --no-cache-dir controlel==0.16.0") == 2
    assert workflow.count("python scripts/ci/verify_public_core.py") == 2
    assert workflow.count("python scripts/ci/verify_ha_candidate_core.py") == 0
    assert workflow.count("--asyncio-mode=auto") == 1
    assert "controlel==0.10.0" not in workflow


def test_core_and_integration_tag_namespaces_are_explicit() -> None:
    release_guide = (ROOT / "docs" / "development" / "ReleaseGuide.md").read_text(encoding="utf-8")
    normalized_guide = " ".join(release_guide.split())

    assert "`core-vX.Y.Z` is reserved for core/PyPI releases" in normalized_guide
    assert "`vX.Y.Z` is reserved for Home Assistant integration releases" in normalized_guide
    assert "`core-v0.2.0` is the namespace-correct tag name" in normalized_guide
    assert "existing integration tag `v0.2.0` must remain unchanged" in normalized_guide


def test_public_core_provenance_records_history_and_current_composition_hash() -> None:
    release_guide = (ROOT / "docs" / "development" / "ReleaseGuide.md").read_text(encoding="utf-8")
    checker = (ROOT / "scripts" / "ci" / "verify_public_core.py").read_text(encoding="utf-8")

    wheel_hash = "a8756b0a1bc3efff7876439bbc12db42d3632ce2aa5bb1a4f8a74400fd76500e"
    sdist_hash = "f97bd8f1b129f7dcf2024ce4eeafbba5f0f4ffa49f6d0ee5704dddccfdf55289"
    assert "built from a dirty Milestone 27 working" in release_guide
    assert "equivalent to `core-v0.3.0`" in release_guide
    assert wheel_hash in release_guide
    assert sdist_hash in release_guide
    assert "controlel-0.16.0-py3-none-any.whl" in checker
    assert "PUBLIC_WHEEL_SIZE = 262_788" in checker
    assert "1bd604429b8a655f6a4295f8b95378fafa194ff9c070eb884745a620cb3c0b8e" in checker
    assert "controlel-0.16.0.tar.gz" in checker
    assert "PUBLIC_SDIST_SIZE = 185_466" in checker
    assert "6a132d3af66261b704d07e055305fe81d62c9648bbd075a3c66300c98cd3050a" in checker
    assert 'distribution.read_text("direct_url.json") is None' in checker


def test_strict_final_core_release_interface_and_sequence_are_documented() -> None:
    preparer = ROOT / "scripts" / "packaging" / "prepare_final_core_release.py"
    validator = ROOT / "scripts" / "packaging" / "validate_core_release_provenance.py"
    release_guide = (ROOT / "docs" / "development" / "ReleaseGuide.md").read_text(encoding="utf-8")
    normalized = " ".join(release_guide.split())

    assert preparer.is_file()
    assert validator.is_file()
    for argument in ("--version", "--commit", "--tag", "--output-dir"):
        assert argument in preparer.read_text(encoding="utf-8")
    for argument in ("--provenance", "--artifact-dir"):
        assert argument in validator.read_text(encoding="utf-8")
    required_sequence = (
        "implementation; 2. core-only merge; 3. green CI for the exact merged `HEAD`; "
        "4. immutable release verification; 5. annotated `core-vX.Y.Z` tag"
    )
    assert required_sequence in normalized
    assert "An older candidate artifact must never be uploaded" in normalized
    assert "PyPI versions are immutable" in normalized

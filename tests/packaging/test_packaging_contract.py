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
    assert project["version"] == "0.10.0"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.13"
    assert project["license"] == "MIT"
    assert project["authors"] == [{"name": "vmshops"}]
    assert project["dependencies"] == ["pydantic>=2.0"]
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

    assert project_version == "0.10.0"
    assert controlel.__version__ == project_version
    assert importlib.metadata.version("controlel") == project_version
    assert version_files == [ROOT / "src" / "controlel" / "__init__.py"]
    assert 'version("controlel")' in package_source
    assert "0.0.0+uninstalled" in package_source
    assert project_version not in package_source


def test_manifest_pins_published_core_and_keeps_version_independent() -> None:
    manifest = json.loads((ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8"))
    core_version = load_pyproject()["project"]["version"]

    assert core_version == "0.10.0"
    assert manifest["requirements"] == ["controlel==0.8.0"]
    assert manifest["version"] == "0.10.1"
    assert manifest["version"] != core_version
    assert manifest["issue_tracker"] == "https://github.com/vmshops/controlel/issues"


def test_core_artifact_verification_binds_representative_public_contracts() -> None:
    validator = (ROOT / "scripts" / "packaging" / "validate_artifacts.py").read_text(encoding="utf-8")
    clean_install = (ROOT / "scripts" / "packaging" / "verify_clean_install.py").read_text(encoding="utf-8")

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
    }
    assert all(contract in clean_install for contract in required_contracts)
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
    ):
        assert module in validator


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


def test_ci_separates_repository_core_from_released_ha_public_core_compositions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "tests/domain" in workflow
    assert "tests/application" in workflow
    assert "tests/infrastructure" in workflow
    assert "tests/architecture" in workflow
    assert "tests/packaging" in workflow
    assert "python -m pytest --ignore=tests/integrations/home_assistant/framework" not in workflow
    assert "home-assistant-public:" in workflow
    assert "home-assistant-framework-public:" in workflow
    assert "home-assistant-framework-local:" not in workflow
    assert "CONTROLEL_FRAMEWORK_COMPOSITION: local" not in workflow
    assert "CONTROLEL_FRAMEWORK_COMPOSITION: public" in workflow
    assert workflow.count("controlel==0.8.0") == 2
    assert workflow.count("python scripts/ci/verify_public_core.py") == 2
    assert "candidate-core-wheel" not in workflow


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
    assert "controlel-0.8.0-py3-none-any.whl" in checker
    assert "PUBLIC_WHEEL_SIZE = 141_379" in checker
    assert "b9f12d0fadf8a0a53e7bd102fc707bf2b518e776b92a2cdbee240562b4079d8f" in checker
    assert "controlel-0.8.0.tar.gz" in checker
    assert "PUBLIC_SDIST_SIZE = 89_285" in checker
    assert "3aa051d187ab5b5305584f67893ed8a89c82bd7061fa3a28ecc4f9136b0fa84c" in checker
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

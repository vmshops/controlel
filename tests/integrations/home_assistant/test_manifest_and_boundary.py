import ast
import json
import tomllib
from pathlib import Path

from controlel.domain.heat_delivery import (
    HeatingPerformanceAssessmentReason,
    ObservationQuality,
)
from custom_components.controlel.const import CONFIG_ENTRY_VERSION, INTEGRATION_VERSION

ROOT = Path(__file__).parents[3]
COMPONENT = ROOT / "custom_components" / "controlel"


def test_manifest_has_required_custom_component_contract():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest == {
        "domain": "controlel",
        "name": "Controlel",
        "codeowners": ["@vmshops"],
        "config_flow": True,
        "documentation": "https://github.com/vmshops/controlel",
        "issue_tracker": "https://github.com/vmshops/controlel/issues",
        "integration_type": "hub",
        "iot_class": "local_push",
        "requirements": ["controlel==0.8.0"],
        "single_config_entry": True,
        "version": "0.10.1",
    }


def test_core_and_integration_versions_are_intentionally_independent():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        core_version = tomllib.load(pyproject_file)["project"]["version"]

    assert core_version == "0.10.0"
    assert manifest["version"] == INTEGRATION_VERSION == "0.10.1"
    assert manifest["requirements"] == ["controlel==0.8.0"]
    assert manifest["version"] != manifest["requirements"][0].partition("==")[2]


def test_manifest_requirement_is_one_exact_public_distribution_pin():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    requirements = manifest["requirements"]

    assert requirements == ["controlel==0.8.0"]
    assert len(requirements) == 1
    assert not any(marker in requirements[0] for marker in ("~=", ">=", "<=", " @ ", "git+", "-e ", "file:"))


def test_required_integration_files_exist():
    required = {
        "__init__.py",
        "manifest.json",
        "const.py",
        "config.py",
        "config_flow.py",
        "host.py",
        "runtime_executor.py",
        "scheduler.py",
        "measurement_ingestion.py",
        "observability.py",
        "heat_source.py",
        "failure_sink.py",
        "strings.json",
        "translations/en.json",
    }

    assert required <= {
        str(path.relative_to(COMPONENT)).replace("\\", "/") for path in COMPONENT.rglob("*") if path.is_file()
    }


def test_operational_translations_are_truthful_and_action_oriented():
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    sensors = strings["entity"]["sensor"]
    binary_sensors = strings["entity"]["binary_sensor"]

    assert binary_sensors == {
        "heat_required": {"name": "Heating is requested", "state": {"on": "Yes", "off": "No"}},
        "measurement_valid": {"name": "Measurement is valid", "state": {"on": "Yes", "off": "No"}},
        "runtime_active": {"name": "Runtime is active", "state": {"on": "Yes", "off": "No"}},
        "recoverable_failure": {
            "name": "Recoverable failure is active",
            "state": {"on": "Yes", "off": "No"},
        },
        "fatal_failure": {"name": "Fatal failure is active", "state": {"on": "Yes", "off": "No"}},
        "safety_bypassed_lockout": {
            "name": "Safety command bypassed source lockout",
            "state": {"on": "Yes", "off": "No"},
        },
        "emergency_disable_attempted": {
            "name": "Emergency heating-off command was attempted",
            "state": {"on": "Yes", "off": "No"},
        },
    }
    assert sensors["grace_remaining"]["name"] == ("Sensor failure grace time remaining")
    assert sensors["grace_deadline"]["name"] == "Sensor failure grace deadline"
    assert (
        sensors["last_decision"]["state"]["indeterminate_preserve_previous"]
        == "Previous demand preserved during sensor failure grace period"
    )
    assert sensors["last_decision"]["state"]["timeout_disable_heating"] == "Heating-off command requested"
    assert sensors["last_decision_reason"]["state"]["measurement_stale"] == "Measurement became stale"
    assert sensors["last_decision_reason"]["state"]["safety_grace_expired"] == "Sensor failure grace period expired"


def test_heating_diagnostic_translations_cover_every_exposed_code() -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    sensors = strings["entity"]["sensor"]
    performance = sensors["heating_performance"]

    assert set(performance["state"]) == {
        "no_episode",
        "observing",
        "assessment_pending",
        "assessed",
        "insufficient_evidence",
        "conflicting_evidence",
        "interrupted",
        "assessment_failed",
        "diagnostics_unavailable",
    }
    assert set(performance["state_attributes"]["latest_assessment_reason_codes"]["state"]) == {
        item.value for item in HeatingPerformanceAssessmentReason
    }
    assert set(performance["state_attributes"]["observation_quality"]["state"]) == {
        item.value for item in ObservationQuality
    }
    assert set(sensors["shadow_pipeline_health"]["state"]) == {
        "healthy",
        "pending",
        "degraded",
        "dropping",
        "unavailable",
    }
    assert english["entity"]["sensor"]["heating_performance"] == performance
    assert english["entity"]["sensor"]["shadow_pipeline_health"] == sensors["shadow_pipeline_health"]


def test_config_flow_exposes_supported_options_flow_without_reconfigure_flow():
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    assert "VERSION = CONFIG_ENTRY_VERSION" in source
    assert CONFIG_ENTRY_VERSION == 1
    assert "async_step_user" in source
    assert "async_get_options_flow" in source
    assert "class ControlelOptionsFlow" in source
    assert "async_step_reconfigure" not in source


def test_core_has_no_home_assistant_or_custom_component_imports():
    forbidden = ("import homeassistant", "from homeassistant", "custom_components")
    core_files = list((ROOT / "src" / "controlel").rglob("*.py"))

    assert core_files
    for path in core_files:
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden), path


def test_home_assistant_diagnostics_consumes_only_application_snapshot_boundary() -> None:
    host_source = (COMPONENT / "host.py").read_text(encoding="utf-8")
    tree = ast.parse(host_source)
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "controlel.application.services.heating_diagnostics_boundary" in imported_modules
    assert "controlel.domain.heat_delivery" not in imported_modules
    assert "HeatingEpisode" not in host_source
    assert "_diagnostic_evidence_timestamp" not in host_source


def test_normal_project_dependencies_exclude_home_assistant():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = pyproject.split("[dependency-groups]", maxsplit=1)[0]

    assert "homeassistant" not in project_dependencies.casefold()
    assert "pytest-homeassistant" not in project_dependencies.casefold()


def test_custom_component_does_not_contain_duplicate_core_source():
    assert not (COMPONENT / "controlel").exists()
    assert not (ROOT / "src" / "controlel" / "integrations" / "home_assistant").exists()


def test_home_assistant_uses_narrow_public_runtime_start_boundary() -> None:
    integration_source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")

    assert "self.record_runtime_started()" in integration_source
    assert "_record_operational" not in integration_source
    assert "emit(" not in integration_source

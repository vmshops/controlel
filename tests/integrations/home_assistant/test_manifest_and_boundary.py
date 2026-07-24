import json
from pathlib import Path

from custom_components.controlel.const import CONFIG_ENTRY_VERSION

ROOT = Path(__file__).parents[3]
COMPONENT = ROOT / "custom_components" / "controlel"


def test_manifest_has_required_custom_component_contract():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest == {
        "domain": "controlel",
        "name": "Controlel",
        "version": "0.1.0",
        "config_flow": True,
        "single_config_entry": True,
        "integration_type": "hub",
        "iot_class": "local_push",
        "requirements": [],
    }


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
        "heat_source.py",
        "failure_sink.py",
        "strings.json",
        "translations/en.json",
    }

    assert required <= {
        str(path.relative_to(COMPONENT)).replace("\\", "/") for path in COMPONENT.rglob("*") if path.is_file()
    }


def test_config_flow_is_explicit_and_has_no_options_or_reconfigure_flow():
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    assert "VERSION = CONFIG_ENTRY_VERSION" in source
    assert CONFIG_ENTRY_VERSION == 1
    assert "async_step_user" in source
    assert "async_step_options" not in source
    assert "async_step_reconfigure" not in source


def test_core_has_no_home_assistant_or_custom_component_imports():
    forbidden = ("import homeassistant", "from homeassistant", "custom_components")
    core_files = list((ROOT / "src" / "controlel").rglob("*.py"))

    assert core_files
    for path in core_files:
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden), path


def test_normal_project_dependencies_exclude_home_assistant():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = pyproject.split("[dependency-groups]", maxsplit=1)[0]

    assert "homeassistant" not in project_dependencies.casefold()
    assert "pytest-homeassistant" not in project_dependencies.casefold()


def test_custom_component_does_not_contain_duplicate_core_source():
    assert not (COMPONENT / "controlel").exists()
    assert not (ROOT / "src" / "controlel" / "integrations" / "home_assistant").exists()

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
WATER_DOMAIN = ROOT / "src" / "controlel" / "domain" / "water_safety"
WATER_APPLICATION = ROOT / "src" / "controlel" / "application" / "water_safety"
WATER_SETUP_ADAPTER = (
    ROOT / "src" / "controlel" / "application" / "configuration" / "water_safety_setup_adapter.py"
)
SHARED_SETUP = ROOT / "src" / "controlel" / "application" / "setup"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_water_domain_is_host_neutral_and_does_not_depend_on_application() -> None:
    forbidden = ("controlel.application", "controlel.infrastructure", "homeassistant", "custom_components")

    for path in sorted(WATER_DOMAIN.rglob("*.py")):
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in _imports(path)
            for prefix in forbidden
        )


def test_water_runtime_is_independent_from_heating_and_home_assistant() -> None:
    forbidden = ("controlel.domain.regulation", "controlel.domain.source_control", "homeassistant", "custom_components")
    files = (*sorted(WATER_APPLICATION.rglob("*.py")), WATER_SETUP_ADAPTER)

    for path in files:
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in _imports(path)
            for prefix in forbidden
        )
        assert "entity_id" not in path.read_text(encoding="utf-8")


def test_water_roles_do_not_leak_into_shared_setup_authority() -> None:
    for path in sorted(SHARED_SETUP.rglob("*.py")):
        assert "water_safety." not in path.read_text(encoding="utf-8")

"""Static dependency-direction guards for the production Python packages."""

import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).parents[2]
CORE = ROOT / "src" / "controlel"


def _module_name(path: Path) -> str:
    try:
        relative = path.relative_to(ROOT / "src").with_suffix("")
    except ValueError:
        relative = path.relative_to(ROOT).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    """Return absolute import targets without importing repository code."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    current_module = _module_name(path)
    package = current_module if path.name == "__init__.py" else current_module.rpartition(".")[0]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(resolve_name(f"{'.' * node.level}{module}", package) if node.level else module)
    return imported


def _assert_no_import_prefixes(root: Path, forbidden: tuple[str, ...]) -> None:
    files = sorted(root.rglob("*.py"))
    assert files
    for path in files:
        violations = sorted(
            imported
            for imported in _imported_modules(path)
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden)
        )
        assert not violations, f"{path.relative_to(ROOT)} imports forbidden layer(s): {violations}"


def test_domain_does_not_depend_on_application_infrastructure_or_home_assistant() -> None:
    _assert_no_import_prefixes(
        CORE / "domain",
        (
            "controlel.application",
            "controlel.infrastructure",
            "controlel.simulation",
            "custom_components",
            "homeassistant",
        ),
    )


def test_application_does_not_depend_on_infrastructure_or_home_assistant() -> None:
    _assert_no_import_prefixes(
        CORE / "application",
        (
            "controlel.infrastructure",
            "controlel.simulation",
            "custom_components",
            "homeassistant",
        ),
    )


def test_production_infrastructure_does_not_depend_on_simulation() -> None:
    _assert_no_import_prefixes(CORE / "infrastructure", ("controlel.simulation",))


def test_simulation_does_not_depend_on_home_assistant_or_production_infrastructure() -> None:
    _assert_no_import_prefixes(
        CORE / "simulation",
        (
            "controlel.infrastructure",
            "custom_components",
            "homeassistant",
        ),
    )


def test_home_assistant_composition_does_not_depend_on_simulation() -> None:
    _assert_no_import_prefixes(ROOT / "custom_components" / "controlel", ("controlel.simulation",))

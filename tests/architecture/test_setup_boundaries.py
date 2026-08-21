import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SETUP_KERNEL = ROOT / "src" / "controlel" / "application" / "setup"


def test_shared_setup_kernel_has_no_heating_or_runtime_domain_dependency() -> None:
    forbidden = {
        "controlel.application.configuration.heating_setup_adapter",
        "controlel.domain.value_objects.sensor_id",
        "controlel.domain.value_objects.zone_id",
        "controlel.domain.entities.zone",
        "controlel.domain.sensors.sensor",
    }
    for path in sorted(SETUP_KERNEL.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert imports.isdisjoint(forbidden), f"{path.relative_to(ROOT)} imports Heating-specific code"


def test_production_layers_do_not_import_setup_module_adapter() -> None:
    adapter_module = "controlel.application.configuration.heating_setup_adapter"
    roots = (
        ROOT / "src" / "controlel" / "domain",
        ROOT / "src" / "controlel" / "application" / "runtime",
        ROOT / "src" / "controlel" / "application" / "services",
    )
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
            }
            assert adapter_module not in imports

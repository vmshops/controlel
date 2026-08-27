import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SETUP_KERNEL = ROOT / "src" / "controlel" / "application" / "setup"
HA_DISCOVERY_ADAPTER = ROOT / "src" / "controlel" / "infrastructure" / "home_assistant" / "setup_discovery.py"
HA_SETUP_HOST = ROOT / "src" / "controlel" / "infrastructure" / "home_assistant" / "setup_host.py"
HA_SETUP_PERSISTENCE = ROOT / "src" / "controlel" / "infrastructure" / "home_assistant" / "setup_persistence.py"
INTEGRATION_INIT = ROOT / "custom_components" / "controlel" / "__init__.py"
INTEGRATION_SETUP_BACKEND = ROOT / "custom_components" / "controlel" / "setup_backend.py"
CANONICAL_V3 = ROOT / "src" / "controlel" / "application" / "configuration" / "canonical_v3.py"
CANONICAL_V3_MIGRATION = ROOT / "src" / "controlel" / "application" / "configuration" / "canonical_v3_migration.py"


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


def test_shared_setup_kernel_has_no_home_assistant_adapter_dependency() -> None:
    forbidden_prefixes = (
        "homeassistant",
        "custom_components.controlel",
        "controlel.infrastructure.home_assistant",
    )
    for path in sorted(SETUP_KERNEL.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in imports
            for prefix in forbidden_prefixes
        ), f"{path.relative_to(ROOT)} imports a Home Assistant adapter"


def test_heating_roles_do_not_leak_into_shared_setup_or_ha_discovery() -> None:
    files = (*sorted(SETUP_KERNEL.rglob("*.py")), HA_DISCOVERY_ADAPTER)
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "heating.primary_temperature" not in source
        assert "heating.source." not in source
        assert "heating.heat_delivery." not in source


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


def test_ha_setup_adapters_have_no_static_home_assistant_class_dependency() -> None:
    for path in (HA_SETUP_HOST, HA_SETUP_PERSISTENCE):
        source = path.read_text(encoding="utf-8")
        assert "from homeassistant" not in source
        assert "import homeassistant" not in source


def test_new_setup_backend_never_reads_or_merges_legacy_runtime_settings() -> None:
    source = INTEGRATION_SETUP_BACKEND.read_text(encoding="utf-8")
    forbidden = (
        "integration_config_from_entry",
        "integration_config_from_entry_data",
        "merged_entry_configuration",
    )
    assert not any(name in source for name in forbidden)
    assert "setup.legacy_configuration_present" in source
    assert "silently_merged=False" in source


def test_setup_backend_is_lazy_relative_to_released_runtime_imports() -> None:
    tree = ast.parse(INTEGRATION_INIT.read_text(encoding="utf-8"), filename=str(INTEGRATION_INIT))
    top_level_imports = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "setup_backend" not in top_level_imports
    assert "async_get_setup_service" in INTEGRATION_INIT.read_text(encoding="utf-8")


def test_canonical_v3_contract_has_no_runtime_or_provider_adapter_dependency() -> None:
    forbidden_prefixes = (
        "controlel.application.runtime",
        "controlel.infrastructure",
        "custom_components",
        "homeassistant",
    )
    for path in (CANONICAL_V3, CANONICAL_V3_MIGRATION):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in imports
            for prefix in forbidden_prefixes
        ), f"{path.relative_to(ROOT)} imports runtime or provider composition"


def test_canonical_v3_is_not_wired_to_runtime_activation() -> None:
    forbidden_modules = {
        "controlel.application.configuration.canonical_v3",
        "controlel.application.configuration.canonical_v3_migration",
    }
    roots = (
        ROOT / "src" / "controlel" / "application" / "runtime",
        ROOT / "src" / "controlel" / "application" / "services",
        ROOT / "custom_components" / "controlel",
    )
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
            }
            assert imports.isdisjoint(forbidden_modules), f"{path.relative_to(ROOT)} activates canonical v3"

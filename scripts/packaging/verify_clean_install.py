"""Install the built wheel into a temporary environment and smoke-test it."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import venv
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TEST = """
import importlib.metadata
import importlib.util
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sys

import controlel
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.services.source_reconciliation_policy import SourceReconciliationPolicy
from controlel.application.services.source_recovery_policy import SourceRecoveryPolicy
from controlel.application.state.source_resilience_diagnostics import (
    SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION,
    SourceResilienceDiagnosticsV1,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.entities.zone import Zone
from controlel.domain.operating_mode import OperatingMode
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceCapabilities,
    SourceCapability,
    SourceOwnership,
    TransitionHistoryKnowledge,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

expected_version = os.environ["CONTROLEL_EXPECTED_VERSION"]
repository_root = Path(os.environ["CONTROLEL_REPOSITORY_ROOT"]).resolve()
package_path = Path(controlel.__file__).resolve()

assert controlel.__version__ == expected_version
assert importlib.metadata.version("controlel") == expected_version
assert not package_path.is_relative_to(repository_root)
assert "site-packages" in package_path.as_posix()
assert all(
    not Path(entry or ".").resolve().is_relative_to(repository_root)
    for entry in sys.path
)
assert importlib.util.find_spec("homeassistant") is None
assert importlib.util.find_spec("custom_components") is None
assert not any(name == "homeassistant" or name.startswith("homeassistant.") for name in sys.modules)

observed_at = datetime(2026, 1, 1, tzinfo=UTC)
capabilities = SourceCapabilities(
    frozenset({SourceCapability.ENABLE_DISABLE, SourceCapability.WATER_TARGET})
)
reported = ReportedSourceEvidence(
    state=ReportedSourceState.UNKNOWN,
    observed_at=observed_at,
)
assert SourceOwnership.CONTROLEL_OWNED.value == "controlel_owned"
assert capabilities.supports(SourceCapability.WATER_TARGET)
assert reported.transition_history is TransitionHistoryKnowledge.UNKNOWN
assert OperatingMode.NORMAL.value == "normal"
assert SourceReconciliationPolicy() is not None
assert SourceRecoveryPolicy() is not None
assert SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION == 1
assert SourceResilienceDiagnosticsV1.__dataclass_params__.frozen is True

sensor_id = SensorId("living_room_temperature")
zone_id = ZoneId("living_room")
temperature = Temperature(21)
sensors = SensorRepository()
sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name="Living room"))
zones = ZoneRepository()
zones.add(
    Zone(
        zone_id=zone_id,
        primary_sensor_id=sensor_id,
        primary_measurement_max_age=timedelta(minutes=5),
        name="Living room",
        target_temperature=temperature,
    )
)

class Clock:
    def now(self):
        return datetime(2026, 1, 1, tzinfo=UTC)

class ScheduledTask:
    def cancel(self):
        return None

class Scheduler:
    def schedule_at(self, when, callback):
        return ScheduledTask()

class FailureSink:
    def report(self, failure):
        return None

class HeatSource:
    def execute(self, command):
        return None

runtime = ControlRuntime(
    sensors,
    zones,
    HeatSource(),
    Clock(),
    Scheduler(),
    FailureSink(),
    timedelta(0),
    timedelta(minutes=1),
    HeatingAction.DISABLE_HEATING,
)
assert isinstance(runtime, ControlRuntime)
print(f"controlel {controlel.__version__} imported from {package_path}")
"""


def _project_version() -> str:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)["project"]["version"]


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def verify_clean_install(wheel: Path) -> None:
    """Create a clean environment, install only the wheel, and run smoke checks."""
    expected_version = _project_version()
    with tempfile.TemporaryDirectory(prefix="controlel-wheel-") as temporary_directory:
        temporary_root = Path(temporary_directory).resolve()
        environment = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = _environment_python(environment)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel.resolve()),
            ],
            cwd=temporary_root,
            check=True,
        )

        smoke_script = temporary_root / "smoke_installed_controlel.py"
        smoke_script.write_text(textwrap.dedent(SMOKE_TEST), encoding="utf-8")
        environment_variables = os.environ.copy()
        environment_variables.pop("PYTHONHOME", None)
        environment_variables.pop("PYTHONPATH", None)
        environment_variables["CONTROLEL_EXPECTED_VERSION"] = expected_version
        environment_variables["CONTROLEL_REPOSITORY_ROOT"] = str(REPOSITORY_ROOT)
        subprocess.run(
            [str(python), str(smoke_script)],
            cwd=temporary_root,
            env=environment_variables,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", nargs="?", type=Path, default=REPOSITORY_ROOT / "dist")
    arguments = parser.parse_args()
    wheels = sorted(arguments.dist_directory.resolve().glob("*.whl"))
    if len(wheels) != 1:
        parser.error(f"expected exactly one wheel, found {len(wheels)}")
    verify_clean_install(wheels[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

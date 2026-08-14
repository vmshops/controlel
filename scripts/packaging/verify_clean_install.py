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
import importlib
import importlib.metadata
import importlib.util
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sys

import controlel
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.failsafe_runtime import FailsafeRuntime
from controlel.application.runtime.runtime_supervisor import RuntimeSupervisor
from controlel.application.ports.notification_delivery_port import NotificationDeliveryPort
from controlel.application.services.source_reconciliation_policy import SourceReconciliationPolicy
from controlel.application.services.source_recovery_policy import SourceRecoveryPolicy
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.operational_event_stream import (
    OperationalEventStream,
    operational_event_stream_to_dict,
)
from controlel.application.services.user_activity_composer import UserActivityComposer
from controlel.application.services.user_activity_stream import (
    UserActivityStream,
    user_activity_snapshot_to_dict,
)
from controlel.application.services.notification_planner import NotificationPlanner
from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.notification_policy import (
    ACTIVITY_NOTIFICATION_RULES,
    notification_level_for_event,
    notification_rule_for_activity,
)
from controlel.application.state.notification_state import NotificationState, notification_state_to_dict
from controlel.application.state.source_resilience_diagnostics import (
    SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION,
    SourceResilienceDiagnosticsV1,
)
from controlel.application.state.runtime_supervision_state import (
    RuntimeSupervisionDiagnosticsV1,
    RuntimeSupervisionState,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.entities.zone import Zone
from controlel.domain.operating_mode import OperatingMode
from controlel.domain.operational_events import (
    OperationalEvent,
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventSeverity,
)
from controlel.domain.user_activities import (
    UserActivity,
    UserActivityLevel,
    UserActivityParameter,
    UserActivitySnapshot,
    UserActivityStatus,
    UserActivityType,
)
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.runtime_supervision import CommandAuthority, RestartPolicy, SupervisorPhase
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

m30_2d_contracts = (
    RuntimeSupervisor,
    FailsafeRuntime,
    CommandAuthority,
    SupervisorPhase,
    RestartPolicy,
    RuntimeSupervisionState,
    RuntimeSupervisionDiagnosticsV1,
)
for contract in m30_2d_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)

restart_policy = RestartPolicy()
assert restart_policy.attempt_limit == 3
assert restart_policy.retry_interval == timedelta(minutes=5)
assert CommandAuthority.NORMAL.value == "normal"
assert CommandAuthority.FAILSAFE.value == "failsafe"
assert SupervisorPhase.NORMAL.value == "normal"
assert SupervisorPhase.FAILSAFE.value == "failsafe"
assert RuntimeSupervisionState.__dataclass_params__.frozen is True
assert RuntimeSupervisionDiagnosticsV1.__dataclass_params__.frozen is True

m31a_contracts = (
    OperationalEvent,
    OperationalEventCategory,
    OperationalEventSeverity,
    OperationalEventCode,
    OperationalEventStream,
    OperationalEventRecorder,
)
for contract in m31a_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
event_stream = OperationalEventStream(capacity=1)
event_stream.emit(
    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    category=OperationalEventCategory.RUNTIME,
    severity=OperationalEventSeverity.INFO,
    event_code=OperationalEventCode.RUNTIME_STARTED,
)
event_payload = operational_event_stream_to_dict(event_stream.snapshot())
assert event_payload["schema_version"] == 1
assert event_payload["capacity"] == 1
assert event_payload["events"][0]["event_code"] == "runtime_started"

m31b_1_contracts = (
    UserActivity,
    UserActivityParameter,
    UserActivityType,
    UserActivityStatus,
    UserActivityLevel,
    UserActivitySnapshot,
    UserActivityStream,
    UserActivityComposer,
)
for contract in m31b_1_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
activity_source = OperationalEventStream(capacity=2)
activity_source.emit(
    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    category=OperationalEventCategory.MEASUREMENT,
    severity=OperationalEventSeverity.WARNING,
    event_code=OperationalEventCode.MEASUREMENT_BECAME_STALE,
    activity_id="measurement-incident:00000001",
)
activity_composer = UserActivityComposer(activity_source.snapshot, activity_capacity=2)
assert activity_composer.process_available() is True
activity_payload = user_activity_snapshot_to_dict(activity_composer.snapshot())
assert activity_payload["schema_version"] == 2
assert activity_payload["total_activity_revisions_emitted"] == 1
assert activity_payload["activities"][0]["activity_type"] == "measurement_degraded"
assert UserActivityParameter("reported_state", None).value is None

m31b_contracts = (
    NotificationDeliveryPort,
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
    NotificationPlanner,
    NotificationProcessor,
    NotificationState,
)
for contract in m31b_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
notification_planner = NotificationPlanner(NotificationPolicy())
notification_payload = notification_state_to_dict(notification_planner.state())
assert notification_payload["schema_version"] == 2
assert notification_payload["enabled"] is False
assert notification_level_for_event(OperationalEventCode.RUNTIME_FATAL) is NotificationLevel.CRITICAL
assert set(ACTIVITY_NOTIFICATION_RULES) == set(UserActivityType)
assert notification_rule_for_activity(UserActivityType.MEASUREMENT_DEGRADED) is not None
activity_notification_planner = NotificationPlanner(
    NotificationPolicy(
        enabled=True,
        recipients=(
            NotificationRecipient(
                "clean_install",
                "test",
                "redacted-target",
                minimum_level=NotificationLevel.DEBUG,
            ),
        ),
    )
)
activity_intent = activity_notification_planner.plan(activity_composer.snapshot().activities[0]).intents[0]
assert activity_intent.source_activity_id == activity_payload["activities"][0]["activity_id"]
assert activity_intent.activity_type is UserActivityType.MEASUREMENT_DEGRADED

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

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
from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION,
    HeatingDiagnosticPolicy,
    HeatingNotificationPolicy,
    HeatingNotificationRecipient,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
    WaterSafetySetupPayload,
)
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
from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.heating_performance_monitor import (
    HeatingPerformanceMonitor,
    heating_performance_snapshot_to_dict,
)
from controlel.application.services.notification_policy import (
    ACTIVITY_NOTIFICATION_RULES,
    notification_level_for_event,
    notification_rule_for_activity,
)
from controlel.application.services.water_safety_projector import WaterSafetyDiagnosticsProjector
from controlel.application.state.notification_state import NotificationState, notification_state_to_dict
from controlel.application.state.source_resilience_diagnostics import (
    SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION,
    SourceResilienceDiagnosticsV1,
)
from controlel.application.state.runtime_supervision_state import (
    RuntimeSupervisionDiagnosticsV1,
    RuntimeSupervisionState,
)
from controlel.application.state.water_safety_diagnostics import (
    WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION,
    WaterSafetyActionsAvailableV1,
    WaterSafetyDiagnosticsSnapshotV1,
    water_safety_diagnostics_to_dict,
)
from controlel.application.water_safety import (
    WaterOutputOutcome,
    WaterSafetyDiagnostics,
    WaterSafetyEvidencePort,
    WaterSafetyOutputPort,
    WaterSafetyRuntime,
    WaterSafetyStatePort,
)
from controlel.application.configuration import (
    CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3,
    ActiveCanonicalConfigurationV3,
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationLifecycleV3,
    CanonicalConfigurationRevisionV3,
    CanonicalConfigurationValidationV3,
    ConfigurationScopesV3,
    author_greenfield_heating_scopes_v3,
    migrate_heating_v2_revision_to_v3,
    new_configuration_id_v3,
)
from controlel.application.setup import (
    ActivationCoordinator,
    ActiveReference,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    ValidationReport,
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
from controlel.domain.heat_delivery import (
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentType,
    HeatingPerformanceSnapshot,
    HeatingPerformanceStatus,
    HeatingPerformanceWindowAssessment,
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
from controlel.domain.water_safety import (
    MoistureCondition,
    MoistureObservation,
    WaterIncident,
    WaterIncidentStatus,
    WaterSafetyAssessmentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from controlel.infrastructure.home_assistant import (
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    HeatingSetupSessionDTO,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    WaterSafetyBindingSelectionRequest,
    WaterSafetySetupHostService,
    WaterSafetySetupSessionDTO,
    async_snapshot_with_notify_services,
)
from controlel.frontend_api.v1 import (
    FRONTEND_API_VERSION,
    BuildingEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    SystemEvidenceV1,
    WaterSafetyEvidenceV1,
    WaterSafetyResponseV1,
    frontend_response_to_dict,
)

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

m31c_1_contracts = (
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentType,
    HeatingPerformanceStatus,
    HeatingPerformanceWindowAssessment,
    HeatingPerformanceSnapshot,
    HeatingPerformanceAssessor,
    HeatingPerformanceMonitor,
)
for contract in m31c_1_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
performance_monitor = HeatingPerformanceMonitor(assessment_capacity=2, pending_zone_capacity=2)
performance_payload = heating_performance_snapshot_to_dict(performance_monitor.snapshot())
assert performance_payload["schema_version"] == 1
assert performance_payload["assessment_capacity"] == 2
assert performance_payload["zones"] == []

setup_contracts = (
    ActivationCoordinator,
    ActiveReference,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    ValidationReport,
    ConfigEntryActiveReferenceStore,
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    HeatingSetupSessionDTO,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    HeatingDiagnosticPolicy,
    HeatingNotificationPolicy,
    HeatingNotificationRecipient,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
for contract in setup_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
assert SETUP_STORAGE_VERSION == 1
assert POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION == 1
assert HEATING_SETUP_SCHEMA_VERSION == 2
assert HeatingSetupAdapter.module_schema_version == 2
assert HeatingSetupAdapter.validator_policy_version == 3
diagnostic_policy = HeatingDiagnosticPolicy()
assert diagnostic_policy.diagnostic_profile == "basic"
assert diagnostic_policy.debug_duration_seconds == 3600.0
notification_recipient = HeatingNotificationRecipient(
    recipient_id="clean_install",
    target="notify.clean_install",
    categories=(OperationalEventCategory.RUNTIME, OperationalEventCategory.RUNTIME),
)
assert notification_recipient.target_configured is True
assert notification_recipient.categories == (OperationalEventCategory.RUNTIME,)
notification_policy = HeatingNotificationPolicy(enabled=True, recipients=(notification_recipient,))
assert notification_policy.enabled is True
assert notification_policy.recipients == (notification_recipient,)
assert hasattr(HeatingSetupHostService, "canonicalize_heating_draft")
assert not hasattr(HeatingSetupHostService, "activate")
assert not hasattr(HeatingSetupHostService, "activate_heating_draft")
assert not any(name == "homeassistant" or name.startswith("homeassistant.") for name in sys.modules)

canonical_v3_contracts = (
    ActiveCanonicalConfigurationV3,
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationLifecycleV3,
    CanonicalConfigurationRevisionV3,
    CanonicalConfigurationValidationV3,
    ConfigurationScopesV3,
    author_greenfield_heating_scopes_v3,
    migrate_heating_v2_revision_to_v3,
    new_configuration_id_v3,
)
for contract in canonical_v3_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
assert CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3 == 3
configuration_id = new_configuration_id_v3()
assert configuration_id.startswith("heating_")
assert CanonicalConfigurationLifecycleV3 is not None

water_contracts = (
    WaterSafetySetupAdapter,
    WaterSafetySetupPayload,
    WaterSafetyDiagnosticsProjector,
    WaterSafetyActionsAvailableV1,
    WaterSafetyDiagnosticsSnapshotV1,
    WaterSafetyDiagnostics,
    WaterSafetyEvidencePort,
    WaterSafetyOutputPort,
    WaterSafetyRuntime,
    WaterSafetyStatePort,
    MoistureCondition,
    MoistureObservation,
    WaterIncident,
    WaterIncidentStatus,
    WaterSafetyAssessmentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
    WaterSafetyBindingSelectionRequest,
    WaterSafetySetupHostService,
    WaterSafetySetupSessionDTO,
    async_snapshot_with_notify_services,
)
for contract in water_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
assert WATER_SAFETY_MODULE_KEY == "water_safety"
assert WATER_SAFETY_SETUP_SCHEMA_VERSION == 1
assert WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION == 1
water_payload = WaterSafetySetupPayload(
    zone_id="utility",
    zone_name="Utility",
    area_id="utility-room",
    area_name="Utility room",
    sensor_id="utility-moisture",
    unavailable_grace_seconds=60.0,
    fault_repeat_interval_seconds=None,
    notification_target_roles=("water_safety.notification.primary",),
)
assert water_payload.behavior_contract_version == 1
assert WaterSafetySetupAdapter.module_schema_version == 1
water_observation = MoistureObservation(
    sensor_id="utility-moisture",
    condition=MoistureCondition.UNKNOWN,
    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
)
assert water_observation.condition is MoistureCondition.UNKNOWN
water_diagnostics = WaterSafetyDiagnostics(
    state=WaterSafetyState.OK,
    processing_enabled=True,
    sensor_id="utility-moisture",
    zone_id="utility",
    area_id="utility-room",
    critical_sensor=False,
    assessment_status=WaterSafetyAssessmentStatus.INDETERMINATE_GRACE,
    latest_observation=water_observation,
    last_confirmed_observation=None,
    active_incident=None,
    last_incident=None,
    fault_deadline=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    next_fault_notification_at=None,
    owned_outputs=(),
    canonical_revision_id="water-revision",
    semantic_configuration_fingerprint="water-fingerprint",
)
water_projection = WaterSafetyDiagnosticsProjector().project(
    water_diagnostics,
    area_name="Utility room",
    zone_name="Utility",
)
water_projection_payload = water_safety_diagnostics_to_dict(water_projection)
assert water_projection_payload["assessment_status"] == "INDETERMINATE_GRACE"
assert water_projection_payload["sensor_condition"] == "UNKNOWN"
assert water_projection_payload["last_siren_command_outcome"] is None
assert WaterOutputOutcome.ACCEPTED.value == "ACCEPTED"

frontend_api_contracts = (
    BuildingEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    SystemEvidenceV1,
    WaterSafetyEvidenceV1,
    WaterSafetyResponseV1,
    frontend_response_to_dict,
)
for contract in frontend_api_contracts:
    module_path = Path(importlib.import_module(contract.__module__).__file__).resolve()
    assert module_path.is_relative_to(package_path.parent)
assert FRONTEND_API_VERSION == 1

class FrontendEvidenceSource:
    def snapshot(self):
        return FrontendApiEvidenceV1(
            system=SystemEvidenceV1(status="active", operating_mode="NORMAL"),
            building=BuildingEvidenceV1(
                heat_source=HeatSourceEvidenceV1(
                    permission="unknown",
                    command_outcome="held",
                    reported_state="UNKNOWN",
                )
            ),
            water_safety=WaterSafetyEvidenceV1(
                state="SENSOR_FAULT",
                assessment_status="CONFIRMED",
                sensor_condition="UNKNOWN",
                area_name="Utility room",
                zone_name="Utility",
                active_incident=False,
                incident_silenced=False,
                processing_enabled=True,
                owned_siren_count=0,
                last_siren_command_outcome=None,
                actions_available=("disable", "test_notification"),
            ),
        )

class FrontendClock:
    def now(self):
        return datetime(2026, 1, 1, tzinfo=UTC)

frontend_provider = FrontendApiProviderV1(source=FrontendEvidenceSource(), clock=FrontendClock())
frontend_payloads = tuple(
    frontend_response_to_dict(response)
    for response in (
        frontend_provider.overview(),
        frontend_provider.heating(),
        frontend_provider.diagnostics(),
        frontend_provider.setup(),
        frontend_provider.water_safety(),
    )
)
frontend_heating = frontend_payloads[1]
frontend_water = frontend_payloads[4]
assert all(payload["frontend_api_version"] == 1 for payload in frontend_payloads)
assert frontend_heating["building"]["heat_source"]["command_outcome"] == "held"
assert frontend_heating["building"]["heat_source"]["reported_state"] == "UNKNOWN"
assert frontend_heating["building"]["heat_source"]["physical_state"] == "unknown"
assert frontend_water["state"] == "SENSOR_FAULT"
assert frontend_water["sensor_condition"] == "UNKNOWN"
assert frontend_water["actions_available"] == ["disable", "test_notification"]

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
assert activity_intent.correlation_id == activity_payload["activities"][0]["correlation_id"]
assert activity_intent.zone_ids == ()
assert activity_intent.source_ids == ()
assert {parameter.key: parameter.value for parameter in activity_intent.parameters}["status"] == "open"
activity_delivery_result = NotificationDeliveryResult(
    datetime(2026, 1, 1, tzinfo=UTC),
    NotificationDeliveryStatus.DELIVERED,
    activity_intent.source_activity_id,
    activity_intent.recipient_id,
    activity_intent.notification_id,
)
assert activity_delivery_result.source_activity_id == activity_intent.source_activity_id

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

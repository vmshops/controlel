from datetime import UTC, datetime, timedelta

from controlel.application.services.operating_mode_policy import OperatingModePolicy
from controlel.application.services.source_reconciliation_policy import SourceReconciliationPolicy
from controlel.application.services.source_recovery_policy import SourceRecoveryPolicy
from controlel.application.services.source_resilience_diagnostics_projector import (
    SourceResilienceDiagnosticsProjector,
    source_resilience_diagnostics_to_dict,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.operating_mode import OperatingMode, SafeHeatingProfile
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceCapabilities,
    SourceCapability,
    SourceOwnership,
)
from controlel.domain.value_objects.sensor_id import SensorId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_projection_is_immutable_bounded_json_safe_and_reason_code_based() -> None:
    mode_policy = OperatingModePolicy(
        safe_heating_profile=SafeHeatingProfile(
            room_target_temperature=19,
            turn_on_differential=1,
            turn_off_differential=1,
            preferred_sensor_id=SensorId("room"),
        )
    )
    mode = mode_policy.activate(
        mode_policy.initial_state(now=NOW),
        mode=OperatingMode.MANUAL_RECOVERY_HEAT,
        now=NOW,
    )
    reported = ReportedSourceEvidence(
        state=ReportedSourceState.DISABLED,
        observed_at=NOW,
    )
    reconciliation = SourceReconciliationPolicy().evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.ENABLE_HEATING,
        last_successful_command=None,
        reported=reported,
        current_state=None,
        now=NOW,
    )
    recovery_policy = SourceRecoveryPolicy()
    recovery = recovery_policy.evaluate(
        current_state=recovery_policy.begin(now=NOW),
        demand_known=True,
        reported_source_known=True,
        now=NOW,
    )

    snapshot = SourceResilienceDiagnosticsProjector().project(
        operating_mode_state=mode,
        operating_mode_assessment=None,
        ownership=SourceOwnership.CONTROLEL_OWNED,
        capabilities=SourceCapabilities(frozenset({SourceCapability.WATER_TARGET, SourceCapability.ENABLE_DISABLE})),
        reported=reported,
        last_successful_command=None,
        reconciliation=reconciliation,
        recovery=recovery,
        source_control_state=None,
        now=NOW + timedelta(minutes=1),
    )
    payload = source_resilience_diagnostics_to_dict(snapshot)

    assert snapshot.schema_version == 1
    assert payload["operating_mode"] == "manual_recovery_heat"
    assert payload["reported_source_state"] == "disabled"
    assert payload["last_successful_command"] is None
    assert payload["transition_history"] == "unknown"
    assert payload["manual_recovery_remaining_seconds"] == 7140.0
    assert payload["source_capabilities"] == ["enable_disable", "water_target"]
    assert all(isinstance(key, str) for key in payload)


def test_identical_projection_inputs_produce_identical_snapshot() -> None:
    mode_policy = OperatingModePolicy()
    mode = mode_policy.initial_state(now=NOW)
    arguments = dict(
        operating_mode_state=mode,
        operating_mode_assessment=None,
        ownership=SourceOwnership.EXTERNAL,
        capabilities=SourceCapabilities(),
        reported=None,
        last_successful_command=None,
        reconciliation=None,
        recovery=None,
        source_control_state=None,
        now=NOW,
    )

    first = SourceResilienceDiagnosticsProjector().project(**arguments)
    second = SourceResilienceDiagnosticsProjector().project(**arguments)

    assert first == second
    assert first.reported_source_state is None
    assert first.drift_detected is None

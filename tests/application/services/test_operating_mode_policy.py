from datetime import UTC, datetime, timedelta

from controlel.application.services.operating_mode_policy import (
    DEFAULT_MANUAL_RECOVERY_DURATION,
    OperatingModePolicy,
)
from controlel.application.state.operating_mode_state import OperatingModeReason
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import (
    OperatingMode,
    SafeHeatingProfile,
    SafeHeatingTemperatureEvidence,
)
from controlel.domain.source_control import SourceCapabilities, SourceCapability
from controlel.domain.value_objects.sensor_id import SensorId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
PREFERRED = SensorId("living_room")
FALLBACK = SensorId("hall")
PROFILE = SafeHeatingProfile(
    room_target_temperature=19.0,
    turn_on_differential=1.0,
    turn_off_differential=1.0,
    preferred_sensor_id=PREFERRED,
    fallback_sensor_id=FALLBACK,
    water_target_temperature=45.0,
)


def _valid(sensor_id: SensorId, value: float) -> SafeHeatingTemperatureEvidence:
    return SafeHeatingTemperatureEvidence(
        sensor_id=sensor_id,
        value=value,
        quality=ObservationQuality.VALID,
        observed_at=NOW,
    )


def test_normal_mode_preserves_normal_source_action() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    assessment = policy.evaluate(
        current_state=policy.initial_state(now=NOW),
        normal_action=HeatingAction.ENABLE_HEATING,
        preferred_evidence=None,
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=NOW,
    )

    assert assessment.desired_source_command is HeatingAction.ENABLE_HEATING
    assert assessment.safety_command is False
    assert assessment.water_target_intent is None


def test_safe_heating_uses_deterministic_room_hysteresis_with_enable_disable_only() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    safe = policy.activate(
        policy.initial_state(now=NOW),
        mode=OperatingMode.SAFE_HEATING,
        now=NOW,
    )
    cold = policy.evaluate(
        current_state=safe,
        normal_action=HeatingAction.DISABLE_HEATING,
        preferred_evidence=_valid(PREFERRED, 17.5),
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=NOW,
    )
    deadband = policy.evaluate(
        current_state=cold.state,
        normal_action=HeatingAction.DISABLE_HEATING,
        preferred_evidence=_valid(PREFERRED, 19.0),
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=NOW + timedelta(seconds=1),
    )

    assert cold.desired_source_command is HeatingAction.ENABLE_HEATING
    assert deadband.desired_source_command is HeatingAction.ENABLE_HEATING
    assert cold.water_target_intent is None


def test_safe_heating_water_target_is_intent_only_and_capability_gated() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    safe = policy.activate(policy.initial_state(now=NOW), mode=OperatingMode.SAFE_HEATING, now=NOW)
    assessment = policy.evaluate(
        current_state=safe,
        normal_action=HeatingAction.DISABLE_HEATING,
        preferred_evidence=_valid(PREFERRED, 17.0),
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(
            frozenset({SourceCapability.ENABLE_DISABLE, SourceCapability.WATER_TARGET})
        ),
        now=NOW,
    )

    assert assessment.water_target_intent is not None
    assert assessment.water_target_intent.target_temperature == 45.0
    assert assessment.water_target_intent.requested_at == NOW


def test_safe_heating_uses_fallback_or_becomes_explicitly_degraded() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    safe = policy.activate(policy.initial_state(now=NOW), mode=OperatingMode.SAFE_HEATING, now=NOW)
    unknown = SafeHeatingTemperatureEvidence(
        sensor_id=PREFERRED,
        value=None,
        quality=ObservationQuality.UNKNOWN,
        observed_at=NOW,
    )
    fallback = policy.evaluate(
        current_state=safe,
        normal_action=HeatingAction.DISABLE_HEATING,
        preferred_evidence=unknown,
        fallback_evidence=_valid(FALLBACK, 17.0),
        source_capabilities=SourceCapabilities(),
        now=NOW,
    )
    degraded = policy.evaluate(
        current_state=safe,
        normal_action=HeatingAction.ENABLE_HEATING,
        preferred_evidence=unknown,
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=NOW,
    )

    assert fallback.desired_source_command is HeatingAction.ENABLE_HEATING
    assert fallback.reason is OperatingModeReason.SAFE_HEATING_FALLBACK_EVIDENCE
    assert degraded.desired_source_command is None
    assert degraded.reason is OperatingModeReason.SAFE_HEATING_EVIDENCE_UNAVAILABLE
    assert degraded.degraded is True


def test_emergency_off_is_an_explicit_safety_disable() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    emergency = policy.activate(
        policy.initial_state(now=NOW),
        mode=OperatingMode.EMERGENCY_OFF,
        now=NOW,
    )
    assessment = policy.evaluate(
        current_state=emergency,
        normal_action=HeatingAction.ENABLE_HEATING,
        preferred_evidence=None,
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=NOW,
    )

    assert assessment.desired_source_command is HeatingAction.DISABLE_HEATING
    assert assessment.safety_command is True
    assert assessment.reason is OperatingModeReason.EMERGENCY_OFF_ACTIVE


def test_manual_recovery_defaults_to_two_hours_extends_and_expires_to_normal() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    initial = policy.initial_state(now=NOW)
    manual = policy.activate(initial, mode=OperatingMode.MANUAL_RECOVERY_HEAT, now=NOW)
    extended = policy.activate(
        manual,
        mode=OperatingMode.MANUAL_RECOVERY_HEAT,
        now=NOW + timedelta(hours=1),
    )

    assert manual.manual_recovery_deadline == NOW + DEFAULT_MANUAL_RECOVERY_DURATION
    assert extended.manual_recovery_deadline == NOW + timedelta(hours=3)

    expired = policy.evaluate(
        current_state=extended,
        normal_action=HeatingAction.DISABLE_HEATING,
        preferred_evidence=None,
        fallback_evidence=None,
        source_capabilities=SourceCapabilities(),
        now=extended.manual_recovery_deadline,
    )
    assert expired.state.mode is OperatingMode.NORMAL
    assert expired.reason is OperatingModeReason.MANUAL_RECOVERY_EXPIRED
    assert expired.desired_source_command is HeatingAction.DISABLE_HEATING


def test_reload_cancels_manual_recovery_without_recreating_deadline() -> None:
    policy = OperatingModePolicy(safe_heating_profile=PROFILE)
    manual = policy.activate(
        policy.initial_state(now=NOW),
        mode=OperatingMode.MANUAL_RECOVERY_HEAT,
        now=NOW,
    )
    cancelled = policy.cancel_for_reload(manual, now=NOW + timedelta(minutes=5))

    assert cancelled.mode is OperatingMode.NORMAL
    assert cancelled.reason is OperatingModeReason.MANUAL_RECOVERY_CANCELLED_RELOAD
    assert cancelled.manual_recovery_deadline is None

    reconstructed = policy.recovered_after_manual_reload(now=NOW + timedelta(minutes=5))
    assert reconstructed == cancelled

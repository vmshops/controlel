"""Deterministic source intent for explicit operating modes."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from controlel.application.state.operating_mode_state import (
    OperatingModeReason,
    OperatingModeState,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import (
    OperatingMode,
    SafeHeatingProfile,
    SafeHeatingTemperatureEvidence,
    WaterTargetIntent,
)
from controlel.domain.source_control import SourceCapabilities, SourceCapability

DEFAULT_MANUAL_RECOVERY_DURATION = timedelta(hours=2)


@dataclass(frozen=True)
class OperatingModeAssessment:
    state: OperatingModeState
    desired_source_command: HeatingAction | None
    safety_command: bool
    reason: OperatingModeReason
    degraded: bool
    selected_evidence: SafeHeatingTemperatureEvidence | None
    water_target_intent: WaterTargetIntent | None
    next_reevaluation_at: datetime | None


class OperatingModePolicy:
    """Apply explicit mode overrides without dispatching source commands."""

    def __init__(
        self,
        *,
        safe_heating_profile: SafeHeatingProfile | None = None,
        manual_recovery_duration: timedelta = DEFAULT_MANUAL_RECOVERY_DURATION,
    ) -> None:
        if not isinstance(manual_recovery_duration, timedelta):
            raise TypeError("manual_recovery_duration must be a timedelta")
        if manual_recovery_duration <= timedelta(0):
            raise ValueError("manual_recovery_duration must be positive")
        self.safe_heating_profile = safe_heating_profile
        self.manual_recovery_duration = manual_recovery_duration

    def initial_state(self, *, now: datetime) -> OperatingModeState:
        _aware(now)
        return OperatingModeState(
            mode=OperatingMode.NORMAL,
            reason=OperatingModeReason.NORMAL_OPERATION,
            activated_at=now,
            manual_recovery_deadline=None,
            safe_heating_requires_heat=None,
            last_evaluated_at=now,
        )

    def activate(
        self,
        current_state: OperatingModeState,
        *,
        mode: OperatingMode,
        now: datetime,
        manual_recovery_duration: timedelta | None = None,
    ) -> OperatingModeState:
        _aware(now)
        if now < current_state.last_evaluated_at:
            raise ValueError("operating-mode activation time must not regress")
        if not isinstance(mode, OperatingMode):
            raise TypeError("mode must be an OperatingMode")
        duration = manual_recovery_duration or self.manual_recovery_duration
        if duration <= timedelta(0):
            raise ValueError("manual recovery duration must be positive")
        reason = {
            OperatingMode.NORMAL: OperatingModeReason.NORMAL_OPERATION,
            OperatingMode.SAFE_HEATING: OperatingModeReason.USER_SELECTED,
            OperatingMode.EMERGENCY_OFF: OperatingModeReason.EMERGENCY_OFF_ACTIVE,
            OperatingMode.MANUAL_RECOVERY_HEAT: OperatingModeReason.MANUAL_RECOVERY_ACTIVE,
        }[mode]
        return OperatingModeState(
            mode=mode,
            reason=reason,
            activated_at=now,
            manual_recovery_deadline=(now + duration if mode is OperatingMode.MANUAL_RECOVERY_HEAT else None),
            safe_heating_requires_heat=(
                current_state.safe_heating_requires_heat if mode is OperatingMode.SAFE_HEATING else None
            ),
            last_evaluated_at=now,
        )

    def cancel_for_reload(
        self,
        current_state: OperatingModeState,
        *,
        now: datetime,
    ) -> OperatingModeState:
        """Cancel an in-memory manual deadline instead of reconstructing it."""

        _aware(now)
        if current_state.mode is not OperatingMode.MANUAL_RECOVERY_HEAT:
            return current_state
        return OperatingModeState(
            mode=OperatingMode.NORMAL,
            reason=OperatingModeReason.MANUAL_RECOVERY_CANCELLED_RELOAD,
            activated_at=now,
            manual_recovery_deadline=None,
            safe_heating_requires_heat=None,
            last_evaluated_at=now,
        )

    def recovered_after_manual_reload(self, *, now: datetime) -> OperatingModeState:
        """Represent cancellation in a reconstructed runtime without restoring a timer."""

        _aware(now)
        return OperatingModeState(
            mode=OperatingMode.NORMAL,
            reason=OperatingModeReason.MANUAL_RECOVERY_CANCELLED_RELOAD,
            activated_at=now,
            manual_recovery_deadline=None,
            safe_heating_requires_heat=None,
            last_evaluated_at=now,
        )

    def evaluate(
        self,
        *,
        current_state: OperatingModeState,
        normal_action: HeatingAction | None,
        preferred_evidence: SafeHeatingTemperatureEvidence | None,
        fallback_evidence: SafeHeatingTemperatureEvidence | None,
        source_capabilities: SourceCapabilities,
        now: datetime,
    ) -> OperatingModeAssessment:
        _aware(now)
        if now < current_state.last_evaluated_at:
            raise ValueError("operating-mode evaluation time must not regress")
        mode = current_state.mode
        if mode is OperatingMode.MANUAL_RECOVERY_HEAT:
            deadline = current_state.manual_recovery_deadline
            if deadline is None:
                raise RuntimeError("manual recovery state requires a deadline")
            if now < deadline:
                state = replace(
                    current_state,
                    reason=OperatingModeReason.MANUAL_RECOVERY_ACTIVE,
                    last_evaluated_at=now,
                )
                return _assessment(
                    state,
                    HeatingAction.ENABLE_HEATING,
                    OperatingModeReason.MANUAL_RECOVERY_ACTIVE,
                    next_reevaluation_at=deadline,
                )
            current_state = OperatingModeState(
                mode=OperatingMode.NORMAL,
                reason=OperatingModeReason.MANUAL_RECOVERY_EXPIRED,
                activated_at=now,
                manual_recovery_deadline=None,
                safe_heating_requires_heat=None,
                last_evaluated_at=now,
            )
            return _assessment(
                current_state,
                normal_action or HeatingAction.DISABLE_HEATING,
                OperatingModeReason.MANUAL_RECOVERY_EXPIRED,
                safety_command=normal_action is None,
            )
        if mode is OperatingMode.EMERGENCY_OFF:
            state = replace(current_state, last_evaluated_at=now)
            return _assessment(
                state,
                HeatingAction.DISABLE_HEATING,
                OperatingModeReason.EMERGENCY_OFF_ACTIVE,
                safety_command=True,
            )
        if mode is OperatingMode.NORMAL:
            state = replace(current_state, last_evaluated_at=now)
            return _assessment(state, normal_action, state.reason)

        profile = self.safe_heating_profile
        if profile is None:
            state = replace(
                current_state,
                reason=OperatingModeReason.SAFE_HEATING_EVIDENCE_UNAVAILABLE,
                safe_heating_requires_heat=None,
                last_evaluated_at=now,
            )
            return _assessment(
                state,
                None,
                state.reason,
                degraded=True,
            )
        evidence, reason = _select_evidence(profile, preferred_evidence, fallback_evidence)
        if evidence is None:
            state = replace(
                current_state,
                reason=OperatingModeReason.SAFE_HEATING_EVIDENCE_UNAVAILABLE,
                safe_heating_requires_heat=None,
                last_evaluated_at=now,
            )
            return _assessment(state, None, state.reason, degraded=True)

        value = float(evidence.value)
        if value < profile.room_target_temperature - profile.turn_on_differential:
            requires_heat = True
        elif value > profile.room_target_temperature + profile.turn_off_differential:
            requires_heat = False
        else:
            requires_heat = (
                current_state.safe_heating_requires_heat
                if current_state.safe_heating_requires_heat is not None
                else value < profile.room_target_temperature
            )
        state = replace(
            current_state,
            reason=reason,
            safe_heating_requires_heat=requires_heat,
            last_evaluated_at=now,
        )
        water_intent = (
            WaterTargetIntent(profile.water_target_temperature, now)
            if requires_heat
            and profile.water_target_temperature is not None
            and source_capabilities.supports(SourceCapability.WATER_TARGET)
            else None
        )
        return _assessment(
            state,
            HeatingAction.ENABLE_HEATING if requires_heat else HeatingAction.DISABLE_HEATING,
            reason,
            selected_evidence=evidence,
            water_target_intent=water_intent,
        )


def _select_evidence(
    profile: SafeHeatingProfile,
    preferred: SafeHeatingTemperatureEvidence | None,
    fallback: SafeHeatingTemperatureEvidence | None,
) -> tuple[SafeHeatingTemperatureEvidence | None, OperatingModeReason]:
    if (
        preferred is not None
        and preferred.sensor_id == profile.preferred_sensor_id
        and preferred.quality is ObservationQuality.VALID
        and preferred.value is not None
    ):
        return preferred, OperatingModeReason.SAFE_HEATING_PREFERRED_EVIDENCE
    if (
        fallback is not None
        and profile.fallback_sensor_id is not None
        and fallback.sensor_id == profile.fallback_sensor_id
        and fallback.quality is ObservationQuality.VALID
        and fallback.value is not None
    ):
        return fallback, OperatingModeReason.SAFE_HEATING_FALLBACK_EVIDENCE
    return None, OperatingModeReason.SAFE_HEATING_EVIDENCE_UNAVAILABLE


def _assessment(
    state: OperatingModeState,
    desired: HeatingAction | None,
    reason: OperatingModeReason,
    *,
    safety_command: bool = False,
    degraded: bool = False,
    selected_evidence: SafeHeatingTemperatureEvidence | None = None,
    water_target_intent: WaterTargetIntent | None = None,
    next_reevaluation_at: datetime | None = None,
) -> OperatingModeAssessment:
    return OperatingModeAssessment(
        state=state,
        desired_source_command=desired,
        safety_command=safety_command,
        reason=reason,
        degraded=degraded,
        selected_evidence=selected_evidence,
        water_target_intent=water_target_intent,
        next_reevaluation_at=next_reevaluation_at,
    )


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

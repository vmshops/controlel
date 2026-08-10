from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from controlel.application.services.source_control_policy import (
    SourceControlOutcome,
    SourceControlPolicy,
)
from controlel.domain.commands.heating_action import HeatingAction

START = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@dataclass
class LegacyReference:
    """Minimal frozen 0.3.0 command/timing contract used as a regression oracle."""

    minimum_on: timedelta
    minimum_off: timedelta
    last_action: HeatingAction | None = None
    last_dispatch: datetime | None = None

    def evaluate(
        self,
        action: HeatingAction,
        now: datetime,
        *,
        safety: bool,
    ) -> SourceControlOutcome:
        if self.last_action is action:
            return SourceControlOutcome.SUPPRESS_DUPLICATE
        if self.last_action is HeatingAction.ENABLE_HEATING and self.last_dispatch is not None:
            minimum_on_deadline = self.last_dispatch + self.minimum_on
            if action is HeatingAction.DISABLE_HEATING and now < minimum_on_deadline and not safety:
                return SourceControlOutcome.DEFER
        if self.last_action is HeatingAction.DISABLE_HEATING and self.last_dispatch is not None:
            minimum_off_deadline = self.last_dispatch + self.minimum_off
            if action is HeatingAction.ENABLE_HEATING and now < minimum_off_deadline:
                return SourceControlOutcome.DEFER
        return SourceControlOutcome.DISPATCH

    def record(self, action: HeatingAction, now: datetime) -> None:
        self.last_action = action
        self.last_dispatch = now


def test_milestone_28_observability_refactor_is_command_and_timing_equivalent_to_0_3_0() -> None:
    minimum_on = timedelta(minutes=10)
    minimum_off = timedelta(minutes=5)
    reference = LegacyReference(minimum_on=minimum_on, minimum_off=minimum_off)
    candidate = SourceControlPolicy(
        minimum_on_time=minimum_on,
        minimum_off_time=minimum_off,
    )
    state = None
    corpus = (
        (0, HeatingAction.ENABLE_HEATING, False),
        (1, HeatingAction.DISABLE_HEATING, False),
        (2, HeatingAction.ENABLE_HEATING, False),
        (3, HeatingAction.DISABLE_HEATING, False),
        (4, HeatingAction.DISABLE_HEATING, True),
        (5, HeatingAction.ENABLE_HEATING, False),
        (6, HeatingAction.ENABLE_HEATING, True),
        (9, HeatingAction.ENABLE_HEATING, False),
        (10, HeatingAction.ENABLE_HEATING, False),
        (11, HeatingAction.DISABLE_HEATING, False),
        (12, HeatingAction.DISABLE_HEATING, True),
    )
    reference_dispatches: list[tuple[datetime, HeatingAction]] = []
    candidate_dispatches: list[tuple[datetime, HeatingAction]] = []
    reference_outcomes: list[SourceControlOutcome] = []
    candidate_outcomes: list[SourceControlOutcome] = []

    for offset, action, safety in corpus:
        now = START + timedelta(minutes=offset)
        reference_outcome = reference.evaluate(action, now, safety=safety)
        assessment = candidate.evaluate(
            desired_command=action,
            now=now,
            current_state=state,
            safety_command=safety,
            lockout_expiry_reevaluation=(state is not None and state.deferred_deadline == now),
        )
        state = assessment.state
        reference_outcomes.append(reference_outcome)
        candidate_outcomes.append(assessment.outcome)
        if reference_outcome is SourceControlOutcome.DISPATCH:
            reference.record(action, now)
            reference_dispatches.append((now, action))
        if assessment.outcome is SourceControlOutcome.DISPATCH:
            state = candidate.record_dispatched(
                assessment,
                dispatched_at=now,
                safety_command=safety,
            )
            candidate_dispatches.append((now, action))

    assert candidate_outcomes == reference_outcomes
    assert candidate_dispatches == reference_dispatches

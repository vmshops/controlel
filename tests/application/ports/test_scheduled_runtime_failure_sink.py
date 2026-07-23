from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from controlel.application.ports.scheduled_runtime_failure_sink import (
    ScheduledRuntimeFailure,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_failure_is_immutable_and_preserves_exact_exception():
    error = RuntimeError("scheduled failure")
    failure = ScheduledRuntimeFailure(
        scheduled_for=NOW,
        error=error,
    )

    assert failure.scheduled_for is NOW
    assert failure.error is error
    with pytest.raises(FrozenInstanceError):
        failure.error = RuntimeError("replacement")


def test_scheduled_for_must_be_an_aware_datetime():
    with pytest.raises(TypeError, match="datetime"):
        ScheduledRuntimeFailure(scheduled_for="later", error=RuntimeError())
    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduledRuntimeFailure(
            scheduled_for=datetime(2026, 1, 1, 12),
            error=RuntimeError(),
        )


@pytest.mark.parametrize("control_flow_error", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
def test_base_exception_control_flow_failures_are_rejected(control_flow_error):
    with pytest.raises(TypeError, match="Exception"):
        ScheduledRuntimeFailure(
            scheduled_for=NOW,
            error=control_flow_error,
        )

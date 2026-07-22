from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest

from controlel.application.services.measurement_timestamp_validator import (
    MeasurementTimestampValidator,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


class FixedClock:
    def __init__(self, current_time: datetime = NOW):
        self.current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current_time


def create_measurement(timestamp: datetime) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(20),
        timestamp=timestamp,
    )


@pytest.mark.parametrize("max_future_skew", [timedelta(0), timedelta(minutes=1)])
def test_accepts_zero_and_positive_future_skew(max_future_skew):
    validator = MeasurementTimestampValidator(FixedClock(), max_future_skew)

    assert validator.max_future_skew == max_future_skew


def test_max_future_skew_is_required_with_no_default():
    parameter = signature(MeasurementTimestampValidator).parameters["max_future_skew"]

    assert parameter.default is parameter.empty


def test_rejects_negative_future_skew():
    with pytest.raises(ValueError, match="max_future_skew must not be negative"):
        MeasurementTimestampValidator(FixedClock(), timedelta(microseconds=-1))


def test_rejects_non_timedelta_future_skew():
    with pytest.raises(TypeError, match="max_future_skew must be a timedelta"):
        MeasurementTimestampValidator(FixedClock(), 60)


@pytest.mark.parametrize(
    ("timestamp", "max_future_skew"),
    [
        (NOW, timedelta(0)),
        (NOW + timedelta(seconds=30), timedelta(minutes=1)),
        (NOW + timedelta(minutes=1), timedelta(minutes=1)),
    ],
    ids=["equal-to-now", "within-tolerance", "future-boundary"],
)
def test_admits_timestamp_at_or_within_future_boundary(timestamp, max_future_skew):
    validator = MeasurementTimestampValidator(FixedClock(), max_future_skew)

    assert validator.is_admissible(create_measurement(timestamp)) is True


def test_rejects_timestamp_one_microsecond_beyond_future_boundary():
    validator = MeasurementTimestampValidator(FixedClock(), timedelta(minutes=1))
    measurement = create_measurement(NOW + timedelta(minutes=1, microseconds=1))

    assert validator.is_admissible(measurement) is False


def test_reads_clock_exactly_once_per_admission_check():
    clock = FixedClock()
    validator = MeasurementTimestampValidator(clock, timedelta(0))

    validator.is_admissible(create_measurement(NOW))

    assert clock.calls == 1


def test_naive_clock_time_raises_clear_value_error():
    validator = MeasurementTimestampValidator(
        FixedClock(datetime(2026, 1, 1, 12)),
        timedelta(0),
    )

    with pytest.raises(
        ValueError,
        match=r"Clock\.now\(\) must return a timezone-aware datetime",
    ):
        validator.is_admissible(create_measurement(NOW))


def test_admission_does_not_mutate_measurement():
    measurement = create_measurement(NOW + timedelta(seconds=30))
    before = measurement.model_dump()
    validator = MeasurementTimestampValidator(FixedClock(), timedelta(minutes=1))

    validator.is_admissible(measurement)

    assert measurement.model_dump() == before

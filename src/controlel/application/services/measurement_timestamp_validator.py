from datetime import timedelta

from controlel.application.time.clock import Clock
from controlel.domain.measurements.measurement import Measurement


class MeasurementTimestampValidator:
    def __init__(
        self,
        clock: Clock,
        max_future_skew: timedelta,
    ):
        if not isinstance(max_future_skew, timedelta):
            raise TypeError("max_future_skew must be a timedelta")
        if max_future_skew < timedelta(0):
            raise ValueError("max_future_skew must not be negative")

        self.clock = clock
        self.max_future_skew = max_future_skew

    def is_admissible(self, measurement: Measurement) -> bool:
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Clock.now() must return a timezone-aware datetime")

        future_boundary = now + self.max_future_skew
        return measurement.timestamp <= future_boundary

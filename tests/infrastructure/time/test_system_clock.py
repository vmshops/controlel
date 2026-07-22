from datetime import UTC

from controlel.infrastructure.time.system_clock import SystemClock


def test_system_clock_returns_timezone_aware_utc_datetime():
    current_time = SystemClock().now()

    assert current_time.tzinfo is not None
    assert current_time.utcoffset() is not None
    assert current_time.tzinfo == UTC

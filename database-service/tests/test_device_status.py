from datetime import datetime, timedelta, timezone

from app.services.device_status import device_status


def test_device_status_classifies_missing_recent_stale_and_future_timestamps():
    now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    assert device_status(None, now) == "unknown"
    assert device_status(now - timedelta(seconds=180), now) == "online"
    assert device_status(now - timedelta(seconds=181), now) == "offline"
    assert device_status(now + timedelta(seconds=1), now) == "online"


def test_device_status_handles_naive_timestamp_as_utc():
    now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    assert device_status(datetime(2026, 9, 9, 11, 59, 59), now) == "online"

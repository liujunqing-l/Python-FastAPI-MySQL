from datetime import datetime, timezone
from typing import Optional


def _as_utc(value: datetime) -> datetime:
    """Normalize aware timestamps and treat legacy naive values as UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def device_status(
    last_seen_at: Optional[datetime],
    now: datetime,
    timeout_seconds: int = 180,
) -> str:
    """Return online/offline/unknown from a device's last-seen timestamp."""
    if last_seen_at is None:
        return "unknown"
    age_seconds = (_as_utc(now) - _as_utc(last_seen_at)).total_seconds()
    return "online" if age_seconds <= timeout_seconds else "offline"

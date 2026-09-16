from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Device,
    DeviceAlarm,
    DeviceConfigSnapshot,
    LocationRecord,
    SleepRecord,
)
from app.schemas import (
    AlarmEvent,
    ConfigSnapshotEvent,
    LocationEvent,
    SleepEvent,
)


EVENT_TABLES = {
    "device_alarms",
    "location_records",
    "sleep_records",
    "device_config_snapshots",
}


def _sqlite_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _device(session: Session) -> Device:
    device = Device(imei="861431071299189")
    session.add(device)
    session.flush()
    return device


def _common(model, device: Device, **values):
    return model(
        device_id=device.id,
        event_hash="a" * 64,
        collected_date=date(2026, 9, 9),
        imei=device.imei,
        message_id=values.pop("message_id"),
        collected_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
        raw_hex=values.pop("raw_hex", "AA"),
        **values,
    )


def test_event_metadata_defines_expected_tables_columns_constraints_and_indexes():
    assert EVENT_TABLES <= set(Base.metadata.tables)

    alarm = Base.metadata.tables["device_alarms"]
    location = Base.metadata.tables["location_records"]
    sleep = Base.metadata.tables["sleep_records"]
    config = Base.metadata.tables["device_config_snapshots"]

    common_columns = {
        "id",
        "device_id",
        "event_hash",
        "collected_date",
        "imei",
        "message_id",
        "collected_at",
        "received_at",
        "raw_hex",
        "raw_archive_id",
    }
    for table in (alarm, location, sleep, config):
        assert common_columns <= set(table.c.keys())
        assert any(
            constraint.name and constraint.name.startswith("uq_")
            and set(constraint.columns.keys()) == {"event_hash", "collected_date"}
            for constraint in table.constraints
        )
        assert any(
            set(index.columns.keys()) == {"imei", "collected_at"}
            for index in table.indexes
        )

    assert {"alarm_codes", "status", "sensor_values"} <= set(alarm.c.keys())
    assert {"source", "latitude", "wifi_access_points", "resolution_status"} <= set(
        location.c.keys()
    )
    assert {"start_at", "end_at", "duration_minutes", "sleep_stage"} <= set(
        sleep.c.keys()
    )
    assert {
        "location_modified",
        "location_interval_minutes",
        "health_modified",
        "health_interval_minutes",
        "timestamp_source",
    } <= set(config.c.keys())
    assert any(
        set(index.columns.keys()) == {"status", "collected_at"}
        for index in alarm.indexes
    )


def test_event_models_create_on_sqlite_and_allow_nullable_protocol_details():
    engine = _sqlite_engine()
    with Session(engine) as session:
        device = _device(session)
        alarm = _common(DeviceAlarm, device, message_id=2)
        location = _common(LocationRecord, device, message_id=164, source="wifi")
        sleep = _common(SleepRecord, device, message_id=197)
        config = _common(DeviceConfigSnapshot, device, message_id=233)
        session.add_all([alarm, location, sleep, config])
        session.commit()

        assert alarm.alarm_codes == []
        assert alarm.raw_archive_id is None
        assert location.latitude is None
        assert location.longitude is None
        assert location.wifi_access_points is None
        assert sleep.start_at is None
        assert sleep.end_at is None
        assert config.location_interval_minutes is None
        assert config.timestamp_source == "received_at"


@pytest.mark.parametrize(
    ("model", "message_id", "extra"),
    [
        (DeviceAlarm, 2, {}),
        (LocationRecord, 3, {"source": "gps"}),
        (SleepRecord, 197, {}),
        (DeviceConfigSnapshot, 233, {}),
    ],
)
def test_event_hash_and_collected_date_are_unique(model, message_id, extra):
    engine = _sqlite_engine()
    with Session(engine) as session:
        device = _device(session)
        first = _common(model, device, message_id=message_id, **extra)
        duplicate = _common(model, device, message_id=message_id, **extra)
        session.add_all([first, duplicate])
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        (
            {
                "start_at": datetime(2026, 9, 9, 2, tzinfo=timezone.utc),
                "end_at": datetime(2026, 9, 9, 1, tzinfo=timezone.utc),
            },
            "end_at",
        ),
        ({"duration_minutes": -1}, "duration_minutes"),
    ],
)
def test_sleep_database_constraints_reject_invalid_intervals(values, constraint):
    engine = _sqlite_engine()
    with Session(engine) as session:
        device = _device(session)
        session.add(_common(SleepRecord, device, message_id=197, **values))
        with pytest.raises(IntegrityError, match=constraint):
            session.commit()


def test_event_schemas_enforce_protocol_message_ids_and_preserve_nulls():
    common = {
        "imei": "861431071299189",
        "collected_at": "2026-09-09T00:00:00Z",
        "raw_hex": "AA",
    }
    alarm = AlarmEvent(message_id=2, event_type="alarm", **common)
    location = LocationEvent(message_id=164, event_type="location", source="wifi", **common)
    sleep = SleepEvent(message_id=197, event_type="sleep", **common)
    config = ConfigSnapshotEvent(
        message_id=233, event_type="config_snapshot", **common
    )

    assert alarm.alarm_codes == []
    assert location.latitude is None and location.longitude is None
    assert sleep.start_at is None and sleep.end_at is None
    assert config.timestamp_source == "received_at"

    with pytest.raises(ValueError):
        ConfigSnapshotEvent(message_id=232, event_type="config_snapshot", **common)

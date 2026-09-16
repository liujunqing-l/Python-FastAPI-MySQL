from sqlalchemy import inspect

from app.models import Base


def test_health_storage_model_defines_expected_tables_and_indexes():
    assert set(Base.metadata.tables) == {
        "devices",
        "device_alarms",
        "location_records",
        "sleep_records",
        "device_config_snapshots",
        "health_records",
        "heartbeat_records",
        "ingestion_errors",
        "raw_archives",
        "device_commands",
        "roles",
        "users",
        "user_device_bindings",
        "alarm_rules",
    }

    devices = Base.metadata.tables["devices"]
    health_records = Base.metadata.tables["health_records"]

    assert any(constraint.name == "uq_devices_imei" for constraint in devices.constraints)
    assert "event_hash" in health_records.c
    assert any(
        set(index.columns.keys()) == {"imei", "collected_at"}
        for index in health_records.indexes
    )

    heartbeat_records = Base.metadata.tables["heartbeat_records"]
    assert "event_hash" in heartbeat_records.c
    assert "battery_raw_value" in heartbeat_records.c
    assert "signal_raw_value" in heartbeat_records.c
    assert "steps_type" in heartbeat_records.c

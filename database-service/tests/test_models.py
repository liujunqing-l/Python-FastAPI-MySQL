from sqlalchemy import inspect

from app.models import Base


def test_health_storage_model_defines_expected_tables_and_indexes():
    assert set(Base.metadata.tables) == {
        "devices",
        "health_records",
        "ingestion_errors",
        "raw_archives",
    }

    devices = Base.metadata.tables["devices"]
    health_records = Base.metadata.tables["health_records"]

    assert any(constraint.name == "uq_devices_imei" for constraint in devices.constraints)
    assert "event_hash" in health_records.c
    assert any(
        set(index.columns.keys()) == {"imei", "collected_at"}
        for index in health_records.indexes
    )

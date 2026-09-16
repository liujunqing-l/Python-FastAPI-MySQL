"""TDD coverage for the unified protocol-event ingestion endpoint.

These tests intentionally exercise the parser-facing forms (hexadecimal and
decimal message IDs) rather than only the database's canonical integers.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    Base,
    DeviceAlarm,
    DeviceConfigSnapshot,
    LocationRecord,
    SleepRecord,
)
from app.schemas import AlarmEvent, ConfigSnapshotEvent, LocationEvent, SleepEvent


IMEI = "861431071299189"


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_event_schemas_normalize_parser_message_ids_timestamps_and_raw_hex():
    common = {
        "imei": IMEI,
        "collected_at": "2026-09-09T12:00:00+08:00",
        "raw_hex": "aa02bb",
    }

    alarm = AlarmEvent(message_id="0x02", event_type="alarm", **common)
    location = LocationEvent(
        message_id="A4", event_type="location", source="wifi", **common
    )
    sleep = SleepEvent(message_id="197", event_type="sleep", **common)
    config = ConfigSnapshotEvent(
        message_id="0xE9", event_type="config_snapshot", **common
    )

    assert alarm.message_id == 2
    assert location.message_id == 164
    assert sleep.message_id == 197
    assert config.message_id == 233
    assert alarm.collected_at.tzinfo == timezone.utc
    assert alarm.collected_at.isoformat() == "2026-09-09T04:00:00+00:00"
    assert alarm.raw_hex == "AA02BB"

    # Digit-only two-character IDs can be emitted as a protocol hex byte by
    # parsers (``16`` = 0x16, ``21`` = 0x21).  The event discriminator resolves
    # those otherwise ambiguous strings without weakening decimal support.
    assert AlarmEvent(message_id="16", event_type="alarm", **common).message_id == 22
    assert AlarmEvent(message_id="21", event_type="alarm", **common).message_id == 33
    assert LocationEvent(
        message_id="21", event_type="location", source="lbs", **common
    ).message_id == 21


@pytest.mark.parametrize(
    ("payload", "table", "event_type", "message_id"),
    [
        (
            {
                "imei": IMEI,
                "message_id": "02",
                "event_type": "alarm",
                "collected_at": "2026-09-09T04:00:00Z",
                "alarm_mask": 4,
                "raw_hex": "AA02BB",
            },
            DeviceAlarm,
            "alarm",
            2,
        ),
        (
            {
                "imei": IMEI,
                "message_id": "0xA4",
                "event_type": "location",
                "collected_at": "2026-09-09T04:01:00Z",
                "source": "wifi",
                "wifi_access_points": [{"mac": "001122334455", "rssi": -50}],
                "raw_hex": "aaA4bb",
            },
            LocationRecord,
            "location",
            164,
        ),
        (
            {
                "imei": IMEI,
                "message_id": "C5",
                "event_type": "sleep",
                "collected_at": "2026-09-09T04:02:00Z",
                "duration_minutes": 30,
                "raw_hex": "AAC5BB",
            },
            SleepRecord,
            "sleep",
            197,
        ),
        (
            {
                "imei": IMEI,
                "message_id": 233,
                "event_type": "config_snapshot",
                "collected_at": "2026-09-09T04:03:00+08:00",
                "health_interval_minutes": 2,
                "raw_hex": "AAE9BB",
            },
            DeviceConfigSnapshot,
            "config_snapshot",
            233,
        ),
    ],
)
def test_events_endpoint_persists_each_event_type(
    tmp_path, monkeypatch, payload, table, event_type, message_id
):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "test-token")
    monkeypatch.setattr("app.api.ingest.settings.raw_spool_dir", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=payload,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "created"
        assert body["duplicate"] is False
        assert body["event_type"] == event_type
        assert body["message_id"] == message_id
        assert body["record_id"] is not None
        assert len(body["event_hash"]) == 64

        with Session(engine) as db:
            row = db.scalar(select(table))
            assert row is not None
            assert row.message_id == message_id
            assert row.raw_hex == payload["raw_hex"].upper()
            assert row.imei == IMEI
            # SQLite (the unit-test dialect) drops the timezone marker from
            # DateTime(timezone=True); PostgreSQL retains the UTC offset.  In
            # either case the stored clock value is the normalized UTC value.
            expected_collected = datetime.fromisoformat(
                payload["collected_at"].replace("Z", "+00:00")
            ).astimezone(timezone.utc).replace(tzinfo=None)
            assert row.collected_at == expected_collected
            if table is LocationRecord:
                assert row.latitude is None
                assert row.longitude is None
            if table is DeviceAlarm:
                assert row.alarm_codes == []

        lines = list(tmp_path.rglob("*.jsonl"))
        assert len(lines) == 1
        assert len(lines[0].read_text(encoding="utf-8").splitlines()) == 1
    finally:
        app.dependency_overrides.clear()


def test_duplicate_event_returns_200_and_does_not_append_spool_line(tmp_path, monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)
    payload = {
        "imei": IMEI,
        "message_id": "0x15",
        "event_type": "location",
        "collected_at": "2026-09-09T04:05:00Z",
        "source": "lbs",
        "latitude": 45.75,
        "longitude": 126.64,
        "raw_hex": "AA15BB",
    }

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "test-token")
    monkeypatch.setattr("app.api.ingest.settings.raw_spool_dir", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        first = client.post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=payload,
        )
        second = client.post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=payload,
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 200, second.text
        assert second.json()["duplicate"] is True
        assert second.json()["event_hash"] == first.json()["event_hash"]
        with Session(engine) as db:
            assert db.query(LocationRecord).count() == 1
        spool = next(tmp_path.rglob("*.jsonl"))
        assert len(spool.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "imei": IMEI,
            "message_id": "0x99",
            "event_type": "alarm",
            "collected_at": "2026-09-09T04:00:00Z",
            "raw_hex": "AA99BB",
        },
        {
            "imei": IMEI,
            "message_id": "0x02",
            "event_type": "location",
            "collected_at": "2026-09-09T04:00:00Z",
            "source": "gps",
            "raw_hex": "AA02BB",
        },
        {
            "imei": IMEI,
            "message_id": "0x02",
            "event_type": "alarm",
            "collected_at": "2026-09-09T04:00:00Z",
            "raw_hex": "AA02BB",
            "unexpected": "must be rejected",
        },
    ],
)
def test_events_endpoint_rejects_unknown_mismatch_and_extra_fields(
    tmp_path, monkeypatch, payload
):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "test-token")
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=payload,
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_events_endpoint_requires_internal_token(tmp_path, monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "test-token")
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/ingest/events",
            json={
                "imei": IMEI,
                "message_id": "0xA4",
                "event_type": "location",
                "source": "wifi",
                "collected_at": "2026-09-09T04:00:00Z",
                "raw_hex": "AAA4BB",
            },
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()

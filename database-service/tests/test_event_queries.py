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
    Role,
    User,
)
from app.services.auth import get_current_user, hash_password
from app.services.ingestion import ingest_event_record, parse_event_payload


IMEI = "861431071299189"


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_events(tmp_path):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)
    payloads = [
        {
            "imei": IMEI,
            "message_id": "0x02",
            "event_type": "alarm",
            "collected_at": "2026-09-09T04:00:00Z",
            "alarm_codes": ["fall"],
            "raw_hex": "AA0201",
        },
        {
            "imei": IMEI,
            "message_id": "0x21",
            "event_type": "alarm",
            "collected_at": "2026-09-09T04:05:00Z",
            "alarm_mask": 2,
            "raw_hex": "AA2102",
        },
        {
            "imei": IMEI,
            "message_id": "0x15",
            "event_type": "location",
            "source": "gps",
            "latitude": 45.75,
            "longitude": 126.64,
            "position_valid": True,
            "collected_at": "2026-09-09T04:10:00Z",
            "raw_hex": "AA1501",
        },
        {
            "imei": IMEI,
            "message_id": "0xA4",
            "event_type": "location",
            "source": "wifi",
            "collected_at": "2026-09-09T04:15:00Z",
            "raw_hex": "AAA401",
        },
        {
            "imei": IMEI,
            "message_id": "0xC5",
            "event_type": "sleep",
            "collected_at": "2026-09-09T04:20:00Z",
            "start_at": "2026-09-08T14:00:00Z",
            "end_at": "2026-09-08T22:00:00Z",
            "duration_minutes": 480,
            "sleep_stage": 1,
            "raw_hex": "AAC501",
        },
        {
            "imei": IMEI,
            "message_id": "0xE9",
            "event_type": "config_snapshot",
            "collected_at": "2026-09-09T04:25:00Z",
            "location_modified": True,
            "location_interval_minutes": 5,
            "health_interval_minutes": None,
            "raw_hex": "AAE901",
        },
    ]
    with session_factory() as db:
        for value in payloads:
            payload = parse_event_payload(value)
            ingest_event_record(db, payload, tmp_path)
        alarm = db.scalar(
            select(DeviceAlarm).where(DeviceAlarm.collected_at == datetime(2026, 9, 9, 4, 5))
        )
        assert alarm is not None
        alarm.status = "acknowledged"
        alarm.acknowledged_at = datetime(2026, 9, 9, 4, 30, tzinfo=timezone.utc)
        role = Role(name="admin")
        db.add(role)
        db.flush()
        admin = User(username="test-admin", password_hash=hash_password("secret"), role_id=role.id)
        db.add(admin)
        db.commit()
        admin_id = admin.id
    return engine, session_factory, admin_id


@pytest.fixture
def seeded_client(tmp_path):
    engine, session_factory, admin_id = seed_events(tmp_path)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    def override_current_user():
        with session_factory() as db:
            return db.get(User, admin_id)
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_alarm_list_filters_paginates_and_orders_by_collected_time_then_id(seeded_client):
    client, _ = seeded_client
    response = client.get(
        "/api/v1/alarms",
        params={
            "imei": IMEI,
            "status": "pending",
            "start": "2026-09-09T00:00:00Z",
            "end": "2026-09-10T00:00:00Z",
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "pending"
    assert body["items"][0]["alarm_mask"] is None
    assert body["items"][0]["alarm_codes"] == ["fall"]


def test_alarm_acknowledgement_is_idempotent_and_unknown_id_is_404(seeded_client):
    client, session_factory = seeded_client
    with session_factory() as db:
        alarm = db.scalar(
            select(DeviceAlarm).where(DeviceAlarm.status == "pending")
        )
        assert alarm is not None
        alarm_id = alarm.id

    first = client.patch(f"/api/v1/alarms/{alarm_id}/acknowledge")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "acknowledged"
    acknowledged_at = first.json()["acknowledged_at"]

    second = client.patch(f"/api/v1/alarms/{alarm_id}/acknowledge")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "acknowledged"
    assert second.json()["acknowledged_at"] == acknowledged_at

    missing = client.patch("/api/v1/alarms/999999/acknowledge")
    assert missing.status_code == 404


def test_location_latest_and_history_return_nulls_and_pagination(seeded_client):
    client, _ = seeded_client
    latest = client.get("/api/v1/locations/latest", params={"imei": IMEI})
    assert latest.status_code == 200, latest.text
    latest_body = latest.json()
    assert latest_body["source"] == "wifi"
    assert latest_body["latitude"] is None
    assert latest_body["longitude"] is None

    history = client.get(
        "/api/v1/locations/history",
        params={
            "imei": IMEI,
            "start": "2026-09-09T00:00:00Z",
            "end": "2026-09-10T00:00:00Z",
            "page": 1,
            "page_size": 1,
        },
    )
    assert history.status_code == 200, history.text
    history_body = history.json()
    assert history_body["total"] == 2
    assert history_body["items"][0]["source"] == "wifi"


def test_sleep_history_and_latest_device_config(seeded_client):
    client, _ = seeded_client
    sleep = client.get(
        "/api/v1/sleep/history",
        params={
            "imei": IMEI,
            "start": "2026-09-09T00:00:00Z",
            "end": "2026-09-10T00:00:00Z",
        },
    )
    assert sleep.status_code == 200, sleep.text
    sleep_body = sleep.json()
    assert sleep_body["total"] == 1
    assert sleep_body["items"][0]["duration_minutes"] == 480

    config = client.get(f"/api/v1/device-config/{IMEI}")
    assert config.status_code == 200, config.text
    assert config.json()["location_interval_minutes"] == 5
    assert config.json()["health_interval_minutes"] is None


def test_event_queries_require_timezone_and_non_empty_time_range(seeded_client):
    client, _ = seeded_client
    response = client.get(
        "/api/v1/locations/history",
        params={
            "imei": IMEI,
            "start": "2026-09-10T00:00:00Z",
            "end": "2026-09-09T00:00:00Z",
        },
    )
    assert response.status_code == 422

    response = client.get(
        "/api/v1/sleep/history",
        params={
            "imei": IMEI,
            "start": "2026-09-09T00:00:00",
            "end": "2026-09-10T00:00:00Z",
        },
    )
    assert response.status_code == 422


def test_latest_and_config_return_404_for_unknown_device(seeded_client):
    client, _ = seeded_client
    unknown = "861431071299180"
    assert client.get("/api/v1/locations/latest", params={"imei": unknown}).status_code == 404
    assert client.get(f"/api/v1/device-config/{unknown}").status_code == 404


def test_alarm_status_filter_rejects_unknown_status(seeded_client):
    client, _ = seeded_client
    response = client.get("/api/v1/alarms", params={"status": "closed"})
    assert response.status_code == 422

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Device, HeartbeatRecord
from app.services.ingestion import ingest_heartbeat_record
from app.schemas import HeartbeatIngestRequest


def make_payload(**overrides):
    payload = {
        "imei": "861431071299189",
        "message_id": "0xF9",
        "event_type": "heartbeat",
        "collected_at": "2026-09-09T12:00:00Z",
        "battery_type": 1,
        "battery_raw_value": 4,
        "signal_type": 0,
        "signal_raw_value": -72,
        "steps_type": 0,
        "steps_value": 1234,
        "raw_hex": "BDBDBDBDF904000048FF0000D20400000000000000",
    }
    payload.update(overrides)
    return payload


def test_heartbeat_request_keeps_raw_values_without_guessing_percent():
    parsed = HeartbeatIngestRequest.model_validate(make_payload())

    assert parsed.message_id == "0xF9"
    assert parsed.event_type == "heartbeat"
    assert parsed.battery_type == 1
    assert parsed.battery_raw_value == 4
    assert parsed.battery_percent is None
    assert parsed.signal_raw_value == -72
    assert parsed.signal_percent is None
    assert parsed.steps_type == 0
    assert parsed.steps_value == 1234


def test_heartbeat_parser_aliases_are_accepted():
    alias_payload = make_payload()
    for key in (
        "battery_raw_value",
        "signal_raw_value",
        "steps_type",
        "steps_value",
    ):
        alias_payload.pop(key, None)
    parsed = HeartbeatIngestRequest.model_validate(
        {
            **alias_payload,
            "message_id": 249,
            "type": "heartbeat",
            "battery_value": 85,
            "signal_strength": -65,
            "other_type": 1,
            "other_value": 9,
        }
    )

    assert parsed.message_id == "0xF9"
    assert parsed.battery_raw_value == 85
    assert parsed.signal_raw_value == -65
    assert parsed.steps_type == 1
    assert parsed.steps_value == 9


def test_heartbeat_ingest_is_idempotent_and_writes_device(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    payload = HeartbeatIngestRequest.model_validate(make_payload())

    monkeypatch.setattr("app.services.ingestion._next_heartbeat_id", lambda db: (_ for _ in ()).throw(AssertionError("manual IDs are forbidden")), raising=False)
    monkeypatch.setattr("app.services.ingestion._next_device_id", lambda db: (_ for _ in ()).throw(AssertionError("manual IDs are forbidden")), raising=False)
    with session_factory() as db:
        first = ingest_heartbeat_record(db, payload, tmp_path)
        second = ingest_heartbeat_record(db, payload, tmp_path)

        assert first.duplicate is False
        assert second.duplicate is True
        assert db.query(HeartbeatRecord).count() == 1
        assert first.record_id is not None
        record = db.query(HeartbeatRecord).one()
        assert record.battery_percent is None
        assert record.signal_raw_value == -72
        assert record.steps_value == 1234

    spool_files = list(tmp_path.rglob("*.jsonl"))
    assert len(spool_files) == 1
    assert len(spool_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_out_of_order_heartbeat_does_not_regress_last_seen(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    newer = HeartbeatIngestRequest.model_validate(
        make_payload(collected_at="2026-09-09T12:05:00Z", raw_hex="AA")
    )
    older = HeartbeatIngestRequest.model_validate(
        make_payload(collected_at="2026-09-09T12:00:00Z", raw_hex="BB")
    )
    with session_factory() as db:
        ingest_heartbeat_record(db, newer, tmp_path)
        ingest_heartbeat_record(db, older, tmp_path)
        device = db.query(Device).one()
        assert device.last_seen_at.isoformat().startswith("2026-09-09T12:05:00")


def test_conflicting_legacy_and_canonical_values_are_rejected():
    payload = make_payload(battery_value=5)
    try:
        HeartbeatIngestRequest.model_validate(payload)
    except ValueError as exc:
        assert "conflicting battery_raw_value and battery_value" in str(exc)
    else:
        raise AssertionError("conflicting heartbeat fields were accepted")


def test_non_percentage_battery_type_never_stores_percent(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    payload = HeartbeatIngestRequest.model_validate(
        make_payload(battery_percent=85, battery_type=3, raw_hex="CC")
    )
    with session_factory() as db:
        ingest_heartbeat_record(db, payload, tmp_path)
        assert db.query(HeartbeatRecord).one().battery_percent is None


def test_events_endpoint_accepts_f9_and_requires_token(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "test-token")
    monkeypatch.setattr("app.api.ingest.settings.raw_spool_dir", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=make_payload(),
        )
        assert response.status_code == 201
        assert response.json()["event_type"] == "heartbeat"
        assert response.json()["duplicate"] is False

        duplicate = client.post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": "test-token"},
            json=make_payload(),
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True

        unauthorized = client.post("/api/v1/ingest/events", json=make_payload())
        assert unauthorized.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_events_endpoint_rejects_non_f9_message_id(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
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
            json=make_payload(message_id="0x32"),
        )
        assert response.status_code == 422
        with session_factory() as db:
            assert db.query(HeartbeatRecord).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_events_endpoint_rejects_when_configured_token_is_empty(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.ingest.settings.internal_token", "")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/ingest/events",
            headers={"X-Internal-Token": ""},
            json=make_payload(),
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()

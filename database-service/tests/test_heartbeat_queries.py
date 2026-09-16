from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Role, User
from app.models import HeartbeatRecord
from app.schemas import HeartbeatIngestRequest
from app.services.ingestion import ingest_heartbeat_record
from app.services.auth import get_current_user, hash_password


def seed_admin(session_factory):
    with session_factory() as db:
        role = Role(name="admin")
        db.add(role)
        db.flush()
        user = User(username="test-admin", password_hash=hash_password("secret"), role_id=role.id)
        db.add(user)
        db.commit()
        return user.id


def install_admin_override(session_factory, user_id):
    def override_current_user():
        with session_factory() as db:
            return db.get(User, user_id)
    app.dependency_overrides[get_current_user] = override_current_user


def heartbeat(at: str, battery: int, signal: int):
    return HeartbeatIngestRequest.model_validate(
        {
            "imei": "861431071299189",
            "message_id": "0xF9",
            "event_type": "heartbeat",
            "collected_at": at,
            "battery_type": 2,
            "battery_raw_value": battery,
            "signal_type": 0,
            "signal_raw_value": signal,
            "steps_type": 0,
            "steps_value": 100,
            "raw_hex": f"BDBDBDBDF9{battery:04X}{abs(signal):04X}00006400000000000000",
        }
    )


def test_latest_heartbeat_endpoint_returns_latest_values(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    user_id = seed_admin(session_factory)
    with session_factory() as db:
        ingest_heartbeat_record(db, heartbeat("2026-09-09T11:59:00Z", 80, -70), tmp_path)
        ingest_heartbeat_record(db, heartbeat("2026-09-09T12:00:00Z", 85, -65), tmp_path)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    install_admin_override(session_factory, user_id)
    try:
        response = TestClient(app).get(
            "/api/v1/heartbeat/latest", params={"imei": "861431071299189"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["message_id"] == "0xF9"
        assert body["battery_type"] == 2
        assert body["battery_raw_value"] == 85
        assert body["battery_percent"] == 85
        assert body["signal_raw_value"] == -65
        assert body["signal_percent"] is None
        assert body["steps_type"] == 0
    finally:
        app.dependency_overrides.clear()


def test_heartbeat_response_adapter_accepts_orm_numeric_message_id(tmp_path):
    from app.api.ingest import _heartbeat_response

    record = HeartbeatRecord(
        id=1,
        collected_date=datetime(2026, 9, 9).date(),
        event_hash="a" * 64,
        imei="861431071299189",
        message_id=249,
        event_type="heartbeat",
        collected_at=datetime(2026, 9, 9, 12, 0),
        received_at=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
        battery_type=1,
        battery_raw_value=4,
        signal_type=0,
        signal_raw_value=-70,
        steps_type=0,
        steps_value=1,
        raw_hex="AA",
    )
    response = _heartbeat_response(record)
    assert response.message_id == "0xF9"

    # Direct validation is also supported for ORM objects whose DB column is
    # numeric; the schema validator normalizes it to the public string form.
    direct = __import__("app.schemas", fromlist=["HeartbeatRecordResponse"]).HeartbeatRecordResponse.model_validate(record)
    assert direct.message_id == "0xF9"


def test_latest_heartbeat_returns_404_for_unknown_device(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    user_id = seed_admin(session_factory)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    install_admin_override(session_factory, user_id)
    try:
        response = TestClient(app).get(
            "/api/v1/heartbeat/latest", params={"imei": "861431071299189"}
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_devices_expose_latest_heartbeat_telemetry(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    user_id = seed_admin(session_factory)
    with session_factory() as db:
        ingest_heartbeat_record(db, heartbeat("2026-09-09T12:00:00Z", 85, -65), tmp_path)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    install_admin_override(session_factory, user_id)
    try:
        response = TestClient(app).get("/api/v1/devices")
        assert response.status_code == 200
        device = response.json()["items"][0]
        assert device["battery_type"] == 2
        assert device["battery_raw_value"] == 85
        assert device["battery_percent"] == 85
        assert device["signal_type"] == 0
        assert device["signal_raw_value"] == -65
        assert device["signal_percent"] is None
    finally:
        app.dependency_overrides.clear()

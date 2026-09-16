from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.models import Base, HealthRecord
from app.db import get_db
from app.main import app
from app.schemas import HealthIngestRequest
from app.services.ingestion import ingest_health_record


def make_payload(**overrides):
    payload = {
        "imei": "868488079852388",
        "message_type": 50,
        "collected_at": "2026-08-31T11:20:00Z",
        "heart_rate": 92,
        "blood_oxygen": 97,
        "body_temperature": 36.7,
        "wrist_temperature": 33.9,
        "diastolic": 81,
        "systolic": 113,
        "steps": 451,
        "raw_hex": "BDBDBDBD32010203",
    }
    payload.update(overrides)
    return payload


def test_valid_health_payload_is_normalized():
    parsed = HealthIngestRequest.model_validate(make_payload())

    assert parsed.imei == "868488079852388"
    assert parsed.collected_at.tzinfo is not None
    assert parsed.body_temperature == Decimal("36.7")


def test_invalid_imei_and_measurement_are_rejected():
    try:
        HealthIngestRequest.model_validate(make_payload(imei="123", heart_rate=300))
    except ValueError as exc:
        assert "imei" in str(exc)
    else:
        raise AssertionError("invalid health payload was accepted")


def test_duplicate_health_payload_is_ignored(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    payload = HealthIngestRequest.model_validate(make_payload())

    # Ingestion must rely on database-generated IDs.  The old MAX(id)+1
    # helpers are deliberately made unusable so this test catches regressions.
    monkeypatch.setattr("app.services.ingestion._next_record_id", lambda db: (_ for _ in ()).throw(AssertionError("manual IDs are forbidden")), raising=False)
    monkeypatch.setattr("app.services.ingestion._next_device_id", lambda db: (_ for _ in ()).throw(AssertionError("manual IDs are forbidden")), raising=False)
    with session_factory() as db:
        first = ingest_health_record(db, payload, tmp_path)
        second = ingest_health_record(db, payload, tmp_path)
        assert first.duplicate is False
        assert second.duplicate is True
        assert db.query(HealthRecord).count() == 1
        assert first.record_id is not None


def test_http_ingest_requires_token_and_returns_created(tmp_path, monkeypatch):
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

    monkeypatch.setattr("app.api.health.settings.internal_token", "test-token")
    monkeypatch.setattr("app.api.health.settings.raw_spool_dir", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/health",
            headers={"X-Internal-Token": "test-token"},
            json=make_payload(),
        )
        assert response.status_code == 201
        assert response.json()["duplicate"] is False

        unauthorized = client.post("/api/v1/health", json=make_payload())
        assert unauthorized.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint_rejects_when_configured_token_is_empty(tmp_path, monkeypatch):
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

    monkeypatch.setattr("app.api.health.settings.internal_token", "")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post("/api/v1/health", json=make_payload())
        assert response.status_code == 401
        response_with_empty_header = client.post(
            "/api/v1/health", headers={"X-Internal-Token": ""}, json=make_payload()
        )
        assert response_with_empty_header.status_code == 401
    finally:
        app.dependency_overrides.clear()

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base
from app.schemas import HealthIngestRequest
from app.services.ingestion import ingest_health_record


def payload(at: str, heart_rate: int):
    return HealthIngestRequest.model_validate(
        {
            "imei": "868488079852388",
            "message_type": 50,
            "collected_at": at,
            "heart_rate": heart_rate,
            "blood_oxygen": 97,
            "body_temperature": 36.7,
            "wrist_temperature": 33.9,
            "diastolic": 81,
            "systolic": 113,
            "steps": heart_rate,
            "raw_hex": f"BDBDBDBD32{heart_rate:02X}",
        }
    )


def test_query_latest_history_and_devices(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        ingest_health_record(db, payload("2026-08-31T11:20:00Z", 92), tmp_path)
        ingest_health_record(db, payload("2026-08-31T11:21:00Z", 95), tmp_path)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.health.settings.internal_token", "test-token")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        devices = client.get("/api/v1/devices")
        assert devices.status_code == 200
        assert devices.json()["items"][0]["imei"] == "868488079852388"

        latest = client.get("/api/v1/health/latest", params={"imei": "868488079852388"})
        assert latest.status_code == 200
        assert latest.json()["heart_rate"] == 95

        history = client.get(
            "/api/v1/health/history",
            params={
                "imei": "868488079852388",
                "start": "2026-08-31T00:00:00Z",
                "end": "2026-08-31T23:59:59Z",
                "page": 1,
                "page_size": 1,
            },
        )
        assert history.status_code == 200
        assert history.json()["total"] == 2
        assert len(history.json()["items"]) == 1
        assert history.json()["items"][0]["heart_rate"] == 95
    finally:
        app.dependency_overrides.clear()


def test_history_rejects_invalid_range_and_large_page_size():
    # Route validation is exercised against the application schema before database access.
    client = TestClient(app)
    response = client.get(
        "/api/v1/health/history",
        params={
            "imei": "868488079852388",
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-08-31T00:00:00Z",
            "page_size": 1001,
        },
    )
    assert response.status_code == 422

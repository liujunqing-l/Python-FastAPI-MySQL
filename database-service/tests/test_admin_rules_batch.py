from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Device, Role, User
from app.services.auth import create_access_token, hash_password


IM1 = "861431071299189"
IM2 = "861431071299180"


def setup_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        role = Role(name="admin")
        db.add(role)
        db.flush()
        db.add_all([Device(imei=IM1), Device(imei=IM2)])
        admin = User(username="admin", password_hash=hash_password("secret"), role_id=role.id)
        db.add(admin)
        db.commit()
        admin_id = admin.id
    factory = sessionmaker(bind=engine)

    def override_get_db():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {create_access_token(user_id=admin_id, username='admin', role='admin')}"
    }
    return client, headers, app.dependency_overrides


def test_admin_can_create_update_and_delete_alarm_rules(monkeypatch):
    client, headers, overrides = setup_client(monkeypatch)
    try:
        created = client.post(
            "/api/v1/alarm-rules",
            headers=headers,
            json={"name": "心率过高", "alarm_type": "heart_rate", "threshold": 180, "enabled": True},
        )
        assert created.status_code == 201
        rule = created.json()
        assert rule["name"] == "心率过高"
        assert float(rule["threshold"]) == 180

        listed = client.get("/api/v1/alarm-rules", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        updated = client.patch(
            f"/api/v1/alarm-rules/{rule['id']}",
            headers=headers,
            json={"enabled": False, "threshold": 175},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False
        assert float(updated.json()["threshold"]) == 175

        deleted = client.delete(f"/api/v1/alarm-rules/{rule['id']}", headers=headers)
        assert deleted.status_code == 204
    finally:
        overrides.clear()


def test_admin_can_batch_update_devices_and_requires_an_explicit_change(monkeypatch):
    client, headers, overrides = setup_client(monkeypatch)
    try:
        invalid = client.patch("/api/v1/devices/batch", headers=headers, json={"imeis": [IM1]})
        assert invalid.status_code == 422
        updated = client.patch(
            "/api/v1/devices/batch",
            headers=headers,
            json={"imeis": [IM1, IM2], "model": "B2315P-Pro", "enabled": False},
        )
        assert updated.status_code == 200
        assert updated.json()["updated"] == 2
        devices = client.get("/api/v1/devices", headers=headers).json()["items"]
        assert {row["model"] for row in devices} == {"B2315P-Pro"}
        assert {row["enabled"] for row in devices} == {False}
    finally:
        overrides.clear()


def test_non_admin_cannot_modify_alarm_rules_or_batch_devices(monkeypatch):
    client, _, overrides = setup_client(monkeypatch)
    try:
        response = client.get("/api/v1/alarm-rules")
        assert response.status_code == 401
        response = client.patch("/api/v1/devices/batch", json={"imeis": [IM1], "enabled": False})
        assert response.status_code == 401
    finally:
        overrides.clear()

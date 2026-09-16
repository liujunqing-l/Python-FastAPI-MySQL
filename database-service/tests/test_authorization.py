from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Device, DeviceAlarm, Role, User, UserDeviceBinding
from app.services.auth import create_access_token, hash_password


IM1 = "861431071299189"
IM2 = "861431071299180"


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_users(engine):
    with Session(engine) as db:
        roles = {name: Role(name=name) for name in ("admin", "operator", "viewer")}
        db.add_all(roles.values())
        db.flush()
        devices = [Device(imei=IM1), Device(imei=IM2)]
        db.add_all(devices)
        db.flush()
        users = {}
        for username, role in (("admin", "admin"), ("operator", "operator"), ("viewer", "viewer")):
            user = User(
                username=username,
                password_hash=hash_password("secret"),
                display_name=username,
                role_id=roles[role].id,
            )
            db.add(user)
            db.flush()
            users[username] = user
        db.add(UserDeviceBinding(user_id=users["operator"].id, device_id=devices[0].id))
        db.add(UserDeviceBinding(user_id=users["viewer"].id, device_id=devices[0].id))
        alarm = DeviceAlarm(
            device_id=devices[0].id,
            event_hash="a" * 64,
            collected_date=datetime.now(timezone.utc).date(),
            imei=IM1,
            message_id=2,
            collected_at=datetime.now(timezone.utc),
            alarm_codes=["fall"],
            raw_hex="AA0201",
        )
        db.add(alarm)
        db.commit()
        return {name: user.id for name, user in users.items()}, {IM1: devices[0].id, IM2: devices[1].id}, alarm.id


def token(username: str, role: str, user_id: int) -> str:
    return create_access_token(user_id=user_id, username=username, role=role)


def test_admin_sees_all_and_operator_viewer_are_device_scoped(monkeypatch):
    engine = make_db()
    users, _, _ = seed_users(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        admin = {"Authorization": f"Bearer {token('admin', 'admin', users['admin'])}"}
        operator = {"Authorization": f"Bearer {token('operator', 'operator', users['operator'])}"}
        viewer = {"Authorization": f"Bearer {token('viewer', 'viewer', users['viewer'])}"}

        assert client.get("/api/v1/devices", headers=admin).json()["total"] == 2
        assert client.get("/api/v1/devices", headers=operator).json()["total"] == 1
        assert client.get("/api/v1/devices", headers=viewer).json()["total"] == 1

        assert client.get("/api/v1/health/latest", params={"imei": IM2}, headers=operator).status_code == 403
        assert client.get("/api/v1/alarms", params={"imei": IM2}, headers=viewer).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_viewer_can_read_but_cannot_acknowledge_or_create_commands(monkeypatch):
    engine = make_db()
    users, _, alarm_id = seed_users(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        viewer = {"Authorization": f"Bearer {token('viewer', 'viewer', users['viewer'])}"}
        assert client.get("/api/v1/alarms", headers=viewer).status_code == 200
        assert client.patch(f"/api/v1/alarms/{alarm_id}/acknowledge", headers=viewer).status_code == 403
        command = client.post(
            "/api/v1/commands",
            headers=viewer,
            json={"imei": IM1, "command_type": "health_frequency", "interval_minutes": 5},
        )
        assert command.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_internal_ingestion_still_uses_internal_token_only(monkeypatch, tmp_path):
    engine = make_db()
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
            json={
                "imei": IM1,
                "message_type": 50,
                "collected_at": "2026-09-10T00:00:00Z",
                "heart_rate": 80,
                "raw_hex": "BDBDBDBD32AA",
            },
        )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_jwt_cannot_replace_internal_token_for_ingestion_or_worker(monkeypatch, tmp_path):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)
    with Session(engine) as db:
        role = Role(name="admin")
        db.add(role)
        db.flush()
        user = User(username="admin", password_hash=hash_password("secret"), role_id=role.id)
        db.add(user)
        db.commit()
        user_id = user.id

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    monkeypatch.setattr("app.api.health.settings.internal_token", "internal-secret")
    monkeypatch.setattr("app.api.ingest.settings.internal_token", "internal-secret")
    monkeypatch.setattr("app.api.commands.settings.internal_token", "internal-secret")
    monkeypatch.setattr("app.api.health.settings.raw_spool_dir", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        jwt_headers = {
            "Authorization": f"Bearer {create_access_token(user_id=user_id, username='admin', role='admin')}"
        }
        health_body = {
            "imei": IM1,
            "message_type": 50,
            "collected_at": "2026-09-10T00:00:00Z",
            "heart_rate": 80,
            "raw_hex": "BDBDBDBD32AA",
        }
        assert client.post("/api/v1/health", headers=jwt_headers, json=health_body).status_code == 401
        assert client.post("/api/v1/ingest/events", headers=jwt_headers, json={}).status_code == 401
        assert client.post(
            "/api/v1/commands/claim",
            headers=jwt_headers,
            json={"imei": IM1, "worker_id": "test"},
        ).status_code == 401
        assert client.post(
            "/api/v1/health",
            headers={"X-Internal-Token": "wrong"},
            json=health_body,
        ).status_code == 401
    finally:
        app.dependency_overrides.clear()

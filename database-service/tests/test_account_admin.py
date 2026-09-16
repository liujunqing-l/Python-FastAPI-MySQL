from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Device, Role, User
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


def seed_admin(engine):
    with Session(engine) as db:
        roles = {name: Role(name=name) for name in ("admin", "operator", "viewer")}
        db.add_all(roles.values())
        db.flush()
        db.add_all([Device(imei=IM1), Device(imei=IM2)])
        admin = User(username="admin", password_hash=hash_password("secret"), role_id=roles["admin"].id)
        db.add(admin)
        db.commit()
        return admin.id


def test_admin_can_manage_accounts_roles_and_device_bindings(monkeypatch):
    engine = make_db()
    admin_id = seed_admin(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers = {
            "Authorization": f"Bearer {create_access_token(user_id=admin_id, username='admin', role='admin')}"
        }

        roles = client.get("/api/v1/roles", headers=headers)
        assert roles.status_code == 200
        assert {row["name"] for row in roles.json()["items"]} == {"admin", "operator", "viewer"}

        created = client.post(
            "/api/v1/accounts",
            headers=headers,
            json={
                "username": "operator",
                "password": "secret2",
                "display_name": "现场操作员",
                "role": "operator",
            },
        )
        assert created.status_code == 201
        account = created.json()
        assert account["username"] == "operator"
        assert account["role"] == "operator"
        assert account["device_imeis"] == []

        binding = client.put(
            f"/api/v1/accounts/{account['id']}/bindings",
            headers=headers,
            json={"imeis": [IM1]},
        )
        assert binding.status_code == 200
        assert binding.json()["device_imeis"] == [IM1]

        listed = client.get("/api/v1/accounts", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 2
        assert listed.json()["items"][1]["device_imeis"] == [IM1]
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_manage_accounts(monkeypatch):
    engine = make_db()
    admin_id = seed_admin(engine)
    session_factory = sessionmaker(bind=engine)
    with Session(engine) as db:
        operator = User(
            username="operator",
            password_hash=hash_password("secret"),
            role_id=db.scalar(select(Role.id).where(Role.name == "operator")),
        )
        db.add(operator)
        db.commit()
        operator_id = operator.id

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers = {
            "Authorization": f"Bearer {create_access_token(user_id=operator_id, username='operator', role='operator')}"
        }
        assert client.get("/api/v1/accounts", headers=headers).status_code == 403
        assert client.get("/api/v1/roles", headers=headers).status_code == 403
    finally:
        app.dependency_overrides.clear()

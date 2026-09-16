from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Role, User
from app.services.auth import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_pbkdf2_password_hash_round_trip_and_wrong_password():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("wrong", "not-a-valid-hash")


def test_jwt_round_trip_and_expired_token_rejected(monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.auth_jwt_secret", "test-secret")
    token = create_access_token(
        user_id=7,
        username="operator",
        role="operator",
        expires_delta=timedelta(minutes=5),
    )
    claims = verify_access_token(token)
    assert claims["sub"] == "7"
    assert claims["username"] == "operator"
    assert claims["role"] == "operator"

    expired = create_access_token(
        user_id=7,
        username="operator",
        role="operator",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(ValueError, match="expired"):
        verify_access_token(expired)
    with pytest.raises(ValueError, match="malformed"):
        verify_access_token("a.b.c")
    parts = token.split(".")
    tampered = ".".join((parts[0], parts[1] + "x", parts[2]))
    with pytest.raises(ValueError, match="signature"):
        verify_access_token(tampered)


def test_login_and_me_return_profile_and_reject_invalid_credentials(monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        role = Role(name="operator")
        db.add(role)
        db.flush()
        db.add(
            User(
                username="operator",
                password_hash=hash_password("secret"),
                display_name="值班员",
                role_id=role.id,
                enabled=True,
            )
        )
        db.commit()

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.auth.settings.auth_jwt_secret", "test-secret")
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        bad = client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "wrong"},
        )
        assert bad.status_code == 401

        logged_in = client.post(
            "/api/v1/auth/login",
            data={"username": "operator", "password": "secret"},
        )
        assert logged_in.status_code == 200, logged_in.text
        body = logged_in.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["role"] == "operator"
        assert body["user"]["display_name"] == "值班员"

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["username"] == "operator"
        assert me.json()["role"] == "operator"

        missing = client.get("/api/v1/auth/me")
        assert missing.status_code == 401
    finally:
        app.dependency_overrides.clear()

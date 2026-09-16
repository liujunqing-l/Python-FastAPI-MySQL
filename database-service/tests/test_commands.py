"""Command queue and protocol downlink contract tests.

These tests are intentionally written before the command implementation.  They
pin the byte-level protocol examples and the short-connection state machine so
that an API response can never imply that a device executed a command before a
0xC0 feedback frame is received.
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
from app.models import Base, Device, DeviceCommand, Role, User
from app.services.auth import get_current_user, hash_password
from app.services.commands import (
    build_alarm_switch_frame,
    build_health_frequency_frame,
    build_location_frequency_frame,
    build_location_priority_frame,
)


IMEI = "861431071299189"


def install_admin(engine, session_factory):
    with Session(engine) as db:
        role = Role(name="admin")
        db.add(role)
        db.flush()
        user = User(username="test-admin", password_hash=hash_password("secret"), role_id=role.id)
        db.add(user)
        db.commit()
        user_id = user.id

    def override_current_user():
        with session_factory() as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_current_user] = override_current_user


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_command_builders_match_documented_frames_and_checksum():
    location = build_location_frequency_frame(interval_minutes=10)
    assert location.hex().upper() == (
        "BDBDBDBD17010A000000173B00000000000000000000000000000000000000000097"
    )

    priority = build_location_priority_frame(["gps", "wifi", "ble"])
    assert priority.hex().upper() == "BDBDBDBDCE0100030001020333"

    health = build_health_frequency_frame(interval_minutes=5)
    assert health.hex().upper() == "BDBDBDBDCE0200030000050033"

    alarm = build_alarm_switch_frame(alarm_type=7, enabled=False)
    # The protocol document prints 0x93 for this example, but its stated
    # complement checksum over the complete frame body computes 0x34.  The
    # parser already preserves such vendor-example discrepancies, so builders
    # use the documented algorithm consistently.
    assert alarm.hex().upper() == "BDBDBDBDCE0702000034"

    # CE20 has a two-byte body: target 0=location/1=health, then switch.
    upload = build_alarm_switch_frame(alarm_type=20, enabled=True, target="location")
    # The vendor example also prints 0x93 here; the documented checksum
    # algorithm yields 0x1B for this frame body.
    assert upload.hex().upper() == "BDBDBDBDCE2000020000001B"


def test_command_builders_reject_out_of_range_or_ambiguous_values():
    with pytest.raises(ValueError):
        build_location_frequency_frame(interval_minutes=0)
    with pytest.raises(ValueError):
        build_location_frequency_frame(interval_minutes=65536)
    with pytest.raises(ValueError):
        build_health_frequency_frame(interval_minutes=1)
    with pytest.raises(ValueError):
        build_location_priority_frame(["gps", "gps"])
    with pytest.raises(ValueError):
        build_alarm_switch_frame(alarm_type=6, enabled=True)
    with pytest.raises(ValueError):
        build_alarm_switch_frame(alarm_type=20, enabled=True)


def test_command_model_exposes_pending_claim_and_ack_fields():
    table = Base.metadata.tables["device_commands"]
    expected = {
        "id",
        "device_id",
        "imei",
        "command_type",
        "message_id",
        "subtype",
        "payload",
        "frame_hex",
        "status",
        "attempts",
        "max_attempts",
        "available_at",
        "claimed_at",
        "claim_expires_at",
        "claimed_by",
        "sent_at",
        "acknowledged_at",
        "feedback_message_ids",
        "last_error",
        "created_at",
        "updated_at",
    }
    assert expected <= set(table.c.keys())
    assert any(
        index.name == "ix_device_commands_pending"
        for index in table.indexes
    )


def test_enqueue_claim_and_ack_are_explicit_state_transitions(tmp_path, monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.commands.settings.internal_token", "test-token")
    install_admin(engine, session_factory)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        queued = client.post(
            "/api/v1/commands",
            json={
                "imei": IMEI,
                "command_type": "health_frequency",
                "interval_minutes": 5,
            },
        )
        assert queued.status_code == 201, queued.text
        queued_body = queued.json()
        assert queued_body["status"] == "pending"
        assert queued_body["executed"] is False
        command_id = queued_body["id"]
        assert queued_body["frame_hex"] == "BDBDBDBDCE0200030000050033"

        claimed = client.post(
            "/api/v1/commands/claim",
            headers={"X-Internal-Token": "test-token"},
            json={"imei": IMEI, "worker_id": "tcp-test"},
        )
        assert claimed.status_code == 200, claimed.text
        assert len(claimed.json()["items"]) == 1
        item = claimed.json()["items"][0]
        assert item["id"] == command_id
        assert item["status"] == "claimed"
        assert item["executed"] is False

        # A second claim in the same connection window cannot send the same
        # command twice.
        second_claim = client.post(
            "/api/v1/commands/claim",
            headers={"X-Internal-Token": "test-token"},
            json={"imei": IMEI, "worker_id": "tcp-test"},
        )
        assert second_claim.status_code == 200
        assert second_claim.json()["items"] == []

        sent = client.post(
            f"/api/v1/commands/{command_id}/sent",
            headers={"X-Internal-Token": "test-token"},
        )
        assert sent.status_code == 200, sent.text

        ack = client.post(
            f"/api/v1/commands/{command_id}/acknowledge",
            headers={"X-Internal-Token": "test-token"},
            json={"message_ids": [0xCE]},
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "acknowledged"
        assert ack.json()["executed"] is True

        # Acknowledge is idempotent and does not change the first timestamp.
        acknowledged_at = ack.json()["acknowledged_at"]
        again = client.post(
            f"/api/v1/commands/{command_id}/acknowledge",
            headers={"X-Internal-Token": "test-token"},
            json={"message_ids": [0xCE]},
        )
        assert again.status_code == 200
        assert again.json()["acknowledged_at"] == acknowledged_at
    finally:
        app.dependency_overrides.clear()


def test_claim_endpoint_requires_worker_token(monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.commands.settings.internal_token", "test-token")
    install_admin(engine, session_factory)
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/v1/commands/claim",
            json={"imei": IMEI, "worker_id": "tcp-test"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_expired_claim_returns_to_pending_and_mismatched_feedback_does_not_execute(monkeypatch):
    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.commands.settings.internal_token", "test-token")
    install_admin(engine, session_factory)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/commands",
            json={"imei": IMEI, "command_type": "location_frequency", "interval_minutes": 1},
        )
        command_id = created.json()["id"]
        headers = {"X-Internal-Token": "test-token"}
        first = client.post(
            "/api/v1/commands/claim",
            headers=headers,
            json={"imei": IMEI, "worker_id": "worker-a", "claim_ttl_seconds": 1},
        )
        assert first.json()["items"][0]["attempts"] == 1

        with Session(engine) as db:
            row = db.get(DeviceCommand, command_id)
            row.claim_expires_at = datetime.now(timezone.utc).replace(year=2020)
            db.commit()

        second = client.post(
            "/api/v1/commands/claim",
            headers=headers,
            json={"imei": IMEI, "worker_id": "worker-b", "claim_ttl_seconds": 1},
        )
        assert second.json()["items"][0]["attempts"] == 2

        wrong = client.post(
            "/api/v1/commands/feedback",
            headers=headers,
            json={"imei": IMEI, "message_ids": [0xCE]},
        )
        # Location-frequency is 0x17, so a CE feedback cannot mark it done.
        assert wrong.json()["items"] == []
        listed = client.get(f"/api/v1/commands?imei={IMEI}")
        assert listed.json()["items"][0]["executed"] is False
    finally:
        app.dependency_overrides.clear()


def test_feedback_cannot_execute_a_command_that_was_never_claimed(monkeypatch):
    """A matching protocol ID is not enough without a worker claim/send."""

    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.commands.settings.internal_token", "test-token")
    install_admin(engine, session_factory)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/commands",
            json={"imei": IMEI, "command_type": "health_frequency", "interval_minutes": 5},
        )
        assert created.status_code == 201, created.text
        command_id = created.json()["id"]

        direct_ack = client.post(
            f"/api/v1/commands/{command_id}/acknowledge",
            headers={"X-Internal-Token": "test-token"},
            json={"message_ids": [0xCE]},
        )
        assert direct_ack.status_code == 200, direct_ack.text
        assert direct_ack.json()["status"] == "pending"
        assert direct_ack.json()["executed"] is False
    finally:
        app.dependency_overrides.clear()


def test_retry_failure_clears_old_claim_metadata(monkeypatch):
    """A retryable send failure must not expose the previous lease as active."""

    engine = make_db()
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    monkeypatch.setattr("app.api.commands.settings.internal_token", "test-token")
    install_admin(engine, session_factory)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/commands",
            json={"imei": IMEI, "command_type": "health_frequency", "interval_minutes": 5},
        )
        command_id = created.json()["id"]
        headers = {"X-Internal-Token": "test-token"}
        claimed = client.post(
            "/api/v1/commands/claim",
            headers=headers,
            json={"imei": IMEI, "worker_id": "tcp-test"},
        )
        assert claimed.status_code == 200, claimed.text
        sent = client.post(
            f"/api/v1/commands/{command_id}/sent",
            headers=headers,
        )
        assert sent.status_code == 200, sent.text

        with Session(engine) as db:
            from app.services.commands import fail_command

            row = fail_command(db, command_id, "socket closed before feedback")
            assert row.status == "pending"
            assert row.claimed_at is None
            assert row.claimed_by is None

        listed = client.get(f"/api/v1/commands?imei={IMEI}")
        item = listed.json()["items"][0]
        assert item["status"] == "pending"
        assert item["claim_expires_at"] is None
        assert item["claimed_by"] is None
        assert item["sent_at"] is None
    finally:
        app.dependency_overrides.clear()

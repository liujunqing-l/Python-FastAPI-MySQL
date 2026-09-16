from __future__ import annotations

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Device, Role, User, UserDeviceBinding
from app.services.auth import hash_password


def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_roles_and_users_are_unique_and_bindings_have_composite_identity():
    engine = make_db()
    with Session(engine) as db:
        admin = Role(name="admin")
        db.add(admin)
        db.flush()
        user = User(
            username="admin",
            password_hash=hash_password("secret"),
            role_id=admin.id,
        )
        device = Device(imei="861431071299189")
        db.add_all([user, device])
        db.flush()
        binding = UserDeviceBinding(user_id=user.id, device_id=device.id)
        db.add(binding)
        db.commit()

        assert db.scalar(
            select(UserDeviceBinding).where(
                UserDeviceBinding.user_id == user.id,
                UserDeviceBinding.device_id == device.id,
            )
        ) is not None

        db.add(User(username="admin", password_hash=hash_password("other"), role_id=admin.id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(
                insert(UserDeviceBinding).values(user_id=user.id, device_id=device.id)
            )


def test_device_binding_model_does_not_expose_command_execution_state():
    assert not hasattr(UserDeviceBinding, "executed")

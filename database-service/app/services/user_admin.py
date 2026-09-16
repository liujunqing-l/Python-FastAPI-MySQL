"""Explicit administrator initialization used during deployment."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Device, Role, User, UserDeviceBinding
from .auth import hash_password


ROLE_NAMES = ("admin", "operator", "viewer")


def create_or_reset_admin(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
) -> User:
    username = username.strip()
    if not username:
        raise ValueError("username must not be empty")
    if not password:
        raise ValueError("password must not be empty")
    role = db.scalar(select(Role).where(Role.name == "admin"))
    if role is None:
        raise RuntimeError("admin role is missing; run alembic upgrade head first")
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, role_id=role.id)
        db.add(user)
    user.password_hash = hash_password(password)
    user.display_name = display_name or user.display_name or username
    user.role_id = role.id
    user.enabled = True
    db.commit()
    db.refresh(user)
    return user


def role_by_name(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise ValueError(f"role {name!r} is not configured")
    return role


def replace_user_bindings(db: Session, user: User, imeis: list[str]) -> list[str]:
    devices = db.scalars(select(Device).where(Device.imei.in_(imeis))).all() if imeis else []
    found = {device.imei for device in devices}
    missing = [imei for imei in imeis if imei not in found]
    if missing:
        raise ValueError(f"unknown device IMEI: {', '.join(missing)}")
    db.execute(delete(UserDeviceBinding).where(UserDeviceBinding.user_id == user.id))
    db.add_all(
        [UserDeviceBinding(user_id=user.id, device_id=device.id) for device in devices]
    )
    db.flush()
    return imeis


def user_device_imeis(db: Session, user_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Device.imei)
            .join(UserDeviceBinding, UserDeviceBinding.device_id == Device.id)
            .where(UserDeviceBinding.user_id == user_id)
            .order_by(Device.imei)
        ).all()
    )

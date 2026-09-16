"""Role and IMEI scoping dependencies for browser-facing endpoints."""

from __future__ import annotations

from typing import Callable, Iterable, Optional, TypeVar

from fastapi import Depends, HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Device, User, UserDeviceBinding
from .auth import get_current_user, user_role


ModelT = TypeVar("ModelT")


def _forbidden(detail: str = "insufficient permissions") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_roles(*allowed_roles: str) -> Callable:
    """Build a FastAPI dependency that authenticates and checks a role."""

    allowed = frozenset(allowed_roles)

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user_role(db, user) not in allowed:
            raise _forbidden()
        return user

    return dependency


def require_browser_user(
    user: User = Depends(get_current_user),
) -> User:
    """Authenticate any role allowed to read browser data."""

    return user


def bound_device_ids(user: User, db: Session):
    """Return a scalar subquery of device IDs visible to a non-admin user."""

    return select(UserDeviceBinding.device_id).where(UserDeviceBinding.user_id == user.id)


def is_admin(user: User, db: Session) -> bool:
    return user_role(db, user) == "admin"


def scope_devices(statement: Select, *, model, user: User, db: Session) -> Select:
    """Restrict a Device or device-event statement at the SQL boundary."""

    if is_admin(user, db):
        return statement
    if hasattr(model, "device_id"):
        return statement.where(model.device_id.in_(bound_device_ids(user, db)))
    # Health/heartbeat/event rows carry IMEI instead of a foreign-key column.
    return statement.where(
        model.imei.in_(
            select(Device.imei)
            .join(UserDeviceBinding, UserDeviceBinding.device_id == Device.id)
            .where(UserDeviceBinding.user_id == user.id)
        )
    )


def assert_imei_access(*, user: User, db: Session, imei: str) -> None:
    """Reject an unbound IMEI before a browser query can disclose its data."""

    if is_admin(user, db):
        return
    permitted = db.scalar(
        select(Device.id)
        .join(UserDeviceBinding, UserDeviceBinding.device_id == Device.id)
        .where(Device.imei == imei, UserDeviceBinding.user_id == user.id)
    )
    if permitted is None:
        raise _forbidden("device is not bound to this user")

def assert_device_access(*, user: User, db: Session, device_id: int) -> None:
    if is_admin(user, db):
        return
    permitted = db.scalar(
        select(UserDeviceBinding.device_id).where(
            UserDeviceBinding.user_id == user.id,
            UserDeviceBinding.device_id == device_id,
        )
    )
    if permitted is None:
        raise _forbidden("device is not bound to this user")

"""Administrator-only user, binding, and device management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AlarmRule, Device, Role, User
from ..schemas import (
    AccountCreateRequest,
    AccountResponse,
    AccountUpdateRequest,
    AlarmRuleCreateRequest,
    AlarmRuleResponse,
    AlarmRuleUpdateRequest,
    BindingReplaceRequest,
    DeviceCreateRequest,
    DeviceResponse,
    DeviceUpdateRequest,
    DeviceBatchUpdateRequest,
    DeviceBatchUpdateResponse,
    PaginatedAccountResponse,
    PaginatedDeviceResponse,
    PaginatedRoleResponse,
    PaginatedAlarmRuleResponse,
    RoleResponse,
)
from ..services.auth import get_current_user, hash_password, user_role
from ..services.device_status import device_status
from ..services.user_admin import replace_user_bindings, role_by_name, user_device_imeis


router = APIRouter(prefix="/api/v1", tags=["admin"])


def _require_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if user_role(db, user) != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


def _account_response(db: Session, user: User) -> AccountResponse:
    role = db.get(Role, user.role_id)
    if role is None:
        raise HTTPException(status_code=500, detail="user role is missing")
    return AccountResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=role.name,
        enabled=user.enabled,
        device_imeis=user_device_imeis(db, user.id),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _device_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        imei=device.imei,
        name=device.name,
        model=device.model,
        enabled=device.enabled,
        last_seen_at=device.last_seen_at,
        status=device_status(device.last_seen_at, datetime.now(timezone.utc)),
        battery_type=None,
        battery_raw_value=None,
        battery_percent=None,
        signal_type=None,
        signal_raw_value=None,
        signal_percent=None,
    )


@router.get("/roles", response_model=PaginatedRoleResponse)
def list_roles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> PaginatedRoleResponse:
    total = int(db.scalar(select(func.count()).select_from(Role)) or 0)
    rows = db.scalars(
        select(Role).order_by(Role.name).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PaginatedRoleResponse(
        items=[RoleResponse(id=row.id, name=row.name) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/accounts", response_model=PaginatedAccountResponse)
def list_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> PaginatedAccountResponse:
    total = int(db.scalar(select(func.count()).select_from(User)) or 0)
    rows = db.scalars(
        select(User).order_by(User.username).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PaginatedAccountResponse(
        items=[_account_response(db, row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    request: AccountCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AccountResponse:
    try:
        role = role_by_name(db, request.role)
        user = User(
            username=request.username,
            password_hash=hash_password(request.password),
            display_name=request.display_name,
            role_id=role.id,
            enabled=request.enabled,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return _account_response(db, user)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(
    request: AccountUpdateRequest,
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
) -> AccountResponse:
    user = db.get(User, account_id)
    if user is None:
        raise HTTPException(status_code=404, detail="account not found")
    if user.id == admin.id:
        if request.enabled is False or request.role not in (None, "admin"):
            raise HTTPException(status_code=422, detail="the current admin cannot disable or demote itself")
    try:
        if request.password is not None:
            user.password_hash = hash_password(request.password)
        if request.display_name is not None:
            user.display_name = request.display_name
        if request.role is not None:
            user.role_id = role_by_name(db, request.role).id
        if request.enabled is not None:
            user.enabled = request.enabled
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_response(db, user)


@router.put("/accounts/{account_id}/bindings", response_model=AccountResponse)
def replace_bindings(
    request: BindingReplaceRequest,
    account_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AccountResponse:
    user = db.get(User, account_id)
    if user is None:
        raise HTTPException(status_code=404, detail="account not found")
    try:
        replace_user_bindings(db, user, request.imeis)
        db.commit()
        db.refresh(user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _account_response(db, user)


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    request: DeviceCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> DeviceResponse:
    device = Device(
        imei=request.imei,
        name=request.name,
        model=request.model,
        enabled=request.enabled,
    )
    db.add(device)
    try:
        db.commit()
        db.refresh(device)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="device IMEI already exists") from exc
    return _device_response(device)


@router.patch("/devices/batch", response_model=DeviceBatchUpdateResponse)
def batch_update_devices(
    request: DeviceBatchUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> DeviceBatchUpdateResponse:
    rows = db.scalars(select(Device).where(Device.imei.in_(request.imeis))).all()
    if len(rows) != len(request.imeis):
        found = {row.imei for row in rows}
        missing = [imei for imei in request.imeis if imei not in found]
        raise HTTPException(status_code=404, detail=f"unknown device IMEI: {', '.join(missing)}")
    now = datetime.now(timezone.utc)
    for device in rows:
        if request.name is not None:
            device.name = request.name
        if request.model is not None:
            device.model = request.model
        if request.enabled is not None:
            device.enabled = request.enabled
        device.updated_at = now
    db.commit()
    return DeviceBatchUpdateResponse(updated=len(rows))


@router.patch("/devices/{imei}", response_model=DeviceResponse)
def update_device(
    request: DeviceUpdateRequest,
    imei: str = Path(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> DeviceResponse:
    device = db.scalar(select(Device).where(Device.imei == imei))
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if request.name is not None:
        device.name = request.name
    if request.model is not None:
        device.model = request.model
    if request.enabled is not None:
        device.enabled = request.enabled
    device.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)
    return _device_response(device)


@router.get("/alarm-rules", response_model=PaginatedAlarmRuleResponse)
def list_alarm_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> PaginatedAlarmRuleResponse:
    total = int(db.scalar(select(func.count()).select_from(AlarmRule)) or 0)
    rows = db.scalars(
        select(AlarmRule).order_by(AlarmRule.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PaginatedAlarmRuleResponse(items=rows, page=page, page_size=page_size, total=total)


@router.post("/alarm-rules", response_model=AlarmRuleResponse, status_code=status.HTTP_201_CREATED)
def create_alarm_rule(
    request: AlarmRuleCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AlarmRuleResponse:
    rule = AlarmRule(**request.model_dump())
    db.add(rule)
    try:
        db.commit()
        db.refresh(rule)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="alarm rule name already exists") from exc
    return rule


@router.patch("/alarm-rules/{rule_id}", response_model=AlarmRuleResponse)
def update_alarm_rule(
    request: AlarmRuleUpdateRequest,
    rule_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> AlarmRuleResponse:
    rule = db.get(AlarmRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alarm rule not found")
    for field in ("name", "alarm_type", "threshold", "direction", "enabled"):
        value = getattr(request, field)
        if value is not None:
            setattr(rule, field, value)
    rule.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(rule)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="alarm rule name already exists") from exc
    return rule


@router.delete("/alarm-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_alarm_rule(
    rule_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(_require_admin),
) -> None:
    rule = db.get(AlarmRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alarm rule not found")
    db.delete(rule)
    db.commit()

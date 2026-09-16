"""Read APIs for decoded device events.

The TCP parser writes concern-specific rows through ``/api/v1/ingest/events``.
This module exposes those rows to the browser without exposing PostgreSQL or
requiring the browser to know the internal SQLAlchemy models.  Query endpoints
are deliberately read-only except for the small, idempotent alarm
acknowledgement transition.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DeviceAlarm, DeviceConfigSnapshot, LocationRecord, SleepRecord, User
from ..services.auth import get_current_user
from ..services.authorization import (
    assert_device_access,
    assert_imei_access,
    require_roles,
    scope_devices,
)


router = APIRouter(prefix="/api/v1", tags=["events"])


class AlarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    event_hash: str
    collected_date: date
    imei: str
    message_id: int
    collected_at: datetime
    received_at: datetime
    alarm_group: Optional[int] = None
    alarm_mask: Optional[int] = None
    alarm_codes: List[str]
    sensor_type: Optional[int] = None
    threshold_direction: Optional[int] = None
    measured_value: Optional[Decimal] = None
    sensor_values: Optional[dict[str, Any]] = None
    status: str
    acknowledged_at: Optional[datetime] = None
    parse_version: Optional[str] = None
    raw_hex: str
    raw_archive_id: Optional[int] = None


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    event_hash: str
    collected_date: date
    imei: str
    message_id: int
    collected_at: datetime
    received_at: datetime
    source: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    north_south: Optional[str] = None
    east_west: Optional[str] = None
    position_status: Optional[str] = None
    position_valid: Optional[bool] = None
    coordinate_system: Optional[str] = None
    precision_digits: Optional[int] = None
    cells: Optional[Any] = None
    wifi_access_points: Optional[Any] = None
    beacon_groups: Optional[Any] = None
    resolution_status: str
    raw_hex: str
    raw_archive_id: Optional[int] = None


class SleepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    event_hash: str
    collected_date: date
    imei: str
    message_id: int
    collected_at: datetime
    received_at: datetime
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    sleep_stage: Optional[int] = None
    raw_hex: str
    raw_archive_id: Optional[int] = None


class DeviceConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    event_hash: str
    collected_date: date
    imei: str
    message_id: int
    collected_at: datetime
    received_at: datetime
    location_modified: Optional[bool] = None
    location_interval_minutes: Optional[int] = None
    health_modified: Optional[bool] = None
    health_interval_minutes: Optional[int] = None
    timestamp_source: str
    raw_hex: str
    raw_archive_id: Optional[int] = None


class PaginatedAlarmResponse(BaseModel):
    items: List[AlarmResponse]
    page: int
    page_size: int
    total: int


class PaginatedLocationResponse(BaseModel):
    items: List[LocationResponse]
    page: int
    page_size: int
    total: int


class PaginatedSleepResponse(BaseModel):
    items: List[SleepResponse]
    page: int
    page_size: int
    total: int


def _validate_aware_time(value: Optional[datetime], name: str) -> Optional[datetime]:
    """Validate a query timestamp and normalize it to UTC.

    FastAPI parses ISO-8601 values before entering the endpoint.  A timestamp
    without an offset is still a valid Python ``datetime`` but is ambiguous for
    a multi-time-zone device fleet, so it is rejected just like the health
    history endpoint.
    """

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail=f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _validate_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _validate_aware_time(start, "start")
    normalized_end = _validate_aware_time(end, "end")
    # Both values are required by the endpoint signatures, but keeping this
    # guard makes the helper safe to reuse and keeps type checkers honest.
    if normalized_start is None or normalized_end is None:
        raise HTTPException(status_code=422, detail="start and end are required")
    if normalized_end <= normalized_start:
        raise HTTPException(status_code=422, detail="end must be later than start")
    return normalized_start, normalized_end


def _alarm_filters(
    imei: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    status: Optional[str],
):
    filters = []
    if imei is not None:
        filters.append(DeviceAlarm.imei == imei)
    normalized_start = _validate_aware_time(start, "start")
    normalized_end = _validate_aware_time(end, "end")
    if normalized_start is not None and normalized_end is not None:
        if normalized_end <= normalized_start:
            raise HTTPException(status_code=422, detail="end must be later than start")
    if normalized_start is not None:
        filters.append(DeviceAlarm.collected_at >= normalized_start)
    if normalized_end is not None:
        filters.append(DeviceAlarm.collected_at < normalized_end)
    if status is not None:
        filters.append(DeviceAlarm.status == status)
    return filters


@router.get("/alarms", response_model=PaginatedAlarmResponse)
def list_alarms(
    imei: Optional[str] = Query(
        default=None, min_length=14, max_length=20, pattern=r"^\d{14,20}$"
    ),
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    status: Optional[Literal["pending", "acknowledged"]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedAlarmResponse:
    filters = _alarm_filters(imei, start, end, status)
    if imei is not None:
        assert_imei_access(user=user, db=db, imei=imei)
    count_query = scope_devices(
        select(func.count()).select_from(DeviceAlarm).where(*filters),
        model=DeviceAlarm,
        user=user,
        db=db,
    )
    total = int(
        db.scalar(count_query) or 0
    )
    rows_query = scope_devices(
        select(DeviceAlarm).where(*filters), model=DeviceAlarm, user=user, db=db
    )
    rows = db.scalars(
        rows_query
        .order_by(DeviceAlarm.collected_at.desc(), DeviceAlarm.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedAlarmResponse(items=rows, page=page, page_size=page_size, total=total)


@router.patch("/alarms/{alarm_id}/acknowledge", response_model=AlarmResponse)
def acknowledge_alarm(
    alarm_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> AlarmResponse:
    """Acknowledge an alarm once; repeating the request is harmless.

    ``FOR UPDATE`` serializes concurrent acknowledgements on PostgreSQL.  On
    SQLite (used by the unit tests) it is ignored, which is still sufficient
    for the single-writer development setup.
    """

    alarm = db.scalar(
        select(DeviceAlarm).where(DeviceAlarm.id == alarm_id).with_for_update()
    )
    if alarm is None:
        raise HTTPException(status_code=404, detail="alarm not found")
    assert_device_access(user=user, db=db, device_id=alarm.device_id)

    if alarm.status == "pending":
        alarm.status = "acknowledged"
        alarm.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(alarm)
    return alarm


@router.get("/locations/latest", response_model=LocationResponse)
def latest_location(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LocationResponse:
    assert_imei_access(user=user, db=db, imei=imei)
    record = db.scalar(
        select(LocationRecord)
        .where(LocationRecord.imei == imei)
        .order_by(LocationRecord.collected_at.desc(), LocationRecord.id.desc())
        .limit(1)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="no location records found")
    return record


@router.get("/locations/history", response_model=PaginatedLocationResponse)
def location_history(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    start: datetime = Query(...),
    end: datetime = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedLocationResponse:
    normalized_start, normalized_end = _validate_range(start, end)
    assert_imei_access(user=user, db=db, imei=imei)
    filters = (
        LocationRecord.imei == imei,
        LocationRecord.collected_at >= normalized_start,
        LocationRecord.collected_at < normalized_end,
    )
    total_query = scope_devices(
        select(func.count()).select_from(LocationRecord).where(*filters),
        model=LocationRecord,
        user=user,
        db=db,
    )
    total = int(db.scalar(total_query) or 0)
    rows_query = scope_devices(
        select(LocationRecord).where(*filters), model=LocationRecord, user=user, db=db
    )
    rows = db.scalars(
        rows_query
        .order_by(LocationRecord.collected_at.desc(), LocationRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedLocationResponse(items=rows, page=page, page_size=page_size, total=total)


@router.get("/sleep/history", response_model=PaginatedSleepResponse)
def sleep_history(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    start: datetime = Query(...),
    end: datetime = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedSleepResponse:
    normalized_start, normalized_end = _validate_range(start, end)
    assert_imei_access(user=user, db=db, imei=imei)
    filters = (
        SleepRecord.imei == imei,
        SleepRecord.collected_at >= normalized_start,
        SleepRecord.collected_at < normalized_end,
    )
    total_query = scope_devices(
        select(func.count()).select_from(SleepRecord).where(*filters),
        model=SleepRecord,
        user=user,
        db=db,
    )
    total = int(db.scalar(total_query) or 0)
    rows_query = scope_devices(
        select(SleepRecord).where(*filters), model=SleepRecord, user=user, db=db
    )
    rows = db.scalars(
        rows_query
        .order_by(SleepRecord.collected_at.desc(), SleepRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedSleepResponse(items=rows, page=page, page_size=page_size, total=total)


@router.get(
    "/device-config/{imei}",
    response_model=DeviceConfigResponse,
)
def latest_device_config(
    imei: str = Path(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeviceConfigResponse:
    assert_imei_access(user=user, db=db, imei=imei)
    snapshot = db.scalar(
        select(DeviceConfigSnapshot)
        .where(DeviceConfigSnapshot.imei == imei)
        .order_by(
            DeviceConfigSnapshot.collected_at.desc(), DeviceConfigSnapshot.id.desc()
        )
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no device configuration found")
    return snapshot

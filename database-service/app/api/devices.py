from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Device, HeartbeatRecord
from ..schemas import PaginatedDeviceResponse
from ..schemas import DeviceResponse
from ..services.device_status import device_status
from ..services.auth import get_current_user
from ..services.authorization import scope_devices
from ..models import User


router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("", response_model=PaginatedDeviceResponse)
def list_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedDeviceResponse:
    total_query = scope_devices(
        select(func.count()).select_from(Device), model=Device, user=user, db=db
    )
    total = int(db.scalar(total_query) or 0)
    rows_query = scope_devices(
        select(Device), model=Device, user=user, db=db
    )
    rows = db.scalars(
        rows_query
        .order_by(Device.imei)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    now = datetime.now(timezone.utc)
    # Fetch only the most recent F9 row for each listed device.  A missing row
    # remains None in the response; no battery/signal value is invented.
    latest_heartbeat: dict[str, HeartbeatRecord] = {}
    for device in rows:
        heartbeat = db.scalar(
            select(HeartbeatRecord)
            .where(HeartbeatRecord.imei == device.imei)
            .order_by(HeartbeatRecord.collected_at.desc(), HeartbeatRecord.id.desc())
            .limit(1)
        )
        if heartbeat is not None:
            latest_heartbeat[device.imei] = heartbeat

    items = [
        DeviceResponse(
            id=device.id,
            imei=device.imei,
            name=device.name,
            model=device.model,
            enabled=device.enabled,
            last_seen_at=device.last_seen_at,
            status=device_status(device.last_seen_at, now),
            battery_type=(latest_heartbeat[device.imei].battery_type
                          if device.imei in latest_heartbeat else None),
            battery_raw_value=(latest_heartbeat[device.imei].battery_raw_value
                               if device.imei in latest_heartbeat else None),
            battery_percent=(latest_heartbeat[device.imei].battery_percent
                             if device.imei in latest_heartbeat else None),
            signal_type=(latest_heartbeat[device.imei].signal_type
                         if device.imei in latest_heartbeat else None),
            signal_raw_value=(latest_heartbeat[device.imei].signal_raw_value
                              if device.imei in latest_heartbeat else None),
            signal_percent=(latest_heartbeat[device.imei].signal_percent
                            if device.imei in latest_heartbeat else None),
        )
        for device in rows
    ]
    return PaginatedDeviceResponse(items=items, page=page, page_size=page_size, total=total)

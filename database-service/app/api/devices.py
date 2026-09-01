from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Device
from ..schemas import PaginatedDeviceResponse


router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("", response_model=PaginatedDeviceResponse)
def list_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> PaginatedDeviceResponse:
    total = int(db.scalar(select(func.count()).select_from(Device)) or 0)
    rows = db.scalars(
        select(Device)
        .order_by(Device.imei)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedDeviceResponse(items=rows, page=page, page_size=page_size, total=total)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import HeartbeatRecord, User
from ..schemas import HeartbeatRecordResponse
from ..services.auth import get_current_user
from ..services.authorization import assert_imei_access
from .ingest import _heartbeat_response


router = APIRouter(prefix="/api/v1/heartbeat", tags=["heartbeat"])


@router.get("/latest", response_model=HeartbeatRecordResponse)
def latest_heartbeat(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HeartbeatRecordResponse:
    assert_imei_access(user=user, db=db, imei=imei)
    record = db.scalar(
        select(HeartbeatRecord)
        .where(HeartbeatRecord.imei == imei)
        .order_by(HeartbeatRecord.collected_at.desc(), HeartbeatRecord.id.desc())
        .limit(1)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="no heartbeat records found")
    return _heartbeat_response(record)

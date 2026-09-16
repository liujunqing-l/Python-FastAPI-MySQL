import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import HealthRecord, User
from ..schemas import HealthIngestRequest, HealthRecordResponse, PaginatedHealthResponse
from ..services.auth import get_current_user
from ..services.authorization import assert_imei_access
from ..services.ingestion import ingest_health_record


router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.post("", status_code=status.HTTP_201_CREATED)
def ingest_health(
    payload: HealthIngestRequest,
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
):
    if (
        not settings.internal_token
        or not internal_token
        or not hmac.compare_digest(internal_token, settings.internal_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")
    try:
        result = ingest_health_record(db, payload, settings.raw_spool_dir)
    except OperationalError:
        db.rollback()
        return JSONResponse(
            status_code=503,
            content={"status": "retry", "retryable": True},
        )

    response = {
        "status": "duplicate" if result.duplicate else "created",
        "duplicate": result.duplicate,
        "event_hash": result.event_hash,
        "record_id": result.record_id,
    }
    return JSONResponse(
        status_code=200 if result.duplicate else 201,
        content=response,
    )


@router.get("/latest", response_model=HealthRecordResponse)
def latest_health(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HealthRecordResponse:
    assert_imei_access(user=user, db=db, imei=imei)
    record = db.scalar(
        select(HealthRecord)
        .where(HealthRecord.imei == imei)
        .order_by(HealthRecord.collected_at.desc(), HealthRecord.id.desc())
        .limit(1)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="no health records found")
    return record


@router.get("/history", response_model=PaginatedHealthResponse)
def health_history(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    start: datetime = Query(...),
    end: datetime = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedHealthResponse:
    if start.tzinfo is None or start.utcoffset() is None:
        raise HTTPException(status_code=422, detail="start must include a timezone")
    if end.tzinfo is None or end.utcoffset() is None:
        raise HTTPException(status_code=422, detail="end must include a timezone")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be later than start")
    assert_imei_access(user=user, db=db, imei=imei)

    base = select(HealthRecord).where(
        HealthRecord.imei == imei,
        HealthRecord.collected_at >= start,
        HealthRecord.collected_at < end,
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(HealthRecord)
            .where(
                HealthRecord.imei == imei,
                HealthRecord.collected_at >= start,
                HealthRecord.collected_at < end,
            )
        )
        or 0
    )
    rows = db.scalars(
        base.order_by(HealthRecord.collected_at.desc(), HealthRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedHealthResponse(items=rows, page=page, page_size=page_size, total=total)

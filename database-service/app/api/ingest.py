from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import HeartbeatRecord
from ..schemas import (
    EventIngestResponse,
    HeartbeatRecordResponse,
)
from ..services.ingestion import ingest_event_record, parse_event_payload
from ..models import User
from ..services.auth import get_current_user
from ..services.authorization import assert_imei_access


router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


def _heartbeat_response(record: HeartbeatRecord) -> HeartbeatRecordResponse:
    return HeartbeatRecordResponse(
        id=record.id,
        imei=record.imei,
        message_id=f"0x{record.message_id:02X}",
        event_type=record.event_type,
        collected_at=record.collected_at,
        received_at=record.received_at,
        battery_type=record.battery_type,
        battery_raw_value=record.battery_raw_value,
        battery_percent=record.battery_percent,
        signal_type=record.signal_type,
        signal_raw_value=record.signal_raw_value,
        signal_percent=record.signal_percent,
        steps_type=record.steps_type,
        steps_value=record.steps_value,
        event_hash=record.event_hash,
        raw_hex=record.raw_hex,
    )


@router.post(
    "/events",
    response_model=EventIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_event(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> EventIngestResponse | JSONResponse:
    """Accept a decoded heartbeat, alarm, location, sleep, or config event.

    The raw JSON object is accepted at the FastAPI boundary so authentication
    can be checked before validation.  ``parse_event_payload`` then performs
    strict discriminated validation and normalizes parser message-id forms.
    """

    if (
        not settings.internal_token
        or not internal_token
        or not hmac.compare_digest(internal_token, settings.internal_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")
    try:
        parsed = parse_event_payload(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = ingest_event_record(db, parsed, settings.raw_spool_dir)
    except OperationalError:
        db.rollback()
        return JSONResponse(
            status_code=503,
            content={"status": "retry", "retryable": True},
        )

    return JSONResponse(
        status_code=200 if result.duplicate else 201,
        content={
            "status": "duplicate" if result.duplicate else "created",
            "duplicate": result.duplicate,
            "event_hash": result.event_hash,
            "record_id": result.record_id,
            "event_type": result.event_type,
            # Preserve the established F9 response string while returning
            # canonical numeric IDs for all newly supported event types.
            "message_id": "0xF9" if result.message_id == 249 else result.message_id,
        },
    )


@router.get("/heartbeat/latest", response_model=HeartbeatRecordResponse)
def latest_heartbeat_via_ingest(
    imei: str = Query(..., min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HeartbeatRecordResponse:
    """Compatibility alias for clients that group reads below ``/ingest``."""

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

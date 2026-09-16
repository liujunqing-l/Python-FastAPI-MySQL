"""Command queue APIs for browser requests and the TCP worker.

The browser can enqueue a command and observe its ``pending`` state.  Only an
authenticated TCP worker can claim, mark-sent, or acknowledge a command.  A
command is reported as executed only after a matching 0xC0 feedback event.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import DeviceCommand, User
from ..schemas import (
    CommandAcknowledgeRequest,
    CommandClaimRequest,
    CommandFeedbackRequest,
    DeviceCommandRequest,
    DeviceCommandResponse,
    PaginatedCommandResponse,
)
from ..services.commands import (
    acknowledge_command,
    acknowledge_feedback,
    build_command,
    claim_pending_commands,
    enqueue_command,
    fail_command,
    mark_command_sent,
)
from ..services.auth import get_current_user
from ..services.authorization import assert_imei_access, require_roles, scope_devices


router = APIRouter(prefix="/api/v1/commands", tags=["commands"])


def _require_worker_token(internal_token: str) -> None:
    if (
        not settings.internal_token
        or not internal_token
        or not hmac.compare_digest(internal_token, settings.internal_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


def _build_from_request(request: DeviceCommandRequest):
    return build_command(
        request.command_type,
        interval_minutes=request.interval_minutes,
        priority=request.priority,
        alarm_type=request.alarm_type,
        enabled=request.enabled,
        target=request.target,
        slots=request.slots,
        health_type=request.health_type,
        time_unit=request.time_unit,
        valid=request.valid,
        start_time=request.start_time,
        end_time=request.end_time,
    )


@router.post("", response_model=DeviceCommandResponse, status_code=status.HTTP_201_CREATED)
def create_command(
    request: DeviceCommandRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "operator")),
) -> DeviceCommandResponse:
    assert_imei_access(user=user, db=db, imei=request.imei)
    try:
        built = _build_from_request(request)
        result = enqueue_command(
            db,
            imei=request.imei,
            command=built,
            max_attempts=request.max_attempts,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.command


@router.get("", response_model=PaginatedCommandResponse)
def list_commands(
    imei: Optional[str] = Query(default=None, min_length=14, max_length=20, pattern=r"^\d{14,20}$"),
    command_status: Optional[str] = Query(default=None, alias="status", max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedCommandResponse:
    filters = []
    if imei is not None:
        filters.append(DeviceCommand.imei == imei)
    if command_status is not None:
        if command_status not in {"pending", "claimed", "sent", "acknowledged", "failed", "expired"}:
            raise HTTPException(status_code=422, detail="invalid command status")
        filters.append(DeviceCommand.status == command_status)
    if imei is not None:
        assert_imei_access(user=user, db=db, imei=imei)
    total_query = scope_devices(
        select(func.count()).select_from(DeviceCommand).where(*filters),
        model=DeviceCommand,
        user=user,
        db=db,
    )
    total = int(db.scalar(total_query) or 0)
    rows_query = scope_devices(
        select(DeviceCommand).where(*filters), model=DeviceCommand, user=user, db=db
    )
    rows = db.scalars(
        rows_query
        .order_by(DeviceCommand.created_at.desc(), DeviceCommand.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaginatedCommandResponse(items=rows, page=page, page_size=page_size, total=total)


@router.post("/claim", response_model=PaginatedCommandResponse)
def claim_commands(
    request: CommandClaimRequest,
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> PaginatedCommandResponse:
    _require_worker_token(internal_token)
    rows = claim_pending_commands(
        db,
        imei=request.imei,
        worker_id=request.worker_id,
        limit=request.limit,
        claim_ttl_seconds=request.claim_ttl_seconds,
    )
    return PaginatedCommandResponse(
        items=rows,
        page=1,
        page_size=request.limit,
        total=len(rows),
    )


@router.post("/feedback", response_model=PaginatedCommandResponse)
def command_feedback(
    request: CommandFeedbackRequest,
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> PaginatedCommandResponse:
    _require_worker_token(internal_token)
    rows = acknowledge_feedback(db, imei=request.imei, message_ids=request.message_ids)
    return PaginatedCommandResponse(items=rows, page=1, page_size=max(len(rows), 1), total=len(rows))


@router.post("/{command_id}/sent", response_model=DeviceCommandResponse)
def command_sent(
    command_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> DeviceCommandResponse:
    _require_worker_token(internal_token)
    try:
        return mark_command_sent(db, command_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{command_id}/acknowledge", response_model=DeviceCommandResponse)
def command_acknowledge(
    request: CommandAcknowledgeRequest,
    command_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> DeviceCommandResponse:
    _require_worker_token(internal_token)
    try:
        return acknowledge_command(db, command_id, message_ids=request.message_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{command_id}/fail", response_model=DeviceCommandResponse)
def command_fail(
    error: str = "worker failure",
    command_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> DeviceCommandResponse:
    _require_worker_token(internal_token)
    try:
        return fail_command(db, command_id, error)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Device, HealthRecord
from ..schemas import HealthIngestRequest


@dataclass(frozen=True)
class HealthIngestResult:
    duplicate: bool
    event_hash: str
    record_id: int | None


def _event_hash(payload: HealthIngestRequest) -> str:
    value = "|".join(
        (
            payload.imei,
            payload.collected_at.isoformat(),
            str(payload.message_type),
            payload.raw_hex,
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _next_record_id(db: Session) -> int:
    current = db.scalar(select(func.max(HealthRecord.id)))
    return int(current or 0) + 1


def _next_device_id(db: Session) -> int:
    current = db.scalar(select(func.max(Device.id)))
    return int(current or 0) + 1


def _append_raw_payload(payload: HealthIngestRequest, event_hash: str, spool_dir: Path) -> None:
    collected = payload.collected_at.astimezone(timezone.utc)
    destination = spool_dir / collected.strftime("%Y/%m/%d") / f"{payload.imei}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "event_hash": event_hash,
        "imei": payload.imei,
        "collected_at": collected.isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "raw_hex": payload.raw_hex,
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def ingest_health_record(
    db: Session, payload: HealthIngestRequest, spool_dir: Union[str, Path]
) -> HealthIngestResult:
    event_hash = _event_hash(payload)
    collected_date = payload.collected_at.date()
    existing = db.scalar(
        select(HealthRecord).where(
            HealthRecord.event_hash == event_hash,
            HealthRecord.collected_date == collected_date,
        )
    )
    if existing is not None:
        db.commit()
        return HealthIngestResult(True, event_hash, existing.id)

    device = db.scalar(select(Device).where(Device.imei == payload.imei))
    if device is None:
        device = Device(
            id=_next_device_id(db), imei=payload.imei, model="B2315P", enabled=True
        )
        db.add(device)
        db.flush()
    device.last_seen_at = payload.collected_at

    record = HealthRecord(
        id=_next_record_id(db),
        collected_date=collected_date,
        event_hash=event_hash,
        imei=payload.imei,
        message_type=payload.message_type,
        collected_at=payload.collected_at,
        heart_rate=payload.heart_rate,
        blood_oxygen=payload.blood_oxygen,
        body_temperature=payload.body_temperature,
        wrist_temperature=payload.wrist_temperature,
        diastolic=payload.diastolic,
        systolic=payload.systolic,
        steps=payload.steps,
    )
    db.add(record)
    _append_raw_payload(payload, event_hash, Path(spool_dir))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(HealthRecord).where(
                HealthRecord.event_hash == event_hash,
                HealthRecord.collected_date == collected_date,
            )
        )
        if existing is not None:
            return HealthIngestResult(True, event_hash, existing.id)
        raise
    return HealthIngestResult(False, event_hash, record.id)

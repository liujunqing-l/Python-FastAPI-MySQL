from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Union

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Device,
    DeviceAlarm,
    DeviceConfigSnapshot,
    HealthRecord,
    HeartbeatRecord,
    LocationRecord,
    SleepRecord,
)
from ..schemas import (
    AlarmEvent,
    ConfigSnapshotEvent,
    EventPayload,
    HealthIngestRequest,
    HeartbeatIngestRequest,
    LocationEvent,
    SleepEvent,
    normalize_protocol_message_id,
)


@dataclass(frozen=True)
class HealthIngestResult:
    duplicate: bool
    event_hash: str
    record_id: int | None


@dataclass(frozen=True)
class HeartbeatIngestResult:
    duplicate: bool
    event_hash: str
    record_id: int | None


@dataclass(frozen=True)
class EventIngestResult:
    duplicate: bool
    event_hash: str
    record_id: int | None
    event_type: str
    message_id: int


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


def _get_or_create_device(db: Session, imei: str) -> Device:
    """Load and lock a device row before comparing/updating last_seen_at.

    ``FOR UPDATE`` is honored by PostgreSQL and ignored by SQLite, which is
    sufficient for the unit-test dialect.  A concurrent first-seen insert can
    race on the IMEI unique constraint; after the failed flush we roll back
    that savepoint and lock the row inserted by the other transaction.
    """

    device = db.scalar(
        select(Device).where(Device.imei == imei).with_for_update()
    )
    if device is not None:
        return device

    device = Device(imei=imei, model="B2315P", enabled=True)
    try:
        # A savepoint keeps a concurrent first-seen unique violation from
        # rolling back unrelated work already staged in the caller's session.
        with db.begin_nested():
            db.add(device)
            db.flush()
    except IntegrityError:
        device = db.scalar(
            select(Device).where(Device.imei == imei).with_for_update()
        )
        if device is None:
            raise
    return device


def _set_last_seen(device: Device, collected_at: datetime) -> None:
    """Advance last_seen_at without allowing out-of-order packets to regress it."""

    current = device.last_seen_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    incoming = collected_at
    if incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    if current is None or incoming > current:
        device.last_seen_at = collected_at


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

    device = _get_or_create_device(db, payload.imei)
    _set_last_seen(device, payload.collected_at)

    record = HealthRecord(
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


def _heartbeat_event_hash(payload: HeartbeatIngestRequest) -> str:
    value = "|".join(
        (
            payload.imei,
            payload.collected_at.isoformat(),
            "249",
            payload.raw_hex,
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _append_heartbeat_payload(
    payload: HeartbeatIngestRequest, event_hash: str, spool_dir: Path
) -> None:
    collected = payload.collected_at.astimezone(timezone.utc)
    destination = spool_dir / collected.strftime("%Y/%m/%d") / f"{payload.imei}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "event_hash": event_hash,
        "event_type": payload.event_type,
        "message_id": payload.message_id,
        "imei": payload.imei,
        "collected_at": collected.isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "battery_type": payload.battery_type,
        "battery_raw_value": payload.battery_raw_value,
        "battery_percent": (
            str(payload.battery_percent) if payload.battery_percent is not None else None
        ),
        "signal_type": payload.signal_type,
        "signal_raw_value": payload.signal_raw_value,
        "signal_percent": (
            str(payload.signal_percent) if payload.signal_percent is not None else None
        ),
        "steps_type": payload.steps_type,
        "steps_value": payload.steps_value,
        "raw_hex": payload.raw_hex,
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _effective_battery_percent(payload: HeartbeatIngestRequest) -> Decimal | None:
    """Return only an explicitly supplied or protocol-unambiguous percentage.

    B2315P type 0/1 values are level encodings and type 3 is a voltage.  None
    of those can safely be presented as a percentage without a vendor mapping.
    Type 2 is explicitly a percentage according to the protocol.
    """

    if payload.battery_type == 2:
        if payload.battery_percent is not None:
            return payload.battery_percent
        if payload.battery_raw_value is not None:
            if 0 <= payload.battery_raw_value <= 100:
                return Decimal(payload.battery_raw_value)
    return None


def ingest_heartbeat_record(
    db: Session, payload: HeartbeatIngestRequest, spool_dir: Union[str, Path]
) -> HeartbeatIngestResult:
    """Persist one decoded F9 event and make retries idempotent."""

    event_hash = _heartbeat_event_hash(payload)
    collected_date = payload.collected_at.date()
    existing = db.scalar(
        select(HeartbeatRecord).where(
            HeartbeatRecord.event_hash == event_hash,
            HeartbeatRecord.collected_date == collected_date,
        )
    )
    if existing is not None:
        db.commit()
        return HeartbeatIngestResult(True, event_hash, existing.id)

    device = _get_or_create_device(db, payload.imei)
    _set_last_seen(device, payload.collected_at)

    record = HeartbeatRecord(
        collected_date=collected_date,
        event_hash=event_hash,
        imei=payload.imei,
        message_id=249,
        event_type="heartbeat",
        collected_at=payload.collected_at,
        battery_type=payload.battery_type,
        battery_raw_value=payload.battery_raw_value,
        battery_percent=_effective_battery_percent(payload),
        signal_type=payload.signal_type,
        signal_raw_value=payload.signal_raw_value,
        signal_percent=payload.signal_percent,
        steps_type=payload.steps_type,
        steps_value=payload.steps_value,
        raw_hex=payload.raw_hex,
    )
    db.add(record)
    _append_heartbeat_payload(payload, event_hash, Path(spool_dir))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(HeartbeatRecord).where(
                HeartbeatRecord.event_hash == event_hash,
                HeartbeatRecord.collected_date == collected_date,
            )
        )
        if existing is not None:
            return HeartbeatIngestResult(True, event_hash, existing.id)
        raise
    return HeartbeatIngestResult(False, event_hash, record.id)


# IDs accepted by the unified event endpoint.  Keeping this map explicit is
# intentional: unsupported protocol frames must remain raw/logged rather than
# being guessed into a business table.
_EVENT_TYPES_BY_MESSAGE_ID: dict[int, str] = {
    2: "alarm",
    22: "alarm",
    33: "alarm",
    3: "location",
    21: "location",
    164: "location",
    214: "location",
    197: "sleep",
    233: "config_snapshot",
    249: "heartbeat",
}

_EVENT_SCHEMA_BY_TYPE: dict[str, type] = {
    "heartbeat": HeartbeatIngestRequest,
    "alarm": AlarmEvent,
    "location": LocationEvent,
    "sleep": SleepEvent,
    "config_snapshot": ConfigSnapshotEvent,
}


def parse_event_payload(value: Any) -> EventPayload:
    """Validate and normalize one parser-facing unified event payload.

    ``message_id`` may be a protocol byte, decimal string, or hexadecimal
    string.  Dispatch is based on the normalized ID and the declared event
    type must agree with the protocol mapping.  Pydantic then enforces the
    event-specific ``extra='forbid'`` contract.
    """

    if not isinstance(value, dict):
        raise ValueError("event payload must be a JSON object")
    data = dict(value)

    declared_type = data.get("event_type")
    if declared_type is None:
        # We need the parser's type before resolving ambiguous digit-only
        # strings such as ``21`` (decimal location ID versus hexadecimal 0x21
        # alarm ID).  F9 retains its historical implicit type.
        declared_type = data.get("type", "heartbeat")
    if not isinstance(declared_type, str) or not declared_type.strip():
        raise ValueError("event_type is required")
    event_type = declared_type.strip().lower()

    raw_message_id = data.get("message_id")
    if raw_message_id is None and "message_type" in data:
        # The old F9 contract uses message_type as an alias.  It is handled by
        # HeartbeatIngestRequest; copying it here allows dispatch while the
        # model still decides whether the alias is legal for that event.
        raw_message_id = data["message_type"]
    if raw_message_id is None:
        raise ValueError("message_id is required")
    message_id = normalize_protocol_message_id(raw_message_id, event_type)

    expected_type = _EVENT_TYPES_BY_MESSAGE_ID.get(message_id)
    if expected_type is None:
        raise ValueError(f"unsupported message_id: {message_id}")
    if event_type != expected_type:
        raise ValueError(
            f"message_id {message_id} requires event_type {expected_type}"
        )

    # Normalize the values used by Pydantic.  Keep legacy F9 aliases in place
    # so HeartbeatIngestRequest can apply its conflict checks; event-specific
    # models intentionally reject unrelated extra keys.
    data["message_id"] = message_id
    data["event_type"] = event_type
    schema = _EVENT_SCHEMA_BY_TYPE[event_type]
    return schema.model_validate(data)


def _generic_event_hash(payload: EventPayload) -> str:
    """Hash a canonical envelope plus event details for idempotency."""

    message_id = (
        249
        if isinstance(payload, HeartbeatIngestRequest)
        else int(payload.message_id)
    )
    event_type = payload.event_type
    canonical = payload.model_dump(mode="json", exclude_none=False)
    value = json.dumps(
        {
            "event_type": event_type,
            "message_id": message_id,
            "imei": payload.imei,
            "collected_at": payload.collected_at.astimezone(timezone.utc).isoformat(),
            "raw_hex": payload.raw_hex,
            "payload": canonical,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _append_event_payload(
    payload: EventPayload, event_hash: str, spool_dir: Path
) -> None:
    """Append one canonical JSONL line for a newly accepted event."""

    collected = payload.collected_at.astimezone(timezone.utc)
    destination = spool_dir / collected.strftime("%Y/%m/%d") / f"{payload.imei}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    message_id = 249 if isinstance(payload, HeartbeatIngestRequest) else int(payload.message_id)
    line = {
        "event_hash": event_hash,
        "event_type": payload.event_type,
        "message_id": message_id,
        "imei": payload.imei,
        "collected_at": collected.isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload.model_dump(mode="json", exclude_none=False),
        "raw_hex": payload.raw_hex,
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")


def _event_model_and_values(payload: EventPayload, device: Device, event_hash: str):
    """Build the concern-specific ORM row for a validated event."""

    collected_date = payload.collected_at.date()
    common = {
        "device_id": device.id,
        "event_hash": event_hash,
        "collected_date": collected_date,
        "imei": payload.imei,
        "message_id": 249 if isinstance(payload, HeartbeatIngestRequest) else int(payload.message_id),
        "collected_at": payload.collected_at,
        "raw_hex": payload.raw_hex,
    }
    if isinstance(payload, AlarmEvent):
        return DeviceAlarm(
            **common,
            alarm_group=payload.alarm_group,
            alarm_mask=payload.alarm_mask,
            alarm_codes=payload.alarm_codes,
            sensor_type=payload.sensor_type,
            threshold_direction=payload.threshold_direction,
            measured_value=payload.measured_value,
            sensor_values=payload.sensor_values,
            parse_version=payload.parse_version,
        )
    if isinstance(payload, LocationEvent):
        return LocationRecord(
            **common,
            source=payload.source,
            latitude=payload.latitude,
            longitude=payload.longitude,
            north_south=payload.north_south,
            east_west=payload.east_west,
            position_status=payload.position_status,
            position_valid=payload.position_valid,
            coordinate_system=payload.coordinate_system,
            precision_digits=payload.precision_digits,
            cells=payload.cells,
            wifi_access_points=payload.wifi_access_points,
            beacon_groups=payload.beacon_groups,
            resolution_status=payload.resolution_status,
        )
    if isinstance(payload, SleepEvent):
        return SleepRecord(
            **common,
            start_at=payload.start_at,
            end_at=payload.end_at,
            duration_minutes=payload.duration_minutes,
            sleep_stage=payload.sleep_stage,
        )
    if isinstance(payload, ConfigSnapshotEvent):
        return DeviceConfigSnapshot(
            **common,
            location_modified=payload.location_modified,
            location_interval_minutes=payload.location_interval_minutes,
            health_modified=payload.health_modified,
            health_interval_minutes=payload.health_interval_minutes,
            timestamp_source=payload.timestamp_source,
        )
    raise ValueError("heartbeat events use ingest_heartbeat_record")


def _find_event_duplicate(db: Session, payload: EventPayload, event_hash: str):
    collected_date = payload.collected_at.date()
    if isinstance(payload, AlarmEvent):
        model = DeviceAlarm
    elif isinstance(payload, LocationEvent):
        model = LocationRecord
    elif isinstance(payload, SleepEvent):
        model = SleepRecord
    elif isinstance(payload, ConfigSnapshotEvent):
        model = DeviceConfigSnapshot
    else:
        return None
    return db.scalar(
        select(model).where(
            model.event_hash == event_hash,
            model.collected_date == collected_date,
        )
    )


def ingest_event_record(
    db: Session, payload: EventPayload, spool_dir: Union[str, Path]
) -> EventIngestResult:
    """Persist any supported unified event and make delivery idempotent."""

    if isinstance(payload, HeartbeatIngestRequest):
        result = ingest_heartbeat_record(db, payload, spool_dir)
        return EventIngestResult(
            duplicate=result.duplicate,
            event_hash=result.event_hash,
            record_id=result.record_id,
            event_type="heartbeat",
            message_id=249,
        )

    event_hash = _generic_event_hash(payload)
    existing = _find_event_duplicate(db, payload, event_hash)
    if existing is not None:
        return EventIngestResult(
            duplicate=True,
            event_hash=event_hash,
            record_id=existing.id,
            event_type=payload.event_type,
            message_id=int(payload.message_id),
        )

    device = _get_or_create_device(db, payload.imei)
    _set_last_seen(device, payload.collected_at)
    record = _event_model_and_values(payload, device, event_hash)
    db.add(record)
    try:
        # Commit first so a unique race cannot leave an archival line for a
        # transaction that was rolled back.  The line is written exactly once
        # after the row is accepted.
        db.flush()
        record_id = record.id
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_event_duplicate(db, payload, event_hash)
        if existing is not None:
            return EventIngestResult(
                duplicate=True,
                event_hash=event_hash,
                record_id=existing.id,
                event_type=payload.event_type,
                message_id=int(payload.message_id),
            )
        raise
    _append_event_payload(payload, event_hash, Path(spool_dir))
    return EventIngestResult(
        duplicate=False,
        event_hash=event_hash,
        record_id=record_id,
        event_type=payload.event_type,
        message_id=int(payload.message_id),
    )

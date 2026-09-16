"""Device downlink command builders and the short-connection queue service.

The protocol document describes downlink frames as little-endian payloads
with the same ``BD BD BD BD`` header and complement checksum used by the TCP
parser.  This module is intentionally independent of the socket: it builds
and persists a frame, while the TCP worker claims it during the F0 login
window and reports the device's 0xC0 feedback separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Device, DeviceCommand


HEADER = bytes.fromhex("BDBDBDBD")
COMMAND_CE = 0xCE
LOCATION_FREQUENCY_MESSAGE_ID = 0x17
HEALTH_FREQUENCY_SUBTYPE = 0x02
LOCATION_PRIORITY_SUBTYPE = 0x01
ALARM_SWITCH_TYPES = frozenset({0x07, 0x08, 0x19, 0x20})

# The protocol calls these values ``01 GPS/BDS, 02 Wi-Fi, 03 BLE beacon``.
# LBS and 125k are retained because the document lists them for special
# firmware, but are not silently substituted for a missing priority item.
LOCATION_PRIORITY_CODES: Mapping[str, int] = {
    "gps": 0x01,
    "satellite": 0x01,
    "gps_bds": 0x01,
    "wifi": 0x02,
    "lbs_wifi": 0x02,
    "ble": 0x03,
    "beacon": 0x03,
    "bluetooth": 0x03,
    "lbs": 0x04,
    "125k": 0x05,
}


def checksum(data: bytes) -> int:
    """Return the vendor complement checksum for bytes before CK."""

    return (0xFF - sum(data)) & 0xFF


def _frame(payload: bytes) -> bytes:
    body = HEADER + payload
    return body + bytes([checksum(body)])


def _bounded_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if integer != value and not isinstance(value, str):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= integer <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return integer


_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _time_parts(value: Any, *, name: str) -> tuple[int, int]:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        hour = _bounded_int(value[0], name=f"{name} hour", minimum=0, maximum=23)
        minute = _bounded_int(value[1], name=f"{name} minute", minimum=0, maximum=59)
        return hour, minute
    if not isinstance(value, str):
        raise ValueError(f"{name} must use HH:MM format")
    match = _TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"{name} must use HH:MM format")
    hour = _bounded_int(match.group(1), name=f"{name} hour", minimum=0, maximum=23)
    minute = _bounded_int(match.group(2), name=f"{name} minute", minimum=0, maximum=59)
    return hour, minute


def _normalize_enabled(value: Any, *, name: str = "enabled") -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"0", "1", "true", "false", "on", "off"}:
        return value.strip().lower() in {"1", "true", "on"}
    raise ValueError(f"{name} must be a boolean")


def _slot_values(slot: Mapping[str, Any], *, index: int) -> bytes:
    enabled_value = slot.get("enabled", slot.get("enable", False))
    enabled = _normalize_enabled(enabled_value, name=f"slots[{index}].enabled")
    interval_value = slot.get("interval_minutes", slot.get("interval", 0))
    if enabled:
        interval = _bounded_int(
            interval_value,
            name=f"slots[{index}].interval_minutes",
            minimum=1,
            maximum=0xFFFF,
        )
        start = _time_parts(slot.get("start_time", "00:00"), name=f"slots[{index}].start_time")
        end = _time_parts(slot.get("end_time", "23:59"), name=f"slots[{index}].end_time")
    else:
        # Disabled slots are explicitly zero-filled per the vendor example.
        interval = 0
        start = (0, 0)
        end = (0, 0)
    return bytes(
        [1 if enabled else 0]
    ) + interval.to_bytes(2, "little") + bytes([start[0], start[1], end[0], end[1]])


def build_location_frequency_frame(
    interval_minutes: Optional[int] = None,
    *,
    slots: Optional[Sequence[Mapping[str, Any]]] = None,
    enabled: bool = True,
    start_time: str = "00:00",
    end_time: str = "23:59",
) -> bytes:
    """Build the 0x17 four-time-slot location upload configuration frame.

    ``interval_minutes`` is a convenience for the common all-day setting.  A
    caller needing multiple periods can provide exactly four slot mappings.
    The protocol's interval field is u16 minutes; the API applies a smaller
    operational upper bound separately when desired.
    """

    if slots is not None and interval_minutes is not None:
        raise ValueError("provide interval_minutes or slots, not both")
    if slots is None:
        if interval_minutes is None:
            raise ValueError("interval_minutes or slots is required")
        slots = [
            {
                "enabled": enabled,
                "interval_minutes": interval_minutes,
                "start_time": start_time,
                "end_time": end_time,
            },
            {"enabled": False},
            {"enabled": False},
            {"enabled": False},
        ]
    if len(slots) != 4:
        raise ValueError("location frequency requires exactly four slots")
    body = bytearray([LOCATION_FREQUENCY_MESSAGE_ID])
    for index, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            raise ValueError(f"slots[{index}] must be an object")
        body.extend(_slot_values(slot, index=index))
    return _frame(bytes(body))


def _priority_code(value: Any) -> int:
    if isinstance(value, str):
        key = value.strip().lower().replace(" ", "_")
        if key in LOCATION_PRIORITY_CODES:
            return LOCATION_PRIORITY_CODES[key]
        # Accept a hexadecimal/decimal protocol code explicitly.
        try:
            value = int(value, 0)
        except ValueError as exc:
            raise ValueError(f"unsupported location priority: {value}") from exc
    code = _bounded_int(value, name="priority item", minimum=1, maximum=5)
    return code


def build_location_priority_frame(
    priority: Sequence[Any], *, valid: int = 0
) -> bytes:
    """Build a CE01 location-priority frame.

    The generic firmware reserves three bytes for the priority chain.  Shorter
    chains are padded with zero (the documented single-GPS/single-Wi-Fi
    examples), while duplicates are rejected because they are ambiguous.
    """

    if isinstance(priority, (str, bytes)) or not isinstance(priority, Sequence):
        raise ValueError("priority must be a sequence of one to three items")
    if not 1 <= len(priority) <= 3:
        raise ValueError("priority must contain one to three items")
    valid_value = _bounded_int(valid, name="valid", minimum=0, maximum=1)
    codes = [_priority_code(item) for item in priority]
    if len(set(codes)) != len(codes):
        raise ValueError("priority items must be unique")
    body = bytes(codes + [0] * (3 - len(codes)))
    return _frame(bytes([COMMAND_CE, LOCATION_PRIORITY_SUBTYPE, valid_value]) + (3).to_bytes(2, "little") + body)


def build_health_frequency_frame(
    interval_minutes: int,
    *,
    health_type: int = 0,
    time_unit: int = 0,
    valid: int = 0,
) -> bytes:
    """Build a CE02 health-sampling/upload-frequency frame.

    The documented general firmware accepts minute units and has a shortest
    interval of two minutes.  Hour units are retained for the protocol's
    one-byte field and accept 1..255 hours.
    """

    health_type_value = _bounded_int(health_type, name="health_type", minimum=0, maximum=7)
    unit_value = _bounded_int(time_unit, name="time_unit", minimum=0, maximum=1)
    valid_value = _bounded_int(valid, name="valid", minimum=0, maximum=1)
    minimum = 2 if unit_value == 0 else 1
    interval = _bounded_int(
        interval_minutes,
        name="interval_minutes",
        minimum=minimum,
        maximum=0xFF,
    )
    body = bytes([health_type_value, interval, unit_value])
    return _frame(bytes([COMMAND_CE, HEALTH_FREQUENCY_SUBTYPE, valid_value]) + (3).to_bytes(2, "little") + body)


def _alarm_switch_code(alarm_type: Any) -> int:
    if isinstance(alarm_type, str):
        text = alarm_type.strip().lower().replace("-", "_")
        aliases = {
            "fall": 0x07,
            "fall_alarm": 0x07,
            "sedentary": 0x08,
            "stay": 0x08,
            "sos": 0x19,
            "sos_button": 0x19,
            "upload": 0x20,
            "data_upload": 0x20,
            "health_location_upload": 0x20,
        }
        if text in aliases:
            return aliases[text]
        try:
            alarm_type = int(text, 0)
        except ValueError as exc:
            raise ValueError(f"unsupported alarm switch type: {alarm_type}") from exc
        # The vendor document labels these subtypes as 7/8/19/20 while the
        # wire bytes are 0x07/0x08/0x19/0x20.  The normalization below treats
        # those decimal labels as protocol subtype labels.
    value = _bounded_int(alarm_type, name="alarm_type", minimum=0, maximum=0xFF)
    if value == 19:
        value = 0x19
    elif value == 20:
        value = 0x20
    if value not in ALARM_SWITCH_TYPES:
        raise ValueError("alarm_type must be one of 0x07, 0x08, 0x19, or 0x20")
    return value


def build_alarm_switch_frame(
    alarm_type: Any,
    enabled: Any,
    *,
    target: Any = None,
) -> bytes:
    """Build a CE07/CE08/CE19/CE20 alarm/upload switch frame.

    For CE20 (documented as type 20), ``target`` is required: 0 means
    location reporting and 1 means health reporting.  The vendor's CE20
    layout differs from the generic four-byte switch layout.
    """

    subtype = _alarm_switch_code(alarm_type)
    switch = 0 if _normalize_enabled(enabled) else 2
    if subtype == 0x20:
        if target is None:
            raise ValueError("target is required for alarm_type 20")
        if isinstance(target, str):
            aliases = {"location": 0, "position": 0, "health": 1, "vitals": 1}
            target_key = target.strip().lower()
            if target_key in aliases:
                target = aliases[target_key]
        target_value = _bounded_int(target, name="target", minimum=0, maximum=1)
        # CE20: Valid=00, Len=0002, body=[target, switch].
        return _frame(bytes([COMMAND_CE, subtype, 0]) + (2).to_bytes(2, "little") + bytes([target_value, switch]))
    # CE07/08/13: subtype, switch, and a reserved 0000 field.
    return _frame(bytes([COMMAND_CE, subtype, switch, 0, 0]))


@dataclass(frozen=True)
class BuiltCommand:
    command_type: str
    message_id: int
    subtype: Optional[int]
    payload: dict[str, Any]
    frame: bytes


def build_command(
    command_type: str,
    *,
    interval_minutes: Optional[int] = None,
    priority: Optional[Sequence[Any]] = None,
    alarm_type: Any = None,
    enabled: Any = None,
    target: Any = None,
    slots: Optional[Sequence[Mapping[str, Any]]] = None,
    health_type: int = 0,
    time_unit: int = 0,
    valid: int = 0,
    start_time: str = "00:00",
    end_time: str = "23:59",
) -> BuiltCommand:
    """Normalize a browser request and return its exact wire frame."""

    normalized = str(command_type).strip().lower().replace("-", "_")
    aliases = {
        "location_interval": "location_frequency",
        "location_upload_frequency": "location_frequency",
        "health_interval": "health_frequency",
        "health_upload_frequency": "health_frequency",
        "location_priority": "location_priority",
        "alarm": "alarm_switch",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized == "location_frequency":
        frame = build_location_frequency_frame(
            interval_minutes,
            slots=slots,
            enabled=True if enabled is None else _normalize_enabled(enabled),
            start_time=start_time,
            end_time=end_time,
        )
        payload: dict[str, Any] = {
            "interval_minutes": interval_minutes,
            "slots": list(slots) if slots is not None else None,
            "enabled": True if enabled is None else bool(enabled),
            "start_time": start_time,
            "end_time": end_time,
        }
        return BuiltCommand(normalized, LOCATION_FREQUENCY_MESSAGE_ID, None, payload, frame)
    if normalized == "location_priority":
        if priority is None:
            raise ValueError("priority is required")
        frame = build_location_priority_frame(priority, valid=valid)
        return BuiltCommand(
            normalized,
            COMMAND_CE,
            LOCATION_PRIORITY_SUBTYPE,
            {"priority": list(priority), "valid": valid},
            frame,
        )
    if normalized == "health_frequency":
        if interval_minutes is None:
            raise ValueError("interval_minutes is required")
        frame = build_health_frequency_frame(
            interval_minutes,
            health_type=health_type,
            time_unit=time_unit,
            valid=valid,
        )
        return BuiltCommand(
            normalized,
            COMMAND_CE,
            HEALTH_FREQUENCY_SUBTYPE,
            {
                "interval_minutes": interval_minutes,
                "health_type": health_type,
                "time_unit": time_unit,
                "valid": valid,
            },
            frame,
        )
    if normalized == "alarm_switch":
        if alarm_type is None or enabled is None:
            raise ValueError("alarm_type and enabled are required")
        subtype = _alarm_switch_code(alarm_type)
        frame = build_alarm_switch_frame(alarm_type, enabled, target=target)
        return BuiltCommand(
            normalized,
            COMMAND_CE,
            subtype,
            {"alarm_type": subtype, "enabled": bool(_normalize_enabled(enabled)), "target": target},
            frame,
        )
    raise ValueError(f"unsupported command_type: {command_type}")


@dataclass(frozen=True)
class CommandResult:
    command: DeviceCommand
    duplicate: bool = False


def _device_for_command(db: Session, imei: str) -> Device:
    device = db.scalar(select(Device).where(Device.imei == imei).with_for_update())
    if device is None:
        device = Device(imei=imei, model="B2315P")
        db.add(device)
        db.flush()
    return device


def _touch_command(row: DeviceCommand, when: Optional[datetime] = None) -> None:
    row.updated_at = when or datetime.now(timezone.utc)


def enqueue_command(
    db: Session,
    *,
    imei: str,
    command: BuiltCommand,
    max_attempts: int = 3,
) -> CommandResult:
    """Persist a command; no socket write occurs here."""

    if not re.fullmatch(r"\d{14,20}", imei):
        raise ValueError("imei must contain 14 to 20 digits")
    max_attempts_value = _bounded_int(max_attempts, name="max_attempts", minimum=1, maximum=20)
    device = _device_for_command(db, imei)
    row = DeviceCommand(
        device_id=device.id,
        imei=imei,
        command_type=command.command_type,
        message_id=command.message_id,
        subtype=command.subtype,
        payload=command.payload,
        frame_hex=command.frame.hex().upper(),
        max_attempts=max_attempts_value,
        status="pending",
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise
    return CommandResult(row, duplicate=False)


def claim_pending_commands(
    db: Session,
    *,
    imei: str,
    worker_id: str,
    limit: int = 10,
    claim_ttl_seconds: int = 30,
) -> list[DeviceCommand]:
    """Atomically reserve pending commands for one TCP login window.

    Stale ``claimed``/``sent`` rows are returned to pending before selecting;
    this gives a bounded retry when a short connection disappears before the
    worker can report feedback.
    """

    limit_value = _bounded_int(limit, name="limit", minimum=1, maximum=100)
    ttl_value = _bounded_int(claim_ttl_seconds, name="claim_ttl_seconds", minimum=1, maximum=3600)
    now = datetime.now(timezone.utc)
    # A command that exhausted its bounded retry budget is terminal; do not
    # leave it forever in claimed/sent merely because its lease expired.
    db.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.imei == imei,
            DeviceCommand.status.in_(("claimed", "sent")),
            DeviceCommand.claim_expires_at.is_not(None),
            DeviceCommand.claim_expires_at < now,
            DeviceCommand.attempts >= DeviceCommand.max_attempts,
        )
        .values(
            status="failed",
            claimed_at=None,
            claim_expires_at=None,
            claimed_by=None,
            sent_at=None,
            last_error="claim lease expired after max attempts",
            updated_at=now,
        )
    )
    db.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.imei == imei,
            DeviceCommand.status.in_(("claimed", "sent")),
            DeviceCommand.claim_expires_at.is_not(None),
            DeviceCommand.claim_expires_at < now,
            DeviceCommand.attempts < DeviceCommand.max_attempts,
        )
        .values(
            status="pending",
            available_at=now,
            claimed_at=None,
            claim_expires_at=None,
            claimed_by=None,
            sent_at=None,
            updated_at=now,
        )
    )
    rows = db.scalars(
        select(DeviceCommand)
        .where(
            DeviceCommand.imei == imei,
            DeviceCommand.status == "pending",
            DeviceCommand.available_at <= now,
            DeviceCommand.attempts < DeviceCommand.max_attempts,
        )
        .order_by(DeviceCommand.created_at.asc(), DeviceCommand.id.asc())
        .limit(limit_value)
        .with_for_update(skip_locked=True)
    ).all()
    expires = now + timedelta(seconds=ttl_value)
    for row in rows:
        row.status = "claimed"
        row.attempts += 1
        row.claimed_at = now
        row.claim_expires_at = expires
        row.claimed_by = worker_id
        _touch_command(row, now)
    db.commit()
    return rows


def mark_command_sent(db: Session, command_id: int) -> DeviceCommand:
    row = db.scalar(select(DeviceCommand).where(DeviceCommand.id == command_id).with_for_update())
    if row is None:
        raise ValueError("command not found")
    if row.status == "claimed":
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc)
        _touch_command(row, row.sent_at)
        db.commit()
        db.refresh(row)
    return row


def acknowledge_command(
    db: Session,
    command_id: int,
    *,
    message_ids: Optional[Iterable[int]] = None,
) -> DeviceCommand:
    """Mark a command executed only after matching 0xC0 feedback.

    The feedback frame may identify a top-level message (0x17/0xCE) or a CE
    subtype, so either is accepted.  If a worker sends no IDs, the call is
    treated as an explicit worker assertion for compatibility with older TCP
    workers; browser clients cannot call this endpoint without the worker
    token.
    """

    row = db.scalar(select(DeviceCommand).where(DeviceCommand.id == command_id).with_for_update())
    if row is None:
        raise ValueError("command not found")
    ids = [] if message_ids is None else [
        _bounded_int(value, name="message_id", minimum=0, maximum=0xFF)
        for value in message_ids
    ]
    if not ids:
        raise ValueError("message_ids from a 0xC0 feedback frame are required")
    existing_ids = list(row.feedback_message_ids or [])
    for value in ids:
        if value not in existing_ids:
            existing_ids.append(value)
    row.feedback_message_ids = existing_ids
    if row.status != "acknowledged":
        expected = {row.message_id}
        if row.subtype is not None:
            expected.add(row.subtype)
        if expected.intersection(ids) and row.status in {"claimed", "sent"}:
            # A matching protocol ID cannot prove execution for a command
            # that was never reserved/sent by this worker. Keep the feedback
            # IDs for audit, but only acknowledge an in-flight command.
            row.status = "acknowledged"
            row.acknowledged_at = row.acknowledged_at or datetime.now(timezone.utc)
            row.claim_expires_at = None
            row.last_error = None
            _touch_command(row, row.acknowledged_at)
    db.commit()
    db.refresh(row)
    return row


def acknowledge_feedback(
    db: Session,
    *,
    imei: str,
    message_ids: Iterable[int],
) -> list[DeviceCommand]:
    """Apply one 0xC0 feedback list to commands for an IMEI.

    A C0 frame reports protocol message IDs, not database command IDs.  The
    worker therefore submits the IMEI and all IDs from the frame; matching
    claimed/sent rows are acknowledged atomically.  A CE feedback (0xCE) is
    sufficient for any CE01/CE02/CE07/CE08/CE19/CE20 command, while 0x17
    matches only the location-frequency command.
    """

    ids = [
        _bounded_int(value, name="message_id", minimum=0, maximum=0xFF)
        for value in message_ids
    ]
    if not ids:
        return []
    rows = db.scalars(
        select(DeviceCommand)
        .where(
            DeviceCommand.imei == imei,
            DeviceCommand.status.in_(("claimed", "sent")),
        )
        .order_by(DeviceCommand.created_at.asc(), DeviceCommand.id.asc())
        .with_for_update()
    ).all()
    acknowledged: list[DeviceCommand] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        expected = {row.message_id}
        if row.message_id == COMMAND_CE and row.subtype is not None:
            expected.add(row.subtype)
        if not expected.intersection(ids):
            continue
        feedback = list(row.feedback_message_ids or [])
        for value in ids:
            if value not in feedback:
                feedback.append(value)
        row.feedback_message_ids = feedback
        row.status = "acknowledged"
        row.acknowledged_at = row.acknowledged_at or now
        row.claim_expires_at = None
        row.last_error = None
        _touch_command(row, row.acknowledged_at)
        acknowledged.append(row)
    db.commit()
    for row in acknowledged:
        db.refresh(row)
    return acknowledged


def fail_command(db: Session, command_id: int, error: str) -> DeviceCommand:
    row = db.scalar(select(DeviceCommand).where(DeviceCommand.id == command_id).with_for_update())
    if row is None:
        raise ValueError("command not found")
    row.last_error = str(error)[:2000]
    if row.attempts >= row.max_attempts:
        row.status = "failed"
        row.claimed_at = None
        row.claim_expires_at = None
        row.claimed_by = None
        row.sent_at = None
    else:
        row.status = "pending"
        row.available_at = datetime.now(timezone.utc)
        row.claimed_at = None
        row.claim_expires_at = None
        row.claimed_by = None
        row.sent_at = None
    _touch_command(row)
    db.commit()
    db.refresh(row)
    return row

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_PROTOCOL_IDS_BY_EVENT_TYPE = {
    "heartbeat": {249},
    "alarm": {2, 22, 33},
    "location": {3, 21, 164, 214},
    "sleep": {197},
    "config_snapshot": {233},
}


def normalize_protocol_message_id(value: Any, expected_type: Optional[str] = None) -> int:
    """Normalize parser message-id representations to a numeric byte.

    The TCP parser has historically emitted both hexadecimal strings (``0xA4``
    or ``A4``) and decimal strings/integers.  Keeping this conversion in one
    place means each event schema validates the same canonical value while
    still rejecting malformed or out-of-range protocol IDs.
    """

    if isinstance(value, bool) or value is None:
        raise ValueError("message_id must be a protocol byte")
    if isinstance(value, int):
        candidates = [value]
    elif isinstance(value, str):
        text = value.strip().upper()
        if not text:
            raise ValueError("message_id must be a protocol byte")
        try:
            if text.startswith("0X"):
                candidates = [int(text[2:], 16)]
            else:
                candidates = []
                if text.isdigit():
                    candidates.append(int(text, 10))
                if all(character in "0123456789ABCDEF" for character in text):
                    hexadecimal = int(text, 16)
                    if hexadecimal not in candidates:
                        candidates.append(hexadecimal)
        except ValueError as exc:
            raise ValueError("message_id must be a protocol byte") from exc
    else:
        raise ValueError("message_id must be a protocol byte")
    candidates = [candidate for candidate in candidates if 0 <= candidate <= 255]
    if not candidates:
        raise ValueError("message_id must be between 0 and 255")
    if expected_type:
        allowed = _PROTOCOL_IDS_BY_EVENT_TYPE.get(expected_type)
        if allowed:
            for candidate in candidates:
                if candidate in allowed:
                    return candidate
    return candidates[0]


class HealthIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imei: str = Field(pattern=r"^\d{14,20}$")
    message_type: Literal[50]
    collected_at: datetime
    heart_rate: Optional[int] = Field(default=None, ge=20, le=250)
    blood_oxygen: Optional[int] = Field(default=None, ge=0, le=100)
    body_temperature: Optional[Decimal] = Field(default=None, ge=Decimal("16.0"), le=Decimal("60.0"))
    wrist_temperature: Optional[Decimal] = Field(default=None, ge=Decimal("16.0"), le=Decimal("60.0"))
    diastolic: Optional[int] = Field(default=None, ge=20, le=250)
    systolic: Optional[int] = Field(default=None, ge=20, le=250)
    steps: Optional[int] = Field(default=None, ge=0)
    raw_hex: str = Field(pattern=r"^(?:[0-9A-Fa-f]{2})+$")

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value.astimezone(__import__("datetime").timezone.utc)

    @field_validator("raw_hex")
    @classmethod
    def normalize_raw_hex(cls, value: str) -> str:
        return value.upper()


class HealthIngestResponse(BaseModel):
    status: str
    duplicate: bool
    event_hash: str
    record_id: Optional[int] = None


class HeartbeatIngestRequest(BaseModel):
    """Canonical representation of a decoded B2315P F9 frame.

    The TCP parser historically emitted ``battery_value``, ``signal_strength``
    and ``other_value``.  The aliases below accept those names while exposing a
    stable API contract to the database service.  Percentages are optional and
    are never guessed from the four/five-level or voltage encodings.
    """

    model_config = ConfigDict(extra="ignore")

    imei: str = Field(pattern=r"^\d{14,20}$")
    message_id: Literal["0xF9"] = "0xF9"
    event_type: Literal["heartbeat"] = "heartbeat"
    collected_at: datetime
    battery_type: Optional[int] = Field(default=None, ge=0, le=255)
    battery_raw_value: Optional[int] = Field(default=None, ge=0, le=65535)
    battery_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    signal_type: Optional[int] = Field(default=None, ge=0, le=255)
    signal_raw_value: Optional[int] = Field(default=None, ge=-32768, le=32767)
    signal_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    steps_type: Optional[int] = Field(default=None, ge=0, le=255)
    steps_value: Optional[int] = Field(default=None, ge=0)
    raw_hex: str = Field(pattern=r"^(?:[0-9A-Fa-f]{2})+$")

    @model_validator(mode="before")
    @classmethod
    def normalize_protocol_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)

        raw_message_id = data.get("message_id", data.get("message_type", "0xF9"))
        if isinstance(raw_message_id, str):
            normalized_message_id = raw_message_id.strip().upper()
            if normalized_message_id in {"F9", "0XF9", "249"}:
                data["message_id"] = "0xF9"
            else:
                raise ValueError("only B2315P F9 heartbeat events are supported")
        else:
            try:
                if int(raw_message_id) != 249:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("only B2315P F9 heartbeat events are supported")
            data["message_id"] = "0xF9"

        event_type = data.get("event_type", data.get("type", "heartbeat"))
        if isinstance(event_type, str):
            data["event_type"] = event_type.strip().lower()
        else:
            data["event_type"] = event_type

        for canonical, legacy in (
            ("battery_raw_value", "battery_value"),
            ("signal_raw_value", "signal_strength"),
            ("steps_type", "other_type"),
            ("steps_value", "other_value"),
        ):
            if canonical in data and legacy in data:
                if data[canonical] is not None and data[legacy] is not None:
                    if data[canonical] != data[legacy]:
                        raise ValueError(f"conflicting {canonical} and {legacy}")
            if data.get(canonical) is None and legacy in data:
                data[canonical] = data[legacy]

        # Remove legacy keys so ``extra=ignore`` does not hide a conflicting
        # value and so model_dump() contains only canonical names.
        data.pop("message_type", None)
        data.pop("type", None)
        data.pop("battery_value", None)
        data.pop("signal_strength", None)
        data.pop("other_type", None)
        data.pop("other_value", None)
        return data

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("raw_hex")
    @classmethod
    def normalize_raw_hex(cls, value: str) -> str:
        return value.upper()


class HeartbeatIngestResponse(BaseModel):
    status: str
    duplicate: bool
    event_hash: str
    record_id: Optional[int] = None
    event_type: Literal["heartbeat"] = "heartbeat"
    message_id: Literal["0xF9"] = "0xF9"


class HeartbeatRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imei: str
    message_id: Literal["0xF9"]
    event_type: Literal["heartbeat"]
    collected_at: datetime
    received_at: datetime
    battery_type: Optional[int] = None
    battery_raw_value: Optional[int] = None
    battery_percent: Optional[float] = None
    signal_type: Optional[int] = None
    signal_raw_value: Optional[int] = None
    signal_percent: Optional[float] = None
    steps_type: Optional[int] = None
    steps_value: Optional[int] = None
    event_hash: str
    raw_hex: str

    @field_validator("message_id", mode="before")
    @classmethod
    def normalize_orm_message_id(cls, value: Any) -> str:
        """Normalize the numeric PostgreSQL column for direct ORM validation."""

        if isinstance(value, int) and value == 249:
            return "0xF9"
        if isinstance(value, str) and value.strip().upper() in {"F9", "0XF9", "249"}:
            return "0xF9"
        return value


class EventEnvelope(BaseModel):
    """Fields common to decoded B2315P protocol events.

    Message-specific schemas below constrain ``message_id`` and ``event_type``;
    no protocol value is synthesized when the parser did not receive it.
    """

    model_config = ConfigDict(extra="forbid")

    imei: str = Field(pattern=r"^\d{14,20}$")
    collected_at: datetime
    raw_hex: str = Field(pattern=r"^(?:[0-9A-Fa-f]{2})+$")

    @model_validator(mode="before")
    @classmethod
    def normalize_protocol_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        expected_type = data.get("event_type")
        if isinstance(expected_type, str):
            expected_type = expected_type.strip().lower()
        if "message_id" in data:
            data["message_id"] = normalize_protocol_message_id(
                data["message_id"], expected_type
            )
        elif "message_type" in data:
            # Keep the legacy key in the input so ``extra='forbid'`` rejects it
            # for event-specific payloads.  The F9 heartbeat schema owns its
            # explicit compatibility alias.
            data["message_id"] = normalize_protocol_message_id(
                data["message_type"], expected_type
            )
        if isinstance(data.get("event_type"), str):
            data["event_type"] = data["event_type"].strip().lower()
        return data

    @field_validator("collected_at")
    @classmethod
    def require_event_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("raw_hex")
    @classmethod
    def normalize_event_raw_hex(cls, value: str) -> str:
        return value.upper()


class AlarmEvent(EventEnvelope):
    message_id: Literal[2, 22, 33]
    event_type: Literal["alarm"]
    alarm_group: Optional[int] = None
    alarm_mask: Optional[int] = None
    alarm_codes: list[str] = Field(default_factory=list)
    sensor_type: Optional[int] = None
    threshold_direction: Optional[int] = None
    measured_value: Optional[Decimal] = None
    sensor_values: Optional[dict[str, Any]] = None
    parse_version: Optional[str] = Field(default=None, max_length=16)


class LocationEvent(EventEnvelope):
    message_id: Literal[3, 21, 164, 214]
    event_type: Literal["location"]
    source: str = Field(min_length=1, max_length=16)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    north_south: Optional[Literal["N", "S"]] = None
    east_west: Optional[Literal["E", "W"]] = None
    position_status: Optional[str] = Field(default=None, min_length=1, max_length=1)
    position_valid: Optional[bool] = None
    coordinate_system: Optional[str] = Field(default=None, max_length=16)
    precision_digits: Optional[int] = Field(default=None, ge=0)
    cells: Optional[list[dict[str, Any]]] = None
    wifi_access_points: Optional[list[dict[str, Any]]] = None
    beacon_groups: Optional[list[dict[str, Any]]] = None
    resolution_status: str = Field(default="direct", min_length=1, max_length=16)


class SleepEvent(EventEnvelope):
    message_id: Literal[197]
    event_type: Literal["sleep"]
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0)
    sleep_stage: Optional[int] = None

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_optional_event_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sleep timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_sleep_interval(self):
        if self.start_at is not None and self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("end_at must not be earlier than start_at")
        return self


class ConfigSnapshotEvent(EventEnvelope):
    message_id: Literal[233]
    event_type: Literal["config_snapshot"]
    location_modified: Optional[bool] = None
    location_interval_minutes: Optional[int] = Field(default=None, ge=0)
    health_modified: Optional[bool] = None
    health_interval_minutes: Optional[int] = Field(default=None, ge=0)
    timestamp_source: Literal["received_at"] = "received_at"


class EventIngestResponse(BaseModel):
    """Stable response shared by heartbeat and concern-specific events."""

    status: str
    duplicate: bool
    event_hash: str
    record_id: Optional[int] = None
    event_type: str
    # F9 historically returned ``0xF9``; newer event IDs are numeric.  The
    # union keeps that established response compatible while making all new
    # protocol IDs unambiguous.
    message_id: Union[int, str]


EventPayload = Union[
    HeartbeatIngestRequest,
    AlarmEvent,
    LocationEvent,
    SleepEvent,
    ConfigSnapshotEvent,
]


class HealthRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imei: str
    message_type: int
    collected_at: datetime
    received_at: datetime
    heart_rate: Optional[int]
    blood_oxygen: Optional[int]
    body_temperature: Optional[Decimal]
    wrist_temperature: Optional[Decimal]
    diastolic: Optional[int]
    systolic: Optional[int]
    steps: Optional[int]
    name: Optional[str] = None
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    hrv: Optional[Decimal] = None
    calories: Optional[Decimal] = None


class PaginatedHealthResponse(BaseModel):
    items: list[HealthRecordResponse]
    page: int
    page_size: int
    total: int


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imei: str
    name: Optional[str] = None
    model: str
    enabled: bool
    last_seen_at: Optional[datetime] = None
    status: str
    battery_type: Optional[int] = None
    battery_raw_value: Optional[int] = None
    battery_percent: Optional[float] = None
    signal_type: Optional[int] = None
    signal_raw_value: Optional[int] = None
    signal_percent: Optional[float] = None


class PaginatedDeviceResponse(BaseModel):
    items: list[DeviceResponse]
    page: int
    page_size: int
    total: int


class DeviceCommandRequest(BaseModel):
    """Browser-facing command request; wire bytes are built server-side."""

    model_config = ConfigDict(extra="forbid")

    imei: str = Field(pattern=r"^\d{14,20}$")
    command_type: str = Field(min_length=1, max_length=32)
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=65535)
    priority: Optional[list[Any]] = None
    alarm_type: Optional[Union[int, str]] = None
    enabled: Optional[bool] = None
    target: Optional[Union[int, str]] = None
    slots: Optional[list[dict[str, Any]]] = None
    health_type: int = Field(default=0, ge=0, le=7)
    time_unit: int = Field(default=0, ge=0, le=1)
    valid: int = Field(default=0, ge=0, le=1)
    start_time: str = Field(default="00:00", pattern=r"^\d{1,2}:\d{2}$")
    end_time: str = Field(default="23:59", pattern=r"^\d{1,2}:\d{2}$")
    max_attempts: int = Field(default=3, ge=1, le=20)


class DeviceCommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    imei: str
    command_type: str
    message_id: int
    subtype: Optional[int] = None
    payload: dict[str, Any]
    frame_hex: str
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    claimed_at: Optional[datetime] = None
    claim_expires_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    sent_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    feedback_message_ids: list[int]
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    executed: bool = False

    @model_validator(mode="after")
    def derive_executed(self) -> "DeviceCommandResponse":
        # ``executed`` is a response convenience field, never an independent
        # database value.  Derive it from the acknowledged terminal state so
        # ORM serialization cannot leave the default ``False`` in place.
        self.executed = self.status == "acknowledged"
        return self


class PaginatedCommandResponse(BaseModel):
    items: list[DeviceCommandResponse]
    page: int
    page_size: int
    total: int


class CommandClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imei: str = Field(pattern=r"^\d{14,20}$")
    worker_id: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=100)
    claim_ttl_seconds: int = Field(default=30, ge=1, le=3600)


class CommandAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_ids: list[int] = Field(min_length=1, max_length=32)

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids(cls, value: list[int]) -> list[int]:
        if any(item < 0 or item > 255 for item in value):
            raise ValueError("message_ids must contain protocol bytes")
        return value


class CommandFeedbackRequest(CommandAcknowledgeRequest):
    imei: str = Field(pattern=r"^\d{14,20}$")


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str] = None
    role: str


class AuthLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: AuthUserResponse


RoleName = Literal["admin", "operator", "viewer"]


class RoleResponse(BaseModel):
    id: int
    name: RoleName


class PaginatedRoleResponse(BaseModel):
    items: list[RoleResponse]
    page: int
    page_size: int
    total: int


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100, pattern=r"^\S+$")
    password: str = Field(min_length=6, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=100)
    role: RoleName = "viewer"
    enabled: bool = True


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: Optional[str] = Field(default=None, min_length=6, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=100)
    role: Optional[RoleName] = None
    enabled: Optional[bool] = None


class AccountResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: RoleName
    enabled: bool
    device_imeis: list[str]
    created_at: datetime
    updated_at: datetime


class PaginatedAccountResponse(BaseModel):
    items: list[AccountResponse]
    page: int
    page_size: int
    total: int


class BindingReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imeis: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("imeis")
    @classmethod
    def validate_imeis(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("imeis must not contain duplicates")
        for imei in value:
            if not __import__("re").fullmatch(r"\d{14,20}", imei):
                raise ValueError("imeis must contain valid IMEI values")
        return value


class DeviceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imei: str = Field(pattern=r"^\d{14,20}$")
    name: Optional[str] = Field(default=None, max_length=100)
    model: str = Field(default="B2315P", min_length=1, max_length=50)
    enabled: bool = True


class DeviceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=50)
    enabled: Optional[bool] = None


class DeviceBatchUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imeis: list[str] = Field(min_length=1, max_length=1000)
    name: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=50)
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def require_change(self) -> "DeviceBatchUpdateRequest":
        if self.name is None and self.model is None and self.enabled is None:
            raise ValueError("at least one device field must be changed")
        if len(set(self.imeis)) != len(self.imeis):
            raise ValueError("imeis must not contain duplicates")
        return self


class DeviceBatchUpdateResponse(BaseModel):
    updated: int


class AlarmRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    alarm_type: str = Field(min_length=1, max_length=32)
    threshold: Optional[Decimal] = None
    direction: Optional[Literal["gte", "lte"]] = None
    enabled: bool = True


class AlarmRuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    alarm_type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    threshold: Optional[Decimal] = None
    direction: Optional[Literal["gte", "lte"]] = None
    enabled: Optional[bool] = None


class AlarmRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    alarm_type: str
    threshold: Optional[Decimal] = None
    direction: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PaginatedAlarmRuleResponse(BaseModel):
    items: list[AlarmRuleResponse]
    page: int
    page_size: int
    total: int

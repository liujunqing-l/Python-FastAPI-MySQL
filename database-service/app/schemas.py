from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class PaginatedHealthResponse(BaseModel):
    items: list[HealthRecordResponse]
    page: int
    page_size: int
    total: int


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    imei: str
    name: Optional[str] = None
    model: str
    enabled: bool
    last_seen_at: Optional[datetime] = None


class PaginatedDeviceResponse(BaseModel):
    items: list[DeviceResponse]
    page: int
    page_size: int
    total: int

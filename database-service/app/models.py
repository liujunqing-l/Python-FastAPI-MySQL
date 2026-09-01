from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("imei", name="uq_devices_imei"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(50), nullable=False, default="B2315P")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RawArchive(Base):
    __tablename__ = "raw_archives"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    archive_date: Mapped[date] = mapped_column(Date, nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    oss_key: Mapped[str] = mapped_column(String(500), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compressed_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class HealthRecord(Base):
    __tablename__ = "health_records"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_health_event_date"),
        Index("ix_health_imei_collected_at", "imei", "collected_at"),
    )

    # collected_date is part of the key so the table can be PostgreSQL RANGE-partitioned.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    collected_date: Mapped[date] = mapped_column(Date, primary_key=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[int] = mapped_column(Integer, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    heart_rate: Mapped[Optional[int]] = mapped_column(Integer)
    blood_oxygen: Mapped[Optional[int]] = mapped_column(Integer)
    body_temperature: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 1))
    wrist_temperature: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 1))
    diastolic: Mapped[Optional[int]] = mapped_column(Integer)
    systolic: Mapped[Optional[int]] = mapped_column(Integer)
    steps: Mapped[Optional[int]] = mapped_column(BigInteger)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class IngestionError(Base):
    __tablename__ = "ingestion_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    imei: Mapped[Optional[str]] = mapped_column(String(20))
    error_code: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

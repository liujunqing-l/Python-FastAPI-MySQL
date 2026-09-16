from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Float,
    Identity,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# PostgreSQL owns production identifiers through identity columns. SQLite's
# INTEGER rowid variant keeps the test dialect compatible without application
# side MAX(id)+1 allocation.
IDENTITY_BIGINT = BigInteger().with_variant(Integer, "sqlite")
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("imei", name="uq_devices_imei"),)

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
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
    __table_args__ = (UniqueConstraint("archive_date", "imei", name="uq_raw_archives_date_imei"),)

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
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
    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
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


class HeartbeatRecord(Base):
    """A decoded B2315P F9 heartbeat/telemetry frame.

    The protocol uses a type byte plus a raw value for battery and signal
    fields.  We deliberately retain both pieces instead of pretending that
    every battery or signal encoding is a percentage.  ``battery_percent``
    and ``signal_percent`` are populated only when the source explicitly
    provides a percentage (or the conversion is unambiguous).
    """

    __tablename__ = "heartbeat_records"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_heartbeat_event_date"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    collected_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    # F9 is 0xF9 (249); storing the numeric ID keeps filtering/indexing cheap.
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=249)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, default="heartbeat")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    battery_type: Mapped[Optional[int]] = mapped_column(SmallInteger)
    battery_raw_value: Mapped[Optional[int]] = mapped_column(Integer)
    battery_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    signal_type: Mapped[Optional[int]] = mapped_column(SmallInteger)
    signal_raw_value: Mapped[Optional[int]] = mapped_column(Integer)
    signal_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    steps_type: Mapped[Optional[int]] = mapped_column(SmallInteger)
    steps_value: Mapped[Optional[int]] = mapped_column(BigInteger)
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class DeviceAlarm(Base):
    """Decoded alarm event from B2315P alarm frames (0x02/0x16/0x21)."""

    __tablename__ = "device_alarms"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_alarm_event_date"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_date: Mapped[date] = mapped_column(Date, nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    alarm_group: Mapped[Optional[int]] = mapped_column(Integer)
    alarm_mask: Mapped[Optional[int]] = mapped_column(Integer)
    alarm_codes: Mapped[list] = mapped_column(
        JSON_TYPE, nullable=False, default=list, server_default=text("'[]'")
    )
    sensor_type: Mapped[Optional[int]] = mapped_column(Integer)
    threshold_direction: Mapped[Optional[int]] = mapped_column(Integer)
    measured_value: Mapped[Optional[Decimal]] = mapped_column(Numeric)
    sensor_values: Mapped[Optional[dict]] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    parse_version: Mapped[Optional[str]] = mapped_column(String(16))
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class LocationRecord(Base):
    """A GPS/LBS/Wi-Fi/BLE location event, including scan-only records."""

    __tablename__ = "location_records"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_location_event_date"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_date: Mapped[date] = mapped_column(Date, nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    north_south: Mapped[Optional[str]] = mapped_column(CHAR(1))
    east_west: Mapped[Optional[str]] = mapped_column(CHAR(1))
    position_status: Mapped[Optional[str]] = mapped_column(CHAR(1))
    position_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    coordinate_system: Mapped[Optional[str]] = mapped_column(String(16))
    precision_digits: Mapped[Optional[int]] = mapped_column(SmallInteger)
    cells: Mapped[Optional[object]] = mapped_column(JSON_TYPE)
    wifi_access_points: Mapped[Optional[object]] = mapped_column(JSON_TYPE)
    beacon_groups: Mapped[Optional[object]] = mapped_column(JSON_TYPE)
    resolution_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="direct"
    )
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class SleepRecord(Base):
    """Sleep interval/summary event from the C5 protocol frame."""

    __tablename__ = "sleep_records"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_sleep_event_date"),
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at >= start_at",
            name="ck_sleep_end_after_start",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_sleep_duration_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_date: Mapped[date] = mapped_column(Date, nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    sleep_stage: Mapped[Optional[int]] = mapped_column(SmallInteger)
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class DeviceConfigSnapshot(Base):
    """E9 (233) snapshot of device upload-frequency configuration."""

    __tablename__ = "device_config_snapshots"
    __table_args__ = (
        UniqueConstraint("event_hash", "collected_date", name="uq_device_config_event_date"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_date: Mapped[date] = mapped_column(Date, nullable=False)
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=233)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    location_modified: Mapped[Optional[bool]] = mapped_column(Boolean)
    location_interval_minutes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    health_modified: Mapped[Optional[bool]] = mapped_column(Boolean)
    health_interval_minutes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    timestamp_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="received_at", server_default="received_at"
    )
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_archive_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_archives.id", ondelete="SET NULL")
    )


class DeviceCommand(Base):
    """A downlink command waiting for a short-lived TCP connection.

    Commands are deliberately persisted before a worker can claim them.  A
    ``claimed`` row means only that a worker reserved the frame; it does not
    mean the device applied it.  The state becomes ``acknowledged`` only after
    the device sends a 0xC0 feedback frame.
    """

    __tablename__ = "device_commands"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'acknowledged', 'failed', 'expired')",
            name="ck_device_commands_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_device_commands_attempts_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_device_commands_max_attempts_positive"),
        CheckConstraint("message_id IN (23, 206)", name="ck_device_commands_message_id"),
        CheckConstraint(
            "(message_id = 23 AND subtype IS NULL) OR "
            "(message_id = 206 AND subtype IN (1, 2, 7, 8, 25, 32))",
            name="ck_device_commands_subtype",
        ),
        Index("ix_device_commands_imei_status", "imei", "status", "available_at"),
        Index("ix_device_commands_pending", "status", "available_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    imei: Mapped[str] = mapped_column(String(20), nullable=False)
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 0x17 for location-frequency commands, 0xCE for CExx commands.
    message_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # CE01/CE02/CE07/CE08/CE19/CE20 subtype; null for 0x17.
    subtype: Mapped[Optional[int]] = mapped_column(SmallInteger)
    payload: Mapped[dict] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    frame_hex: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[Optional[str]] = mapped_column(String(100))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    feedback_message_ids: Mapped[list] = mapped_column(
        JSON_TYPE, nullable=False, default=list, server_default=text("'[]'")
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    """Browser-user role seeded by migration 006."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    """A browser login account; plaintext passwords never reach this model."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        Index("ix_users_role_id", "role_id"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    role: Mapped[Role] = relationship(back_populates="users")


class UserDeviceBinding(Base):
    """Many-to-many binding used to scope non-admin browser queries by IMEI."""

    __tablename__ = "user_device_bindings"
    __table_args__ = (
        Index("ix_user_device_bindings_device_id", "device_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlarmRule(Base):
    """Global alarm threshold managed by administrators."""

    __tablename__ = "alarm_rules"
    __table_args__ = (UniqueConstraint("name", name="uq_alarm_rules_name"),)

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    alarm_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric)
    direction: Mapped[Optional[str]] = mapped_column(String(4))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Keep the descending order explicit in ORM metadata as well as in the
# PostgreSQL migration.  Defining these after class construction lets us use
# actual column expressions (``.desc()``) while remaining SQLite-compatible.
Index(
    "ix_heartbeat_imei_collected_at",
    HeartbeatRecord.__table__.c.imei,
    HeartbeatRecord.__table__.c.collected_at.desc(),
)
Index("ix_heartbeat_event_hash", HeartbeatRecord.__table__.c.event_hash)
Index(
    "ix_alarm_imei_collected_at",
    DeviceAlarm.__table__.c.imei,
    DeviceAlarm.__table__.c.collected_at.desc(),
)
Index(
    "ix_alarm_status_collected_at",
    DeviceAlarm.__table__.c.status,
    DeviceAlarm.__table__.c.collected_at.desc(),
)
Index(
    "ix_location_imei_collected_at",
    LocationRecord.__table__.c.imei,
    LocationRecord.__table__.c.collected_at.desc(),
)
Index(
    "ix_sleep_imei_collected_at",
    SleepRecord.__table__.c.imei,
    SleepRecord.__table__.c.collected_at.desc(),
)
Index(
    "ix_device_config_imei_collected_at",
    DeviceConfigSnapshot.__table__.c.imei,
    DeviceConfigSnapshot.__table__.c.collected_at.desc(),
)
Index(
    "ix_device_commands_imei_created_at",
    DeviceCommand.__table__.c.imei,
    DeviceCommand.__table__.c.created_at.desc(),
)


class IngestionError(Base):
    __tablename__ = "ingestion_errors"

    id: Mapped[int] = mapped_column(IDENTITY_BIGINT, Identity(always=False), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    imei: Mapped[Optional[str]] = mapped_column(String(20))
    error_code: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(HealthRecord, "before_insert")
def _sqlite_health_identity_fallback(mapper, connection, target) -> None:
    """Provide an ID only for SQLite's composite-primary-key test table.

    PostgreSQL uses the identity sequence declared by the migration. SQLite
    cannot auto-increment a column in a composite primary key, so tests use a
    collision-resistant positive integer generated at the ORM boundary. This
    branch is never taken by the production PostgreSQL dialect.
    """

    if connection.dialect.name == "sqlite" and target.id is None:
        target.id = secrets.randbelow((1 << 63) - 1) + 1

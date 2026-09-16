from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RawArchive


@dataclass(frozen=True)
class ArchiveResult:
    status: str
    archive_date: str
    imei: str
    oss_key: str
    record_count: int
    compressed_bytes: int
    sha256: str
    archive_id: int


def _parse_spool_path(source: Path) -> tuple[str, str]:
    if source.suffix != ".jsonl" or len(source.parts) < 4:
        raise ValueError("source must match YYYY/MM/DD/IMEI.jsonl")
    imei = source.stem
    year, month, day = source.parts[-4:-1]
    if not (year.isdigit() and month.isdigit() and day.isdigit() and len(year) == 4):
        raise ValueError("source must match YYYY/MM/DD/IMEI.jsonl")
    archive_date = f"{year}-{month}-{day}"
    datetime.strptime(archive_date, "%Y-%m-%d")
    if not imei.isdigit() or not 14 <= len(imei) <= 20:
        raise ValueError("source path contains invalid IMEI")
    return archive_date, imei


def archive_spool_file(
    source: str | Path,
    bucket: Any,
    db: Session,
    oss_prefix: str = "raw",
) -> ArchiveResult:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    archive_date_text, imei = _parse_spool_path(source)
    archive_date = datetime.strptime(archive_date_text, "%Y-%m-%d").date()
    compressed = Path(str(source) + ".gz")
    record_count = sum(1 for _ in source.open("r", encoding="utf-8"))
    digest = hashlib.sha256()
    compressed.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, gzip.open(compressed, "wb") as compressed_handle:
        while chunk := source_handle.read(1024 * 1024):
            compressed_handle.write(chunk)
    with compressed.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    compressed_bytes = compressed.stat().st_size
    sha256 = digest.hexdigest()
    oss_key = f"{oss_prefix.strip('/')}/{archive_date_text.replace('-', '/')}/{imei}.jsonl.gz"

    row = db.scalar(
        select(RawArchive).where(
            RawArchive.archive_date == archive_date,
            RawArchive.imei == imei,
        )
    )
    if row is None:
        row = RawArchive(
            archive_date=archive_date,
            imei=imei,
            oss_key=oss_key,
            status="pending",
        )
        db.add(row)
    row.oss_key = oss_key
    row.record_count = record_count
    row.compressed_bytes = compressed_bytes
    row.sha256 = sha256
    row.status = "pending"
    db.commit()

    try:
        bucket.put_object_from_file(oss_key, str(compressed))
    except Exception:
        row.status = "failed"
        row.retry_count = (row.retry_count or 0) + 1
        db.commit()
        raise

    row.status = "uploaded"
    row.uploaded_at = datetime.now(timezone.utc)
    db.commit()
    source.unlink()
    compressed.unlink()
    return ArchiveResult(
        status=row.status,
        archive_date=archive_date_text,
        imei=imei,
        oss_key=oss_key,
        record_count=record_count,
        compressed_bytes=compressed_bytes,
        sha256=sha256,
        archive_id=row.id,
    )

import gzip
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, RawArchive
from app.services.archive import archive_spool_file


class FakeBucket:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.uploaded = {}

    def put_object_from_file(self, key, filename):
        self.calls.append((key, filename))
        if self.fail:
            raise RuntimeError("OSS unavailable")
        self.uploaded[key] = open(filename, "rb").read()


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_archive_compresses_uploads_and_removes_spool(tmp_path, monkeypatch):
    source = tmp_path / "2026" / "08" / "31" / "868488079852388.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text('{"event_hash":"abc","raw_hex":"AA"}\n{"raw_hex":"BB"}\n', encoding="utf-8")
    bucket = FakeBucket()
    engine = make_db()

    monkeypatch.setattr("app.services.archive._next_archive_id", lambda db: (_ for _ in ()).throw(AssertionError("manual IDs are forbidden")), raising=False)

    with Session(engine) as db:
        result = archive_spool_file(source, bucket, db, "raw")
        row = db.scalar(select(RawArchive))

    assert result.status == "uploaded"
    assert bucket.calls[0][0] == "raw/2026/08/31/868488079852388.jsonl.gz"
    assert not source.exists()
    assert not source.with_suffix(".jsonl.gz").exists()
    assert row.archive_date == date(2026, 8, 31)
    assert row.record_count == 2
    assert row.status == "uploaded"
    import io
    with gzip.open(io.BytesIO(bucket.uploaded[bucket.calls[0][0]]), "rt", encoding="utf-8") as handle:
        assert handle.readline().startswith('{"event_hash"')


def test_archive_failure_keeps_files_and_increments_retry(tmp_path):
    source = tmp_path / "2026" / "08" / "31" / "868488079852388.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text('{"raw_hex":"AA"}\n', encoding="utf-8")
    engine = make_db()

    with Session(engine) as db:
        with pytest.raises(RuntimeError):
            archive_spool_file(source, FakeBucket(fail=True), db, "raw")
        row = db.scalar(select(RawArchive))

    assert source.exists()
    assert source.with_suffix(".jsonl.gz").exists()
    assert row.status == "failed"
    assert row.retry_count == 1

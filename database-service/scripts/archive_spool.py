from __future__ import annotations

import sys
from pathlib import Path

import oss2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.archive import archive_spool_file  # noqa: E402


def main() -> int:
    required = {
        "OSS_ENDPOINT": settings.oss_endpoint,
        "OSS_BUCKET": settings.oss_bucket,
        "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        print("missing OSS settings: " + ", ".join(missing), file=sys.stderr)
        return 2

    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
    spool_dir = Path(settings.raw_spool_dir)
    failures = 0
    for source in sorted(spool_dir.glob("????/??/??/*.jsonl")):
        try:
            with SessionLocal() as db:
                result = archive_spool_file(source, bucket, db, settings.oss_prefix)
            print(f"uploaded {result.oss_key} ({result.record_count} records)")
        except Exception as exc:
            failures += 1
            print(f"failed {source}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

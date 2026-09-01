from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import engine


def main() -> int:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"database check failed: {exc}", file=sys.stderr)
        return 1

    spool = Path(settings.raw_spool_dir)
    if not spool.exists() or not spool.is_dir():
        print(f"spool directory is not usable: {spool}", file=sys.stderr)
        return 1

    missing = [
        name
        for name, value in {
            "OSS_ENDPOINT": settings.oss_endpoint,
            "OSS_BUCKET": settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        }.items()
        if not value
    ]
    if missing:
        print("missing OSS settings: " + ", ".join(missing), file=sys.stderr)
        return 1

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

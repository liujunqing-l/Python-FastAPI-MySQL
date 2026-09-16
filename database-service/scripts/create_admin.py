#!/usr/bin/env python3
"""Create or reset one browser administrator.

Example::

    python scripts/create_admin.py --username admin

The password is entered without echo by default.  An explicit ``--password``
is retained only for non-interactive secret-manager wrappers.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Allow ``python scripts/create_admin.py`` from the service root to import the
# local ``app`` package without requiring an editable installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.user_admin import create_or_reset_admin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--password",
        help="optional non-interactive password; omit this flag to enter it without echo",
    )
    parser.add_argument("--display-name")
    args = parser.parse_args()
    password = args.password or getpass.getpass("管理员密码（输入不回显）：")
    if not password:
        parser.error("password must not be empty")
    with SessionLocal() as db:
        user = create_or_reset_admin(
            db,
            username=args.username,
            password=password,
            display_name=args.display_name,
        )
    print(f"admin user ready: {user.username} (id={user.id})")


if __name__ == "__main__":
    main()

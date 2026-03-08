"""Admin bootstrap script — creates the first admin account if none exists.

Usage:
    python -m olympus.src.auth.init_admin

Reads from environment:
    OLYMPUS_DB_PATH       (default: /data/olympus.db)
    OLYMPUS_ADMIN_USERNAME (default: admin)
    OLYMPUS_ADMIN_EMAIL
    OLYMPUS_ADMIN_PASSWORD
"""
from __future__ import annotations

import asyncio
import os
import sys


async def _run() -> None:
    db_path = os.environ.get("OLYMPUS_DB_PATH", "/data/olympus.db")
    username = os.environ.get("OLYMPUS_ADMIN_USERNAME", "admin")
    email = os.environ.get("OLYMPUS_ADMIN_EMAIL", "")
    password = os.environ.get("OLYMPUS_ADMIN_PASSWORD", "")

    if not email or not password:
        print("ERROR: OLYMPUS_ADMIN_EMAIL and OLYMPUS_ADMIN_PASSWORD must be set.", file=sys.stderr)
        sys.exit(1)

    from olympus.src.auth.db import AuthDB
    from olympus.src.auth.security import hash_password

    auth_db = AuthDB(db_path)
    await auth_db.init()

    if await auth_db.admin_exists():
        print("Admin already exists — skipping.")
        return

    hashed = hash_password(password)
    user_id = await auth_db.create_user(username, email, hashed, is_admin=True)
    print(f"Admin created: id={user_id} username={username} email={email}")


if __name__ == "__main__":
    asyncio.run(_run())

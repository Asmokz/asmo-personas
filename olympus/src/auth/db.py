"""AuthDB — aiosqlite manager for users, refresh_tokens, invite_tokens."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    email           TEXT    NOT NULL UNIQUE,
    hashed_password TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0,
    ip_address  TEXT,
    user_agent  TEXT
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT    NOT NULL UNIQUE,
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    used_by     INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_rt_user    ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_rt_hash    ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_invite_tok ON invite_tokens(token);
"""


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthDB:
    """Async SQLite manager for auth tables (shares the olympus.db file)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_CREATE_SQL)
            await db.commit()
        logger.info("auth_db_initialised", path=self._db_path)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def create_user(
        self,
        username: str,
        email: str,
        hashed_password: str,
        is_admin: bool = False,
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "INSERT INTO users (username, email, hashed_password, is_admin) VALUES (?, ?, ?, ?)",
                (username, email, hashed_password, int(is_admin)),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def update_password(self, user_id: int, hashed_password: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE users SET hashed_password = ? WHERE id = ?",
                (hashed_password, user_id),
            )
            await db.commit()

    async def update_last_login(self, user_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id,),
            )
            await db.commit()

    async def admin_exists(self) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE is_admin = 1"
            ) as cur:
                row = await cur.fetchone()
        return bool(row and row[0] > 0)

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    async def store_refresh_token(
        self,
        user_id: int,
        raw_token: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        token_hash = _hash_token(raw_token)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, ip_address, user_agent) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, token_hash, expires_at.isoformat(), ip_address, user_agent),
            )
            await db.commit()

    async def get_refresh_token(self, raw_token: str) -> Optional[dict]:
        token_hash = _hash_token(raw_token)
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ? AND revoked = 0",
                (token_hash,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def revoke_refresh_token(self, raw_token: str) -> None:
        token_hash = _hash_token(raw_token)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            await db.commit()

    async def revoke_all_user_tokens(self, user_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Invite tokens
    # ------------------------------------------------------------------

    async def create_invite_token(
        self, raw_token: str, created_by: int, expires_at: datetime
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO invite_tokens (token, created_by, expires_at) VALUES (?, ?, ?)",
                (raw_token, created_by, expires_at.isoformat()),
            )
            await db.commit()

    async def get_invite_token(self, raw_token: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM invite_tokens WHERE token = ? AND used = 0",
                (raw_token,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def consume_invite_token(self, raw_token: str, used_by: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE invite_tokens SET used = 1, used_by = ? WHERE token = ?",
                (used_by, raw_token),
            )
            await db.commit()

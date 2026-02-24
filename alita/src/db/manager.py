"""Async SQLite CRUD wrapper for Alita's persistent memory."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
import structlog

from .models import CREATE_TABLES_SQL

logger = structlog.get_logger()


class AlitaDbManager:
    """Manages Alita's SQLite database (preferences, history, reminders)."""

    def __init__(self, db_path: str = "/data/alita.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Create tables and run startup cleanup."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(CREATE_TABLES_SQL)
            await db.commit()
        await self.cleanup_old_conversations(days=7)
        logger.info("db_initialised", path=self._db_path)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    async def get_preference(self, key: str) -> Optional[str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_preference(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (key, value),
            )
            await db.commit()

    async def list_preferences(self) -> dict[str, str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT key, value FROM preferences ORDER BY key"
            ) as cur:
                rows = await cur.fetchall()
                return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    async def save_message(self, channel_id: str, role: str, content: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO conversation_history (channel_id, role, content) VALUES (?, ?, ?)",
                (str(channel_id), role, content),
            )
            await db.commit()

    async def get_conversation_history(
        self, channel_id: str, limit: int = 50
    ) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT role, content FROM conversation_history "
                "WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?",
                (str(channel_id), limit),
            ) as cur:
                rows = await cur.fetchall()
        # Reverse to chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    async def cleanup_old_conversations(self, days: int = 7) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                "DELETE FROM conversation_history WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            await db.commit()
            deleted = result.rowcount
        if deleted:
            logger.info("conversation_cleanup", deleted=deleted, days=days)
        return deleted

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------

    async def add_reminder(self, content: str, due_at: Optional[str] = None) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "INSERT INTO reminders (content, due_at) VALUES (?, ?)",
                (content, due_at),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def get_pending_reminders(self) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, content, due_at, created_at FROM reminders "
                "WHERE completed = FALSE ORDER BY due_at NULLS LAST, created_at"
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"id": r[0], "content": r[1], "due_at": r[2], "created_at": r[3]}
            for r in rows
        ]

    async def complete_reminder(self, reminder_id: int) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                "UPDATE reminders SET completed = TRUE WHERE id = ?", (reminder_id,)
            )
            await db.commit()
            return result.rowcount > 0

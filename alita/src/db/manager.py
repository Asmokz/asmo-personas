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

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_portfolio(self) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT symbol, shares, avg_price, label FROM portfolio ORDER BY symbol"
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"symbol": r[0], "shares": r[1], "avg_price": r[2], "label": r[3]}
            for r in rows
        ]

    async def get_position(self, symbol: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT symbol, shares, avg_price, label FROM portfolio WHERE symbol = ?",
                (symbol.upper(),),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return {"symbol": row[0], "shares": row[1], "avg_price": row[2], "label": row[3]}
        return None

    async def upsert_position(
        self, symbol: str, shares: float, avg_price: float, label: Optional[str] = None
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO portfolio (symbol, shares, avg_price, label, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "  shares = excluded.shares, "
                "  avg_price = excluded.avg_price, "
                "  label = COALESCE(excluded.label, label), "
                "  updated_at = CURRENT_TIMESTAMP",
                (symbol.upper(), shares, avg_price, label),
            )
            await db.commit()

    async def delete_position(self, symbol: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                "DELETE FROM portfolio WHERE symbol = ?", (symbol.upper(),)
            )
            await db.commit()
            return result.rowcount > 0

    async def portfolio_is_empty(self) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM portfolio") as cur:
                row = await cur.fetchone()
        return row[0] == 0  # type: ignore[index]

    # ------------------------------------------------------------------
    # Long-term memory vectors
    # ------------------------------------------------------------------

    async def save_conversation_vector(
        self,
        user_msg: str,
        assistant_msg: str,
        embedding: list[float],
        channel_id: Optional[str] = None,
    ) -> None:
        import json
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO conversation_vectors "
                "(user_msg, assistant_msg, embedding, channel_id) VALUES (?, ?, ?, ?)",
                (user_msg, assistant_msg, json.dumps(embedding), channel_id),
            )
            await db.commit()

    async def get_all_conversation_vectors(
        self, limit: int = 500, channel_id: Optional[str] = None
    ) -> list[dict]:
        import json
        async with aiosqlite.connect(self._db_path) as db:
            if channel_id is not None:
                async with db.execute(
                    "SELECT id, user_msg, assistant_msg, embedding, channel_id, created_at "
                    "FROM conversation_vectors WHERE channel_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (channel_id, limit),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT id, user_msg, assistant_msg, embedding, channel_id, created_at "
                    "FROM conversation_vectors ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ) as cur:
                    rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "user_msg": r[1],
                "assistant_msg": r[2],
                "embedding": json.loads(r[3]),
                "channel_id": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    async def count_conversation_vectors(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM conversation_vectors") as cur:
                row = await cur.fetchone()
        return row[0] if row else 0  # type: ignore[index]

"""OlympusDB — conversations and persistent message history."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL,
    title      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conv_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id      TEXT NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    tool_calls   TEXT,
    tool_call_id TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ch_conv ON conv_history(conv_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_persona ON conversations(persona_id, updated_at);
"""


class OlympusDB:
    """Async SQLite manager for Olympus conversations."""

    def __init__(self, db_path: str = "/data/olympus.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_CREATE_SQL)
            await db.commit()
        logger.info("olympus_db_initialised", path=self._db_path)

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def create_conversation(self, persona_id: str, title: Optional[str] = None) -> str:
        """Create a new conversation and return its UUID."""
        conv_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO conversations (id, persona_id, title) VALUES (?, ?, ?)",
                (conv_id, persona_id, title),
            )
            await db.commit()
        logger.info("conversation_created", id=conv_id, persona_id=persona_id)
        return conv_id

    async def get_conversations(self, persona_id: str) -> list[dict]:
        """List all conversations for a persona, most recent first."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, persona_id, title, created_at, updated_at "
                "FROM conversations WHERE persona_id = ? ORDER BY updated_at DESC",
                (persona_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "persona_id": r[1],
                "title": r[2],
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]

    async def get_conversation(self, conv_id: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, persona_id, title, created_at, updated_at "
                "FROM conversations WHERE id = ?",
                (conv_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "persona_id": row[1], "title": row[2],
                "created_at": row[3], "updated_at": row[4]}

    async def delete_conversation(self, conv_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM conv_history WHERE conv_id = ?", (conv_id,))
            result = await db.execute(
                "DELETE FROM conversations WHERE id = ?", (conv_id,)
            )
            await db.commit()
            return result.rowcount > 0

    async def update_title(self, conv_id: str, title: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, conv_id),
            )
            await db.commit()

    async def touch_conversation(self, conv_id: str) -> None:
        """Update the updated_at timestamp."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conv_id,),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def get_history(self, conv_id: str, limit: int = 20) -> list[dict]:
        """Return the most recent conversation history in chronological order.

        Loads the last `limit` messages (most recent), then reverses to
        chronological order. Ensures the result starts on a user message to
        avoid orphaned tool results confusing the LLM.
        Tool call lists are capped at 5 entries to guard against corrupted history.
        """
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT role, content, tool_calls, tool_call_id FROM conv_history "
                "WHERE conv_id = ? ORDER BY created_at DESC LIMIT ?",
                (conv_id, limit),
            ) as cur:
                rows = await cur.fetchall()

        rows = list(reversed(rows))  # back to chronological order

        result = []
        for role, content, tool_calls_json, tool_call_id in rows:
            msg: dict = {"role": role, "content": content}
            if tool_calls_json:
                try:
                    tool_calls = json.loads(tool_calls_json)
                    # Sanitise: cap tool_calls list to prevent corrupted history
                    if isinstance(tool_calls, list) and len(tool_calls) > 5:
                        tool_calls = tool_calls[:5]
                    msg["tool_calls"] = tool_calls
                except (json.JSONDecodeError, ValueError):
                    pass
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            result.append(msg)

        # Trim leading non-user messages (orphaned tool results / assistant msgs)
        # so the LLM always receives a context that starts with a user message.
        while result and result[0]["role"] != "user":
            result.pop(0)

        return result

    async def append_messages(self, conv_id: str, messages: list[dict]) -> None:
        """Persist a list of new messages to conv_history."""
        async with aiosqlite.connect(self._db_path) as db:
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
                tool_call_id = msg.get("tool_call_id")
                await db.execute(
                    "INSERT INTO conv_history (conv_id, role, content, tool_calls, tool_call_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        conv_id,
                        role,
                        content,
                        json.dumps(tool_calls) if tool_calls else None,
                        tool_call_id,
                    ),
                )
            await db.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conv_id,),
            )
            await db.commit()

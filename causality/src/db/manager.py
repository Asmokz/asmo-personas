"""Causality SQLite manager — exchanges table with rolling cleanup."""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger()


class DbManager:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS exchanges (
                id                TEXT PRIMARY KEY,
                conv_id           TEXT,
                persona           TEXT NOT NULL,
                model             TEXT NOT NULL,
                started_at        REAL NOT NULL,
                ended_at          REAL,
                duration_ms       INTEGER,
                prompt_tokens     INTEGER,
                completion_tokens INTEGER,
                tokens_per_sec    REAL,
                load_duration_ms  INTEGER,
                request_messages  TEXT,
                request_tool_names TEXT,
                response          TEXT,
                hw_before         TEXT,
                hw_after          TEXT
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_started ON exchanges(started_at DESC)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_persona ON exchanges(persona)"
        )
        await self._db.commit()

    async def cleanup_old(self, retention_days: int) -> None:
        threshold = time.time() - retention_days * 86400
        async with self._db.execute(
            "DELETE FROM exchanges WHERE started_at < ?", (threshold,)
        ) as cur:
            deleted = cur.rowcount
        await self._db.commit()
        if deleted:
            logger.info("causality_cleanup", deleted=deleted, retention_days=retention_days)

    async def insert_call_start(self, data: dict, hw_before: dict) -> None:
        await self._db.execute(
            """
            INSERT OR IGNORE INTO exchanges
              (id, conv_id, persona, model, started_at, request_messages,
               request_tool_names, hw_before)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["call_id"],
                data.get("conv_id"),
                data["persona"],
                data["model"],
                data["ts_start"],
                json.dumps(data.get("messages", []), ensure_ascii=False),
                json.dumps(data.get("tool_names", []), ensure_ascii=False),
                json.dumps(hw_before, ensure_ascii=False),
            ),
        )
        await self._db.commit()

    async def update_call_end(self, data: dict, hw_after: dict) -> None:
        await self._db.execute(
            """
            UPDATE exchanges SET
                ended_at          = ?,
                duration_ms       = ?,
                prompt_tokens     = ?,
                completion_tokens = ?,
                tokens_per_sec    = ?,
                load_duration_ms  = ?,
                response          = ?,
                hw_after          = ?
            WHERE id = ?
            """,
            (
                data["ts_end"],
                data["duration_ms"],
                data.get("prompt_tokens"),
                data.get("completion_tokens"),
                data.get("tokens_per_sec"),
                data.get("load_duration_ms"),
                json.dumps(data.get("response", {}), ensure_ascii=False),
                json.dumps(hw_after, ensure_ascii=False),
                data["call_id"],
            ),
        )
        await self._db.commit()

    async def list_exchanges(
        self,
        limit: int,
        offset: int,
        persona: str | None,
    ) -> list[dict]:
        query = "SELECT * FROM exchanges"
        params: list[Any] = []
        if persona:
            query += " WHERE persona = ?"
            params.append(persona)
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        async with self._db.execute(query, params) as cur:
            rows = await cur.fetchall()

        result = []
        json_fields = (
            "request_messages", "request_tool_names",
            "response", "hw_before", "hw_after",
        )
        for row in rows:
            d = dict(row)
            for field in json_fields:
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except Exception:
                        pass
            result.append(d)
        return result

    async def close(self) -> None:
        if self._db:
            await self._db.close()

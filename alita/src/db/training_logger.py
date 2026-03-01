"""Training data logger — captures Alita exchanges for future fine-tuning.

Each logged exchange is a full conversation snapshot in Mistral's chat format,
plus metadata (model, turns, latency, tools called).

Schema:
    training_log(id, timestamp, conv_id, channel_id,
                 system_prompt, messages, meta, quality, correction)

quality: NULL (unlabelled) | 'good' | 'bad'
correction: JSON override of the last assistant message for DPO pairs.

Export workflow (future):
    SELECT * FROM training_log WHERE quality = 'good'
    → JSONL for SFT

    SELECT * FROM training_log WHERE quality = 'bad' AND correction IS NOT NULL
    → JSONL preferred/rejected pairs for DPO
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS training_log (
    id            TEXT PRIMARY KEY,
    timestamp     TEXT NOT NULL,
    conv_id       TEXT,
    channel_id    TEXT,
    system_prompt TEXT NOT NULL,
    messages      TEXT NOT NULL,
    meta          TEXT NOT NULL,
    quality       TEXT,
    correction    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tl_quality   ON training_log(quality);
CREATE INDEX IF NOT EXISTS idx_tl_timestamp ON training_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_tl_conv_id   ON training_log(conv_id);
"""

# Skip exchanges where the final assistant reply is too short to be useful
_MIN_REPLY_LEN = 40


class TrainingLogger:
    """Async logger writing Alita exchanges to a dedicated SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Create the database and table if not already present."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_CREATE_SQL)
            await db.commit()
        logger.info("training_logger_ready", db=self._db_path)

    async def log_exchange(
        self,
        conv_id: str,
        channel_id: str,
        system_prompt: str,
        messages: list[dict],
        meta: dict,
    ) -> None:
        """Persist one exchange. quality and correction start as NULL.

        messages must be a full snapshot in Mistral chat format:
        [{"role": "user"|"assistant"|"tool", "content": ..., "tool_calls"?: ...}, ...]

        meta must contain at minimum:
        {"model": str, "turns": int, "total_ms": int, "tools_called": list[str]}
        """
        # Skip trivial exchanges
        last_assistant = next(
            (m for m in reversed(messages) if m.get("role") == "assistant"),
            None,
        )
        if not last_assistant or len(last_assistant.get("content") or "") < _MIN_REPLY_LEN:
            return

        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO training_log
                        (id, timestamp, conv_id, channel_id,
                         system_prompt, messages, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        now,
                        conv_id,
                        channel_id,
                        system_prompt,
                        json.dumps(messages, ensure_ascii=False),
                        json.dumps(meta, ensure_ascii=False),
                    ),
                )
                await db.commit()
            logger.debug(
                "training_exchange_logged",
                id=entry_id,
                tools=meta.get("tools_called"),
                turns=meta.get("turns"),
                reply_len=len(last_assistant.get("content") or ""),
            )
        except Exception as exc:
            # Non-fatal — training logging must never break the bot
            logger.warning("training_log_failed", error=str(exc))

    async def count(self) -> dict:
        """Return counts by quality label (useful for monitoring)."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT quality, COUNT(*) FROM training_log GROUP BY quality"
                ) as cur:
                    rows = await cur.fetchall()
            return {(r[0] or "unlabelled"): r[1] for r in rows}
        except Exception:
            return {}

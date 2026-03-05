"""Causality Redis subscriber — listens to asmo.causality and persists to SQLite."""
from __future__ import annotations

import asyncio
import json

import structlog

from .db.manager import DbManager
from .hardware import HardwareSampler

logger = structlog.get_logger()

CHANNEL = "asmo.causality"
RECONNECT_DELAY = 5  # seconds


class CausalitySubscriber:
    def __init__(self, db: DbManager, hw: HardwareSampler, redis_url: str) -> None:
        self._db = db
        self._hw = hw
        self._redis_url = redis_url
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                import redis.asyncio as aioredis
                r = aioredis.from_url(self._redis_url)
                async with r.pubsub() as ps:
                    await ps.subscribe(CHANNEL)
                    logger.info("causality_subscriber_ready", channel=CHANNEL)
                    async for msg in ps.listen():
                        if not self._running:
                            break
                        if msg["type"] != "message":
                            continue
                        try:
                            data = json.loads(msg["data"])
                            await self._handle(data)
                        except Exception as exc:
                            logger.error("subscriber_handle_error", error=str(exc))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.warning("subscriber_reconnecting", error=str(exc), delay=RECONNECT_DELAY)
                    await asyncio.sleep(RECONNECT_DELAY)

    async def stop(self) -> None:
        self._running = False

    async def _handle(self, data: dict) -> None:
        event = data.get("event")
        hw = self._hw.sample()

        if event == "call_start":
            await self._db.insert_call_start(data, hw)
            logger.debug("causality_call_start", call_id=data.get("call_id"), persona=data.get("persona"))
        elif event == "call_end":
            await self._db.update_call_end(data, hw)
            logger.debug(
                "causality_call_end",
                call_id=data.get("call_id"),
                duration_ms=data.get("duration_ms"),
                tokens_per_sec=data.get("tokens_per_sec"),
            )
        else:
            logger.debug("causality_unknown_event", event=event)

"""Redis subscriber — listens to FEMTO and GIORGIO events."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

import structlog

from asmo_commons.pubsub.redis_client import RedisPubSub

if TYPE_CHECKING:
    from ..bot import AlitaBot

logger = structlog.get_logger()

# Redis channels Alita subscribes to
CHANNEL_SYSTEM_ALERTS = "asmo.alerts.system"
CHANNEL_MEDIA_RATED = "asmo.media.rated"

# Redis list keys for buffering events (TTL 24h enforced on write)
LIST_SYSTEM_EVENTS = "alita:events:system"
LIST_MEDIA_EVENTS = "alita:events:media"
EVENTS_TTL = 86400  # 24h in seconds


class AlitaSubscriber:
    """Manages Alita's Redis subscriptions and event buffering."""

    def __init__(self, bot: "AlitaBot") -> None:
        self._bot = bot
        self._pubsub: Optional[RedisPubSub] = None
        self._redis = None  # raw redis client for list operations

    async def start(self, redis_url: str) -> None:
        """Connect to Redis and subscribe to channels."""
        try:
            self._pubsub = RedisPubSub(redis_url)
            await self._pubsub.connect()

            # Also get raw client for list operations (TTL buffer)
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(redis_url, decode_responses=True)

            await self._pubsub.subscribe(CHANNEL_SYSTEM_ALERTS, self._on_system_alert)
            await self._pubsub.subscribe(CHANNEL_MEDIA_RATED, self._on_media_rated)
            logger.info("alita_subscriber_started", channels=[CHANNEL_SYSTEM_ALERTS, CHANNEL_MEDIA_RATED])
        except Exception as exc:
            logger.warning("alita_subscriber_failed", error=str(exc))
            # Non-fatal — Alita works without Redis

    async def stop(self) -> None:
        if self._pubsub:
            await self._pubsub.disconnect()
        if self._redis:
            await self._redis.aclose()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_system_alert(self, event: dict) -> None:
        """Handle system alerts from FEMTO."""
        from .handlers import handle_system_alert
        await handle_system_alert(self._bot, event, self._redis, LIST_SYSTEM_EVENTS, EVENTS_TTL)

    async def _on_media_rated(self, event: dict) -> None:
        """Handle media rating events from GIORGIO."""
        from .handlers import handle_media_rated
        await handle_media_rated(event, self._redis, LIST_MEDIA_EVENTS, EVENTS_TTL)

    # ------------------------------------------------------------------
    # Buffer access (used by briefing)
    # ------------------------------------------------------------------

    async def get_recent_system_events(self, limit: int = 20) -> list[dict]:
        """Return buffered system events (last N)."""
        return await _read_list(self._redis, LIST_SYSTEM_EVENTS, limit)

    async def get_recent_media_events(self, limit: int = 10) -> list[dict]:
        """Return buffered media events (last N)."""
        return await _read_list(self._redis, LIST_MEDIA_EVENTS, limit)


async def _read_list(redis, key: str, limit: int) -> list[dict]:
    if not redis:
        return []
    import json
    try:
        raw_items = await redis.lrange(key, 0, limit - 1)
        result = []
        for raw in raw_items:
            try:
                result.append(json.loads(raw))
            except Exception:
                pass
        return result
    except Exception as exc:
        logger.warning("redis_list_read_error", key=key, error=str(exc))
        return []

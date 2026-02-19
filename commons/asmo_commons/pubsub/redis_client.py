"""Async Redis pub/sub client for inter-persona event passing."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

# Predefined channels
CHANNEL_JELLYFIN = "asmo.events.jellyfin"
CHANNEL_SYSTEM = "asmo.events.system"
CHANNEL_ALERTS = "asmo.alerts"


def make_event(source: str, event_type: str, data: Any) -> dict:
    """Build a standardised event payload."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "type": event_type,
        "data": data,
    }


class RedisPubSub:
    """Thin async wrapper around Redis pub/sub.

    Usage::

        pubsub = RedisPubSub("redis://redis:6379")
        await pubsub.connect()

        await pubsub.subscribe(CHANNEL_ALERTS, my_handler)
        await pubsub.publish(CHANNEL_SYSTEM, "femto", "metrics", {...})

        await pubsub.disconnect()
    """

    def __init__(self, redis_url: str = "redis://redis:6379") -> None:
        self.redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._subscriptions: dict[str, list[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        logger.info("redis_connected", url=self.redis_url)

    async def disconnect(self) -> None:
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        if self._redis:
            await self._redis.aclose()
        logger.info("redis_disconnected")

    # ------------------------------------------------------------------
    # Publish / Subscribe
    # ------------------------------------------------------------------

    async def publish(
        self,
        channel: str,
        source: str,
        event_type: str,
        data: Any,
    ) -> None:
        """Publish a standardised event to *channel*."""
        if not self._redis:
            raise RuntimeError("Not connected to Redis — call connect() first")
        event = make_event(source, event_type, data)
        await self._redis.publish(channel, json.dumps(event))
        logger.debug("redis_published", channel=channel, type=event_type)

    async def subscribe(self, channel: str, callback: Callable[[dict], Any]) -> None:
        """Subscribe to *channel* and call *callback* on every message.

        Multiple callbacks can be registered for the same channel.
        """
        if not self._pubsub:
            raise RuntimeError("Not connected to Redis — call connect() first")
        if channel not in self._subscriptions:
            self._subscriptions[channel] = []
            await self._pubsub.subscribe(channel)
            logger.info("redis_subscribed", channel=channel)

        self._subscriptions[channel].append(callback)

        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(
                self._listen(), name="redis-listener"
            )

    # ------------------------------------------------------------------
    # Internal listener loop
    # ------------------------------------------------------------------

    async def _listen(self) -> None:
        logger.info("redis_listener_started")
        try:
            async for raw in self._pubsub.listen():
                if raw["type"] != "message":
                    continue
                channel: str = raw["channel"]
                callbacks = self._subscriptions.get(channel, [])
                if not callbacks:
                    continue
                try:
                    event = json.loads(raw["data"])
                except json.JSONDecodeError:
                    logger.warning("redis_invalid_json", channel=channel)
                    continue
                for cb in callbacks:
                    try:
                        result = cb(event)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        logger.error(
                            "redis_callback_error",
                            channel=channel,
                            error=str(exc),
                        )
        except asyncio.CancelledError:
            logger.info("redis_listener_stopped")
            raise

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            if not self._redis:
                return False
            await self._redis.ping()
            return True
        except Exception:
            return False

"""Event handlers for Redis pub/sub messages."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from ..bot import AlitaBot

logger = structlog.get_logger()


async def handle_system_alert(
    bot: "AlitaBot",
    event: dict,
    redis,
    list_key: str,
    ttl: int,
) -> None:
    """Process a system alert from FEMTO.

    Buffers it in a Redis list and, if severity is 'critical',
    sends an immediate notification on the briefing channel.
    """
    logger.info("system_alert_received", event_type=event.get("type"), source=event.get("source"))

    # Buffer the event
    await _push_to_list(redis, list_key, event, ttl)

    # Immediate Discord notification for critical alerts
    severity = event.get("data", {}).get("severity", "warning")
    if severity == "critical":
        await _notify_discord(bot, event)


async def handle_media_rated(
    event: dict,
    redis,
    list_key: str,
    ttl: int,
) -> None:
    """Process a media rating event from GIORGIO — just buffer it."""
    logger.info(
        "media_rated_received",
        title=event.get("data", {}).get("title"),
        rating=event.get("data", {}).get("rating"),
    )
    await _push_to_list(redis, list_key, event, ttl)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _push_to_list(redis, key: str, event: dict, ttl: int) -> None:
    """Push event to Redis list and set TTL."""
    if not redis:
        return
    try:
        serialised = json.dumps(event)
        await redis.lpush(key, serialised)
        await redis.ltrim(key, 0, 99)   # keep max 100 events
        await redis.expire(key, ttl)
    except Exception as exc:
        logger.warning("redis_push_error", key=key, error=str(exc))


async def _notify_discord(bot: "AlitaBot", event: dict) -> None:
    """Send a critical alert to the briefing channel immediately."""
    channel_id = bot.settings.alita_briefing_channel_id
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    data = event.get("data", {})
    message_text = data.get("message", "Alerte système non détaillée")
    ts = event.get("timestamp", "")
    await channel.send(
        f"🚨 **Alerte FEMTO** (`{ts[:19]}`)\n{message_text}"
    )
    logger.info("critical_alert_sent_to_discord")

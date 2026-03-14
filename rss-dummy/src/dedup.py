import os

import redis
import structlog

from .models import FeedItem

log = structlog.get_logger()

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


def filter_new(items: list[FeedItem], ttl_seconds: int) -> list[FeedItem]:
    """Return only items not yet seen. Marks seen items in Redis."""
    r = get_redis()
    new_items = []
    for item in items:
        key = f"rss:seen:{item.guid}"
        result = r.set(key, "1", ex=ttl_seconds, nx=True)
        if result:
            new_items.append(item)
    return new_items


def seed_seen(items: list[FeedItem], ttl_seconds: int) -> int:
    """Mark all items as seen without returning them (silent first run).

    Uses SET NX so already-seen items are not overwritten.
    Returns the number of items seeded.
    """
    r = get_redis()
    count = 0
    for item in items:
        key = f"rss:seen:{item.guid}"
        if r.set(key, "1", ex=ttl_seconds, nx=True):
            count += 1
    return count

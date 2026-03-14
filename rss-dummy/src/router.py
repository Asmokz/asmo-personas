import json
from collections import defaultdict

import structlog

from .dedup import get_redis
from .models import FeedItem

log = structlog.get_logger()

CHANNEL_MAP = {
    "alita": "rss:alita",
    "femto": "rss:femto",
}


def publish(items: list[FeedItem]) -> None:
    """Publish each item to the Redis channel(s) for its targets."""
    r = get_redis()
    counts: dict[str, int] = defaultdict(int)

    for item in items:
        payload = json.dumps(item.__dict__)
        for target in item.targets:
            channel = CHANNEL_MAP.get(target)
            if channel:
                r.publish(channel, payload)
                counts[channel] += 1
            else:
                log.warning("unknown_target", target=target, item_guid=item.guid)

    for channel, count in counts.items():
        log.info("published", channel=channel, count=count)

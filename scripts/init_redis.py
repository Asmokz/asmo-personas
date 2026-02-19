"""Redis initialisation script — verify connectivity and seed channels.

Run once before starting the bots:
    python scripts/init_redis.py
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import redis.asyncio as aioredis


async def main() -> None:
    redis_url = os.getenv("ASMO_REDIS_URL", "redis://localhost:6379")
    print(f"Connecting to Redis at {redis_url}…")

    r = aioredis.from_url(redis_url, decode_responses=True)

    # Ping
    await r.ping()
    print("✅ Redis is reachable.")

    # Publish a test event on each channel
    channels = ["asmo.events.jellyfin", "asmo.events.system", "asmo.alerts"]
    for channel in channels:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "init_script",
            "type": "init",
            "data": {"message": "Redis channel initialised"},
        }
        subscribers = await r.publish(channel, json.dumps(event))
        print(f"  📡 {channel} — {subscribers} subscriber(s) at init time")

    # Store a version key
    await r.set("asmo:version", "0.1.0")
    await r.set("asmo:init_time", datetime.now(timezone.utc).isoformat())
    print("✅ Init keys written.")

    await r.aclose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

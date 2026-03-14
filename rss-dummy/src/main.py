import logging
import os

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler

from .dedup import filter_new, seed_seen
from .fetcher import fetch_all, load_config
from .normalizer import normalize
from .router import publish

# ── Logging setup ──────────────────────────────────────────────────────────────
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
log_json = os.environ.get("LOG_JSON", "true").lower() == "true"

shared_processors = [
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]

if log_json:
    renderer = structlog.processors.JSONRenderer()
else:
    renderer = structlog.dev.ConsoleRenderer()

structlog.configure(
    processors=shared_processors + [renderer],
    wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()

# ── Job ────────────────────────────────────────────────────────────────────────


def run_job() -> None:
    log.info("job_start")
    config = load_config()
    settings = config["settings"]

    poll_hours: int = settings["poll_interval_hours"]
    ttl_seconds: int = int(poll_hours * settings["dedup_ttl_multiplier"] * 3600)
    max_chars: int = settings["max_summary_chars"]

    raw_feeds = fetch_all(config)

    all_items = []
    for feed_cfg, entries in raw_feeds:
        all_items.extend(normalize(feed_cfg, entries, max_chars))

    log.info("normalized", total=len(all_items))

    new_items = filter_new(all_items, ttl_seconds)
    log.info("dedup_done", new=len(new_items), skipped=len(all_items) - len(new_items))

    publish(new_items)
    log.info("job_done")


# ── Seed run ───────────────────────────────────────────────────────────────────


def _seed_run(config: dict) -> None:
    """Fetch all feeds and mark items as seen — no Discord publish."""
    settings = config["settings"]
    ttl_seconds: int = int(
        settings["poll_interval_hours"] * settings["dedup_ttl_multiplier"] * 3600
    )
    max_chars: int = settings["max_summary_chars"]

    log.info("seed_run_start")
    raw_feeds = fetch_all(config)
    all_items = []
    for feed_cfg, entries in raw_feeds:
        all_items.extend(normalize(feed_cfg, entries, max_chars))

    seeded = seed_seen(all_items, ttl_seconds)
    log.info("seed_run_done", total=len(all_items), seeded=seeded)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    config = load_config()
    poll_hours: int = config["settings"]["poll_interval_hours"]

    log.info("rss_dummy_starting", poll_interval_hours=poll_hours)

    # Silent seed run: mark all current items as seen without publishing.
    # Prevents a flood of old articles on first startup.
    _seed_run(config)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_job, "interval", hours=poll_hours, id="rss_poll")

    log.info("scheduler_started", interval_hours=poll_hours)
    scheduler.start()


if __name__ == "__main__":
    main()

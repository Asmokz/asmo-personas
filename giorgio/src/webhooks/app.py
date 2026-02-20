"""FastAPI application — Jellyfin webhooks + stats API.

Runs in the same asyncio event loop as the Discord bot (via asyncio.gather in
main.py), which lets webhook handlers call bot.send_rating_request() directly
with asyncio.create_task() without any cross-thread machinery.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from ..db import service as db
from .schemas import JellyfinWebhook

if TYPE_CHECKING:
    from ..bot import GiorgioBot

logger = structlog.get_logger()


def create_app(notification_users: list[str], bot: "GiorgioBot") -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        notification_users: Jellyfin usernames that receive Discord rating prompts.
        bot: The GiorgioBot instance (same event loop — safe for create_task).
    """
    app = FastAPI(title="GIORGIO API", docs_url=None, redoc_url=None)

    # ── Webhook ──────────────────────────────────────────────────────────────

    @app.post("/api/webhook")
    async def jellyfin_webhook(request: Request):
        try:
            body = await request.body()
            raw = json.loads(body)
            payload = JellyfinWebhook(**raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error("webhook_parse_error", error=str(exc))
            return {"status": "error", "detail": str(exc)}

        event_type = payload.NotificationType

        if event_type == "PlaybackStop":
            await _handle_playback_stop(payload, notification_users, bot)
            return {"status": "handled"}

        logger.info("webhook_unhandled", event=event_type)
        return {"status": "unhandled", "event": event_type}

    # ── Stats API ─────────────────────────────────────────────────────────────

    @app.get("/api/stats")
    def global_stats():
        return db.get_global_stats()

    @app.get("/api/stats/most-watched")
    def most_watched(limit: int = 10):
        return db.get_most_watched(limit=limit)

    @app.get("/api/stats/top-rated")
    def top_rated(limit: int = 10, min_ratings: int = 1):
        return db.get_top_rated(limit=limit, min_ratings=min_ratings)

    @app.get("/api/stats/recent")
    def recent_activity(limit: int = 10):
        return db.get_recent_activity(limit=limit)

    @app.get("/api/stats/user/{user_id}")
    def user_stats(user_id: str):
        stats = db.get_user_stats(user_id)
        if not stats:
            raise HTTPException(status_code=404, detail="User not found")
        return stats

    return app


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------


async def _handle_playback_stop(
    payload: JellyfinWebhook,
    notification_users: list[str],
    bot: "GiorgioBot",
) -> None:
    if not payload.PlayedToCompletion:
        logger.info(
            "playback_stopped_early",
            user=payload.NotificationUsername,
            title=payload.Name,
        )
        return

    if payload.ItemType == "Episode":
        season = payload.SeasonNumber or 0
        episode = payload.EpisodeNumber or 0
        content_name = f"{payload.SeriesName} S{season:02d}E{episode:02d}"
    else:
        content_name = f"{payload.Name} ({payload.Year})"

    logger.info("playback_completed", user=payload.NotificationUsername, title=content_name)

    # Persist for ALL users (regardless of notification setting)
    user = db.get_or_create_user(payload.UserId, payload.NotificationUsername)
    content = db.get_or_create_content(
        content_id=payload.ItemId,
        title=content_name,
        content_type=payload.ItemType.lower(),
        year=payload.Year,
        genres=payload.get_genres_list(),
        tmdb_id=payload.Provider_tmdb,
    )
    watchlog = db.create_watchlog(user.jellyfin_id, content.id)

    # Discord rating prompt only for configured users
    if payload.NotificationUsername.lower() in notification_users:
        asyncio.create_task(
            bot.send_rating_request(
                user_id=payload.UserId,
                username=payload.NotificationUsername,
                content_id=payload.ItemId,
                content_name=content_name,
                content_type=payload.ItemType,
                watchlog_id=watchlog.id,
            )
        )
    else:
        logger.info("watchlog_saved_no_notify", user=payload.NotificationUsername)

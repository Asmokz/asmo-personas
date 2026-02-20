"""GIORGIO entry point — Discord bot + FastAPI webhook server.

Both services run in the same asyncio event loop via asyncio.gather(), which
allows the webhook handler to call bot.send_rating_request() directly using
asyncio.create_task() without any cross-thread synchronisation.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog
import uvicorn

from asmo_commons.config.settings import GiorgioSettings

from .bot import GiorgioBot
from .db import service as db_service
from .webhooks.app import create_app


def configure_logging(log_level: str, json_logs: bool) -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def main() -> None:
    settings = GiorgioSettings()
    configure_logging(settings.asmo_log_level, settings.asmo_log_json)
    logger = structlog.get_logger()

    # Initialise DB connection (does NOT run migrations)
    db_service.init_db(settings.db_url)
    logger.info("db_initialised", host=settings.giorgio_db_host, db=settings.giorgio_db_name)

    # Create Discord bot
    bot = GiorgioBot(settings)

    # Create FastAPI app (bot reference shared — same event loop)
    app = create_app(
        notification_users=settings.notification_users_list,
        bot=bot,
    )

    # Configure uvicorn (runs in same loop via server.serve())
    uv_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.giorgio_api_port,
        log_level=settings.asmo_log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(uv_config)

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    async def _shutdown() -> None:
        logger.info("giorgio_stopping")
        server.should_exit = True
        if not bot.is_closed():
            await bot.close()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.create_task(_shutdown()))

    logger.info(
        "giorgio_starting",
        api_port=settings.giorgio_api_port,
        notification_users=settings.notification_users_list,
    )

    try:
        await asyncio.gather(
            bot.start(settings.giorgio_discord_token),
            server.serve(),
        )
    except Exception as exc:
        logger.error("giorgio_crashed", error=str(exc))
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

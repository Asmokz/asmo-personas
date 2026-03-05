"""ALITA entry point."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog

from asmo_commons.config.settings import AlitaSettings
from .bot import AlitaBot


def configure_logging(log_level: str, json_logs: bool) -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
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
    settings = AlitaSettings()
    configure_logging(settings.asmo_log_level, settings.asmo_log_json)
    logger = structlog.get_logger()

    bot = AlitaBot(settings)
    loop = asyncio.get_running_loop()

    async def _shutdown() -> None:
        logger.info("alita_stopping")
        if not bot.is_closed():
            await bot.close()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.create_task(_shutdown()))

    logger.info("alita_starting", model=settings.alita_ollama_model)

    try:
        await asyncio.gather(bot.start(settings.alita_discord_token))
    except Exception as exc:
        logger.error("alita_crashed", error=str(exc))
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

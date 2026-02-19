"""FEMTO entry point — setup logging and run the bot."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog

from asmo_commons.config.settings import FemtoSettings
from .bot import FemtoBot


def configure_logging(log_level: str, json_logs: bool) -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def main() -> None:
    settings = FemtoSettings()  # reads from env / .env
    configure_logging(settings.asmo_log_level, settings.asmo_log_json)

    logger = structlog.get_logger()
    logger.info("femto_starting", model=settings.asmo_ollama_model)

    bot = FemtoBot(settings)

    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("signal_received", signal=sig.name)
        loop.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        await bot.start(settings.femto_discord_token)
    except Exception as exc:
        logger.error("bot_crashed", error=str(exc))
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()
        logger.info("femto_stopped")


if __name__ == "__main__":
    asyncio.run(main())

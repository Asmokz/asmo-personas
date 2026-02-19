"""ALITA scheduler — morning briefing."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .bot import AlitaBot

logger = structlog.get_logger()


class AlitaScheduler:
    """Runs the daily morning briefing for ALITA."""

    def __init__(self, bot: "AlitaBot") -> None:
        self._bot = bot
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks.append(
            asyncio.create_task(self._run_briefing(), name="alita-briefing")
        )
        logger.info("alita_scheduler_started")

    def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

    async def _run_briefing(self) -> None:
        while True:
            await _sleep_until_hour(self._bot.settings.alita_briefing_hour)
            try:
                await self._post_briefing()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("briefing_error", error=str(exc))

    async def _post_briefing(self) -> None:
        bot = self._bot
        channel_id = bot.settings.alita_briefing_channel_id
        if not channel_id:
            return

        channel = bot.get_channel(channel_id)
        if channel is None:
            return

        async with channel.typing():
            # TODO: gather weather, calendar, stocks
            now_str = datetime.now().strftime("%A %d %B %Y")
            prompt = f"Génère le briefing matinal pour le {now_str}. Météo, agenda et points importants."

            try:
                briefing = await bot.ollama.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=bot.get_system_prompt(),
                )
            except Exception as exc:
                briefing = f"⚠️ Briefing indisponible : {exc}"

            from asmo_commons.discord.base_bot import send_long_message
            await send_long_message(channel, f"☀️ **Briefing ALITA**\n\n{briefing}")


async def _sleep_until_hour(hour: int) -> None:
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())

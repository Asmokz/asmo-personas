"""ALITA scheduler — morning briefing (weekdays at configured hour)."""
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

    # ------------------------------------------------------------------
    # Briefing loop
    # ------------------------------------------------------------------

    async def _run_briefing(self) -> None:
        while True:
            await _sleep_until_next_briefing(
                self._bot.settings.alita_briefing_hour,
                self._bot.settings.alita_briefing_weekdays_only,
            )
            try:
                channel_id = self._bot.settings.alita_briefing_channel_id
                if channel_id:
                    channel = self._bot.get_channel(channel_id)
                    if channel:
                        await self.post_briefing(channel)
                    else:
                        logger.warning("briefing_channel_not_found", channel_id=channel_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("briefing_error", error=str(exc))

    async def post_briefing(self, channel) -> None:
        """Collect all data and post the morning briefing to *channel*."""
        bot = self._bot
        now_str = datetime.now().strftime("%A %d %B %Y")
        logger.info("generating_briefing", date=now_str)

        async with channel.typing():
            # Refresh system prompt with latest prefs/reminders
            await bot._refresh_prompt()

            # Collect all data concurrently
            (
                weather_str,
                moto_str,
                portfolio_str,
                reminders_str,
            ) = await asyncio.gather(
                _safe(bot.weather.get_current_weather()),
                _safe(bot.weather.should_i_ride()),
                _safe(bot.stocks.get_portfolio_summary()),
                _safe(bot.memory.get_reminders()),
                return_exceptions=False,
            )

            # Collect recent Redis events
            system_events = await bot._subscriber.get_recent_system_events(limit=10)
            system_alerts_str = _format_system_events(system_events)

            # Build the briefing prompt
            prompt = _build_briefing_prompt(
                date=now_str,
                weather=weather_str,
                moto=moto_str,
                portfolio=portfolio_str,
                reminders=reminders_str,
                system_alerts=system_alerts_str,
            )

            try:
                briefing = await bot.ollama.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=bot.get_system_prompt(),
                )
            except Exception as exc:
                briefing = f"⚠️ Briefing indisponible (LLM) : {exc}"

            from asmo_commons.discord.base_bot import send_long_message
            await send_long_message(channel, f"☀️ **Briefing ALITA — {now_str}**\n\n{briefing}")
            logger.info("briefing_sent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe(coro) -> str:
    """Await *coro* and return its string result, or an error string on failure."""
    try:
        return await coro
    except Exception as exc:
        return f"[indisponible : {exc}]"


def _format_system_events(events: list[dict]) -> str:
    if not events:
        return "Aucune alerte système ces dernières heures."
    lines = []
    for e in events[:5]:
        ts = e.get("timestamp", "")[:19]
        data = e.get("data", {})
        msg = data.get("message", str(data))
        severity = data.get("severity", "info")
        emoji = "🚨" if severity == "critical" else "⚠️"
        lines.append(f"{emoji} [{ts}] {msg}")
    return "\n".join(lines)


def _build_briefing_prompt(
    date: str,
    weather: str,
    moto: str,
    portfolio: str,
    reminders: str,
    system_alerts: str,
) -> str:
    return (
        f"Génère le briefing matinal pour le **{date}**.\n\n"
        f"## Météo\n{weather}\n\n"
        f"## Moto\n{moto}\n\n"
        f"## Portefeuille\n{portfolio}\n\n"
        f"## Rappels\n{reminders}\n\n"
        f"## Alertes système (FEMTO)\n{system_alerts}\n\n"
        "Synthétise ces données en un briefing naturel et utile en français. "
        "Commence par ce qui est le plus important. Sois concis mais complet."
    )


async def _sleep_until_next_briefing(hour: int, weekdays_only: bool) -> None:
    """Sleep until the next briefing time, skipping weekends if configured."""
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        # Skip weekends (Mon=0 … Sun=6)
        if weekdays_only:
            while target.weekday() >= 5:  # Saturday=5, Sunday=6
                target += timedelta(days=1)

        wait = (target - now).total_seconds()
        logger.info(
            "briefing_sleep_until",
            target=target.isoformat(),
            seconds=int(wait),
            weekdays_only=weekdays_only,
        )
        await asyncio.sleep(wait)

        # After waking, double-check it's the right day
        if weekdays_only and datetime.now().weekday() >= 5:
            continue  # Weekend — loop and recalculate
        break

"""VEGAS scheduler — rapport PEA quotidien à 18h, lundi-vendredi."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .bot import VegasBot

logger = structlog.get_logger()


class VegasScheduler:
    """Rapport PEA quotidien à 18h, lundi-vendredi."""

    def __init__(self, bot: "VegasBot") -> None:
        self._bot = bot
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks.append(
            asyncio.create_task(self._run_report(), name="vegas-report")
        )
        self._tasks.append(
            asyncio.create_task(self._run_market_sync(), name="vegas-market-sync")
        )
        logger.info("vegas_scheduler_started")

    def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Rapport 18h
    # ------------------------------------------------------------------

    async def _run_report(self) -> None:
        """Boucle principale du rapport quotidien."""
        while True:
            await _sleep_until(
                self._bot.settings.vegas_report_hour,
                weekdays_only=True,
            )
            try:
                channel_id = self._bot.settings.vegas_report_channel_id
                if channel_id:
                    channel = self._bot.get_channel(channel_id)
                    if channel:
                        await self.post_pea_report(channel)
                    else:
                        logger.warning("report_channel_not_found", channel_id=channel_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("report_error", error=str(exc))

    async def post_pea_report(self, channel) -> None:
        """Collecte les performances du PEA et poste un rapport."""
        bot = self._bot
        now_str = datetime.now().strftime("%A %d %B %Y")
        logger.info("generating_pea_report", date=now_str)

        async with channel.typing():
            # Diagnostic du portefeuille
            portfolio_str = await _safe(bot.portfolio_diag.diagnose())

            # Synthèse via LLM
            prompt = _build_report_prompt(date=now_str, portfolio=portfolio_str)
            try:
                report = await bot.ollama.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=bot.get_system_prompt(),
                )
            except Exception as exc:
                report = f"Rapport indisponible (LLM) : {exc}"

            from asmo_commons.discord.base_bot import send_long_message
            await send_long_message(
                channel,
                f"**Rapport PEA VEGAS — {now_str}**\n\n{report}",
            )

            # Publier l'alerte Redis
            await bot.publisher.publish_alert(
                alert_type="report",
                message=f"Rapport PEA du {now_str}",
                data={"date": now_str},
            )
            logger.info("pea_report_sent")

    # ------------------------------------------------------------------
    # Sync marché
    # ------------------------------------------------------------------

    async def _run_market_sync(self) -> None:
        """Boucle de synchronisation des données de marché."""
        while True:
            await _sleep_until(
                self._bot.settings.vegas_market_sync_hour,
                weekdays_only=True,
            )
            try:
                logger.info("market_sync_starting")
                await self._bot.cron.sync_market_data()
                await self._bot.cron.scrape_financial_news()
                await self._bot.cron.purge_old_data()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("market_sync_error", error=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe(coro) -> str:
    """Await une coroutine et retourne son résultat ou une chaîne d'erreur."""
    try:
        return await coro
    except Exception as exc:
        return f"[indisponible : {exc}]"


def _build_report_prompt(date: str, portfolio: str) -> str:
    return (
        f"Génère le rapport PEA de clôture pour le **{date}**.\n\n"
        f"## État du portefeuille\n{portfolio}\n\n"
        "Synthétise la performance du jour, identifie les principaux mouvements, "
        "et fournis un commentaire de marché concis. "
        "Inclus le disclaimer légal habituel. Sois factuel et rigoureux."
    )


async def _sleep_until(hour: int, weekdays_only: bool = True) -> None:
    """Dort jusqu'à la prochaine occurrence de l'heure donnée (en semaine si weekdays_only)."""
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        if weekdays_only:
            while target.weekday() >= 5:
                target += timedelta(days=1)

        wait = (target - now).total_seconds()
        logger.info(
            "scheduler_sleep_until",
            target=target.isoformat(),
            seconds=int(wait),
        )
        await asyncio.sleep(wait)

        if weekdays_only and datetime.now().weekday() >= 5:
            continue
        break

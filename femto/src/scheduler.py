"""FEMTO scheduler — hourly metrics collection + daily report."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .bot import FemtoBot

logger = structlog.get_logger()


class FemtoScheduler:
    """Runs periodic background tasks for FEMTO.

    Tasks:
    - **hourly**: collect system + docker metrics, append to JSON file
    - **daily at N:00**: generate a 24h summary and post to Discord
    """

    def __init__(self, bot: "FemtoBot") -> None:
        self._bot = bot
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks.append(
            asyncio.create_task(self._run_hourly(), name="femto-hourly")
        )
        self._tasks.append(
            asyncio.create_task(self._run_daily_report(), name="femto-daily")
        )
        logger.info("scheduler_started")

    def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()
        logger.info("scheduler_stopped")

    # ------------------------------------------------------------------
    # Hourly metrics collection
    # ------------------------------------------------------------------

    async def _run_hourly(self) -> None:
        """Collect metrics every hour."""
        while True:
            try:
                await self._collect_and_store_metrics()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("hourly_metrics_error", error=str(exc))
            await asyncio.sleep(3600)

    async def _collect_and_store_metrics(self) -> dict:
        bot = self._bot
        now = datetime.now(timezone.utc)

        metrics: dict = {"timestamp": now.isoformat()}

        try:
            metrics["system"] = await bot.system_metrics.get_all_metrics()
        except Exception as exc:
            metrics["system_error"] = str(exc)

        try:
            metrics["docker"] = await bot.docker_status.get_docker_status()
        except Exception as exc:
            metrics["docker_error"] = str(exc)

        try:
            metrics["network"] = await bot.network_monitor.get_network_stats()
        except Exception as exc:
            metrics["network_error"] = str(exc)

        _append_metrics(bot.settings.femto_metrics_file, metrics)
        logger.info("metrics_collected", ts=now.isoformat())
        return metrics

    # ------------------------------------------------------------------
    # Daily report
    # ------------------------------------------------------------------

    async def _run_daily_report(self) -> None:
        """Post a 24h summary at the configured hour."""
        while True:
            await _sleep_until_hour(self._bot.settings.femto_history_report_hour)
            try:
                await self._post_daily_report()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("daily_report_error", error=str(exc))

    async def _post_daily_report(self) -> None:
        bot = self._bot
        channel_id = bot.settings.femto_report_channel_id
        if not channel_id:
            logger.warning("no_report_channel_configured")
            return

        channel = bot.get_channel(channel_id)
        if channel is None:
            logger.warning("report_channel_not_found", channel_id=channel_id)
            return

        logger.info("generating_daily_report")
        async with channel.typing():
            # Collect fresh metrics
            metrics = await self._collect_and_store_metrics()

            # Load last 24h stored history
            history_summary = _load_metrics_summary(
                bot.settings.femto_metrics_file, hours=24
            )

            sys_metrics = metrics.get("system", {})
            prompt = (
                "Génère un rapport de monitoring sur les 24 dernières heures pour le homelab ASMO-01.\n\n"
                f"**Métriques actuelles :**\n"
                f"Disque système :\n{sys_metrics.get('disk', 'N/A')}\n\n"
                f"NAS (/mnt/nas) :\n{sys_metrics.get('nas', 'N/A')}\n\n"
                f"Mémoire :\n{sys_metrics.get('memory', 'N/A')}\n\n"
                f"CPU :\n{sys_metrics.get('cpu', 'N/A')}\n\n"
                f"Uptime : {sys_metrics.get('uptime', 'N/A')}\n\n"
                f"Conteneurs :\n{metrics.get('docker', 'N/A')}\n\n"
                f"**Résumé historique (24h)** :\n{history_summary}\n\n"
                "Structure ton rapport avec : état général, points d'attention (disque NAS inclus), tendances."
            )

            try:
                report = await bot.ollama.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=bot.get_system_prompt(),
                )
            except Exception as exc:
                report = f"⚠️ Génération du rapport échouée : {exc}"

            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            header = f"📊 **Rapport FEMTO — {now_str}**\n\n"
            from asmo_commons.discord.base_bot import send_long_message

            await send_long_message(channel, header + report)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append_metrics(filepath: str, metrics: dict) -> None:
    """Append a metrics snapshot to the JSON-lines file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics) + "\n")


def _load_metrics_summary(filepath: str, hours: int = 24) -> str:
    """Load metrics entries from the last *hours* and return a short summary."""
    if not os.path.exists(filepath):
        return "Aucun historique disponible."

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    entries: list[dict] = []

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                if ts >= cutoff:
                    entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

    if not entries:
        return f"Aucune entrée dans les {hours} dernières heures."

    return f"{len(entries)} snapshots collectés. Premier : {entries[0]['timestamp']}, dernier : {entries[-1]['timestamp']}"


async def _sleep_until_hour(hour: int) -> None:
    """Sleep until the next occurrence of *hour*:00:00 local time."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    wait = (target - now).total_seconds()
    logger.info("scheduler_sleep_until", target=target.isoformat(), seconds=int(wait))
    await asyncio.sleep(wait)

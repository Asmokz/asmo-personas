"""Femto — subscriber for Causality drift alerts and pattern analysis reports."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from ..bot import FemtoBot

logger = structlog.get_logger()

CHANNEL_CAUSALITY = "asmo.alerts.causality"

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning":  "🟡",
}


class FemtoCausalitySubscriber:
    """Listens to asmo.alerts.causality and posts alerts to the Discord report channel."""

    def __init__(self, bot: "FemtoBot") -> None:
        self._bot = bot
        self._pubsub = None

    async def start(self, redis_url: str) -> None:
        try:
            from asmo_commons.pubsub.redis_client import RedisPubSub
            self._pubsub = RedisPubSub(redis_url)
            await self._pubsub.connect()
            await self._pubsub.subscribe(CHANNEL_CAUSALITY, self._on_event)
            logger.info("femto_causality_subscriber_started")
        except Exception as exc:
            logger.warning("femto_causality_subscriber_failed", error=str(exc))

    async def stop(self) -> None:
        if self._pubsub:
            await self._pubsub.disconnect()

    # ------------------------------------------------------------------

    async def _on_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        data = event.get("data", {})

        channel_id = self._bot.settings.femto_report_channel_id
        if not channel_id:
            return
        channel = self._bot.get_channel(channel_id)
        if not channel:
            return

        try:
            if event_type == "drift_alert":
                await self._post_drift_alert(channel, data)
            elif event_type == "pattern_analysis":
                await self._post_pattern_analysis(channel, data)
        except Exception as exc:
            logger.error("femto_causality_post_error", error=str(exc))

    async def _post_drift_alert(self, channel, data: dict) -> None:
        from asmo_commons.discord.base_bot import send_long_message
        severity = data.get("severity", "warning")
        emoji = _SEVERITY_EMOJI.get(severity, "⚠️")
        msg = data.get("message", "Anomalie LLM détectée")
        await send_long_message(
            channel,
            f"{emoji} **CAUSALITY — Alerte drift LLM**\n{msg}",
        )
        logger.info("femto_drift_alert_posted", alert_type=data.get("alert_type"))

    async def _post_pattern_analysis(self, channel, data: dict) -> None:
        from asmo_commons.discord.base_bot import send_long_message
        report = data.get("report", "")
        if report:
            header = "🔬 **Analyse hebdomadaire LLM — CAUSALITY**\n\n"
            await send_long_message(channel, header + report)
            logger.info("femto_pattern_analysis_posted")

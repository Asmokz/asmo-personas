"""Publisher Redis pour les alertes financières VEGAS."""
from __future__ import annotations

from typing import Any, Optional

import structlog

from asmo_commons.pubsub.redis_client import RedisPubSub

logger = structlog.get_logger()

CHANNEL_FINANCE_ALERTS = "asmo.finance.alerts"


class VegasPublisher:
    """Publie les alertes financières sur asmo.finance.alerts."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pubsub: Optional[RedisPubSub] = None

    async def connect(self) -> None:
        """Initialise la connexion Redis."""
        try:
            self._pubsub = RedisPubSub(self._redis_url)
            await self._pubsub.connect()
            logger.info("vegas_publisher_connected", channel=CHANNEL_FINANCE_ALERTS)
        except Exception as exc:
            logger.warning("vegas_publisher_connect_failed", error=str(exc))
            self._pubsub = None

    async def disconnect(self) -> None:
        if self._pubsub:
            await self._pubsub.disconnect()

    async def publish_alert(
        self,
        alert_type: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        """Publie une alerte financière sur asmo.finance.alerts.

        Types d'alerte courants :
        - "volatility" : seuil de volatilité atteint
        - "opportunity" : opportunité détectée (ex: RSI bas)
        - "sector_change" : changement sectoriel notable
        - "report" : rapport PEA quotidien

        Args:
            alert_type: Type de l'alerte.
            message: Message lisible de l'alerte.
            data: Données structurées associées (tickers, valeurs, etc.).
        """
        if not self._pubsub:
            logger.debug("vegas_publisher_no_connection", alert_type=alert_type)
            return
        try:
            await self._pubsub.publish(
                channel=CHANNEL_FINANCE_ALERTS,
                source="vegas",
                event_type=alert_type,
                data={"message": message, **data},
            )
            logger.info(
                "vegas_alert_published",
                alert_type=alert_type,
                message=message[:80],
            )
        except Exception as exc:
            logger.warning("vegas_alert_publish_failed", alert_type=alert_type, error=str(exc))

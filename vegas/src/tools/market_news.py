"""Outil accès aux news financières via le RAG dynamique."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..rag.vegas_rag import VegasRAG

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : informations issues du RAG VEGAS à titre indicatif. "
    "Vérifiez les sources originales pour les décisions financières.*"
)


class MarketNews:
    """Accès aux dernières news financières via le RAG dynamique de VEGAS."""

    def __init__(self, rag: "VegasRAG") -> None:
        self._rag = rag

    async def get_news(self, query: str, top_k: int = 5) -> str:
        """Recherche dans le RAG les news financières pertinentes à la query."""
        if not query.strip():
            return "Requête vide — précisez un sujet (ex: 'LVMH résultats', 'taux BCE')."
        try:
            result = await self._rag.search(query, top_k=top_k)
            if not result:
                return (
                    f"Aucune donnée RAG trouvée pour « {query} ».\n"
                    "La base de market intelligence est peut-être vide ou non encore synchronisée. "
                    "Utilisez `web_search` pour une recherche temps réel."
                )
            return result + _DISCLAIMER
        except Exception as exc:
            logger.error("market_news_error", query=query, error=str(exc))
            return f"Erreur lors de la recherche RAG : {exc}"

"""Outil recherche web — SearXNG integration pour VEGAS."""
from __future__ import annotations

import aiohttp
import structlog

logger = structlog.get_logger()


class VegasWebSearch:
    """Recherche web via SearXNG, orientée finance."""

    def __init__(self, searxng_url: str = "http://searxng:8080") -> None:
        self._url = searxng_url.rstrip("/")

    async def search(self, query: str, num_results: int = 5) -> str:
        """Recherche via SearXNG et retourne les résultats formatés."""
        if not query.strip():
            return "Requête vide."
        params = {
            "q": query,
            "format": "json",
            "language": "fr-FR",
            "categories": "general",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._url}/search",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"Accept": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        return f"Erreur SearXNG HTTP {resp.status}"
                    data = await resp.json()

            results = data.get("results", [])[:num_results]
            if not results:
                return f"Aucun résultat pour : {query}"

            lines = [f"Résultats de recherche pour « {query} »\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Sans titre")
                url = r.get("url", "")
                snippet = r.get("content", "").strip()[:300]
                lines.append(f"{i}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
            return "\n".join(lines)

        except Exception as exc:
            logger.error("vegas_web_search_error", query=query, error=str(exc))
            return f"Recherche indisponible : {exc}"

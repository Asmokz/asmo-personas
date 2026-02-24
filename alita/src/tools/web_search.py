"""Web search tool — SearXNG integration."""
from __future__ import annotations

import aiohttp
import structlog

logger = structlog.get_logger()


class WebSearchTool:
    """Search the web via a local SearXNG instance."""

    def __init__(self, searxng_url: str = "http://searxng:8080") -> None:
        self._url = searxng_url.rstrip("/")

    async def search(self, query: str, num_results: int = 5) -> str:
        """Search via SearXNG and return formatted results."""
        if not query.strip():
            return "❌ Requête vide."
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
                        return f"❌ Erreur SearXNG HTTP {resp.status}"
                    data = await resp.json()

            results = data.get("results", [])[:num_results]
            if not results:
                return f"📭 Aucun résultat pour : {query}"

            lines = [f"🔍 **Résultats pour « {query} »**\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Sans titre")
                url = r.get("url", "")
                snippet = r.get("content", "").strip()[:200]
                snippet_str = f"\n  _{snippet}_" if snippet else ""
                lines.append(f"**{i}.** [{title}]({url}){snippet_str}")
            return "\n".join(lines)
        except Exception as exc:
            logger.error("web_search_error", query=query, error=str(exc))
            return f"❌ Recherche indisponible : {exc}"

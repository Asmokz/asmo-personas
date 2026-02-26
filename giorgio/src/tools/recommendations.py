"""Recommendation engine — LLM-powered, enriched with DB rating history."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from asmo_commons.llm.ollama_client import OllamaClient

from .jellyfin_client import JellyfinClient
from ..db import service as db

if TYPE_CHECKING:
    from .web_search import WebSearchTool

logger = structlog.get_logger()

_REC_SYSTEM = """Tu es GIORGIO, un connaisseur passionné d'art et de cinéma, d'origine italienne.
Tu recommandes des films et séries avec enthousiasme et conviction, en t'appuyant sur
l'historique de notation de l'utilisateur et la bibliothèque Jellyfin disponible.
Tu glisses parfois des expressions italiennes pour exprimer ton enthousiasme ou ta déception.
"""


class RecommendationEngine:
    """Generate personalised media recommendations using LLM + DB history."""

    def __init__(
        self,
        jellyfin: JellyfinClient,
        ollama: OllamaClient,
        web_search: WebSearchTool | None = None,
    ) -> None:
        self._jellyfin = jellyfin
        self._ollama = ollama
        self._web_search = web_search

    async def recommend(self, mood: str | None = None, genre: str | None = None) -> str:
        """Generate a recommendation based on mood/genre + past ratings.

        Strategy: Jellyfin library first (80%). Web search is included only as
        supplementary context for when the library has nothing fitting (20%).
        """
        import asyncio

        # Build request descriptor
        query_parts = []
        if mood:
            query_parts.append(f"humeur : {mood}")
        if genre:
            query_parts.append(f"genre : {genre}")
        user_request = " | ".join(query_parts) if query_parts else "surprise-moi"

        # Fetch Jellyfin context + taste profile in parallel
        recent_task = asyncio.create_task(self._jellyfin.get_recent_items(limit=20))
        search_task = (
            asyncio.create_task(self._jellyfin.search_media(genre))
            if genre
            else None
        )

        recent = await recent_task
        library_search = (await search_task) if search_task else ""

        try:
            top_rated = db.get_top_rated(limit=8, min_ratings=1)
            if top_rated:
                top_str = ", ".join(
                    f"{r['title']} ({r['avg_rating']}/10)" for r in top_rated[:5]
                )
                taste_ctx = f"Contenus les mieux notés par l'utilisateur : {top_str}"
            else:
                taste_ctx = "Pas encore d'historique de notation disponible."
        except Exception:
            taste_ctx = "Historique de notation indisponible."

        # Web search — only if a genre/mood is specified AND web search is available
        web_ctx = ""
        if self._web_search and (mood or genre):
            web_query = f"meilleurs films séries {genre or ''} {mood or ''} recommandations".strip()
            try:
                web_results = await self._web_search.search(web_query, num_results=4)
                web_ctx = (
                    f"\n\n**Suggestions issues du web** (à utiliser UNIQUEMENT si "
                    f"la bibliothèque Jellyfin ne propose rien de pertinent) :\n{web_results}"
                )
                logger.debug("recommendation_web_enriched", query=web_query)
            except Exception as exc:
                logger.debug("recommendation_web_search_failed", error=str(exc))

        prompt = (
            f"Bibliothèque Jellyfin — ajouts récents :\n{recent}\n\n"
            + (f"Recherche dans Jellyfin pour « {genre} » :\n{library_search}\n\n" if library_search else "")
            + f"{taste_ctx}\n"
            + web_ctx
            + f"\n\nRecommande quelque chose pour : **{user_request}**\n\n"
            "PRIORITÉ : privilégie toujours un contenu présent dans Jellyfin. "
            "Indique explicitement si le contenu est disponible dans la bibliothèque. "
            "Ne suggère un contenu externe (web) qu'en dernier recours, si vraiment "
            "rien dans Jellyfin ne correspond à la demande."
        )

        try:
            return await self._ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=_REC_SYSTEM,
            )
        except Exception as exc:
            return f"❌ Recommandation impossible : {exc}"

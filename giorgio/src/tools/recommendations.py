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


def _build_taste_context(requested_genre: str | None = None) -> str:
    """Build a rich taste-profile block for the LLM from DB data.

    Combines:
    - Per-genre average ratings (loves ≥7, dislikes ≤4, neutral in between)
    - Top-rated content for the requested genre (if any)
    - Global top-rated anchors (cross-genre)
    """
    lines: list[str] = []

    # Genre taste profile
    try:
        profile = db.get_genre_taste_profile()
        if profile:
            loved = sorted(
                [(g, v) for g, v in profile.items() if v["avg_rating"] >= 7.0],
                key=lambda x: x[1]["avg_rating"], reverse=True,
            )
            disliked = sorted(
                [(g, v) for g, v in profile.items() if v["avg_rating"] <= 4.0],
                key=lambda x: x[1]["avg_rating"],
            )
            neutral = [
                (g, v) for g, v in profile.items()
                if 4.0 < v["avg_rating"] < 7.0
            ]

            lines.append("**Profil de goût par genre :**")
            if loved:
                loved_str = ", ".join(
                    f"{g} ({v['avg_rating']}/10, {v['count']} vus)" for g, v in loved[:6]
                )
                lines.append(f"  ✅ Genres appréciés : {loved_str}")
            if disliked:
                dis_str = ", ".join(
                    f"{g} ({v['avg_rating']}/10)" for g, v in disliked[:4]
                )
                lines.append(f"  ❌ Genres peu appréciés : {dis_str}")
            if neutral:
                neu_str = ", ".join(g for g, _ in neutral[:4])
                lines.append(f"  〰 Genres neutres : {neu_str}")
    except Exception as exc:
        logger.debug("taste_profile_error", error=str(exc))

    # Top rated for the requested genre
    if requested_genre:
        try:
            genre_hits = db.get_top_rated_by_genre(requested_genre, limit=5)
            if genre_hits:
                hits_str = ", ".join(
                    f"{r['title']} ({r['avg_rating']}/10)" for r in genre_hits
                )
                lines.append(
                    f"\n**Contenus {requested_genre} déjà vus et bien notés :** {hits_str}"
                )
        except Exception as exc:
            logger.debug("genre_top_rated_error", genre=requested_genre, error=str(exc))

    # Global top-rated anchors
    try:
        top_rated = db.get_top_rated(limit=6, min_ratings=1)
        if top_rated:
            top_str = ", ".join(
                f"{r['title']} ({r['avg_rating']}/10)" for r in top_rated
            )
            lines.append(f"\n**Top contenus toutes catégories :** {top_str}")
    except Exception as exc:
        logger.debug("top_rated_error", error=str(exc))

    return "\n".join(lines) if lines else "Pas encore d'historique de notation disponible."


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

        Context assembled for the LLM:
        - Genre taste profile: per-genre avg rating (loves / dislikes / neutral)
        - Top-rated content for the requested genre (if any)
        - Global top rated (cross-genre anchors)
        - Jellyfin library: genre search + recent additions
        - Web results as low-priority fallback only
        """
        import asyncio

        user_request = " | ".join(filter(None, [
            f"humeur : {mood}" if mood else "",
            f"genre : {genre}" if genre else "",
        ])) or "surprise-moi"

        # --- Parallel data fetching ---
        recent_task = asyncio.create_task(self._jellyfin.get_recent_items(limit=20))
        jf_genre_task = (
            asyncio.create_task(self._jellyfin.search_media(genre)) if genre else None
        )
        recent = await recent_task
        jf_genre_results = (await jf_genre_task) if jf_genre_task else ""

        # --- DB taste profile ---
        taste_ctx = _build_taste_context(genre)

        # --- Web search fallback ---
        web_ctx = ""
        if self._web_search and (mood or genre):
            web_query = f"meilleurs films séries {genre or ''} {mood or ''} recommandations".strip()
            try:
                web_results = await self._web_search.search(web_query, num_results=4)
                web_ctx = (
                    f"\n\n**Suggestions issues du web** "
                    f"(à utiliser UNIQUEMENT si Jellyfin ne propose rien de pertinent) :\n"
                    f"{web_results}"
                )
                logger.debug("recommendation_web_enriched", query=web_query)
            except Exception as exc:
                logger.debug("recommendation_web_search_failed", error=str(exc))

        prompt = (
            f"{taste_ctx}\n\n"
            f"Bibliothèque Jellyfin — ajouts récents :\n{recent}\n"
            + (f"\nRecherche Jellyfin pour « {genre} » :\n{jf_genre_results}\n" if jf_genre_results else "")
            + web_ctx
            + f"\n\nRecommande quelque chose pour : **{user_request}**\n\n"
            "PRIORITÉ : suggère un contenu présent dans Jellyfin en tenant compte "
            "des goûts de l'utilisateur (genres aimés/détestés ci-dessus). "
            "Indique explicitement si le contenu est disponible dans la bibliothèque. "
            "Ne suggère un contenu externe (web) qu'en dernier recours."
        )

        try:
            return await self._ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=_REC_SYSTEM,
            )
        except Exception as exc:
            return f"❌ Recommandation impossible : {exc}"

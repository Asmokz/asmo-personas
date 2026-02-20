"""Recommendation engine — LLM-powered, enriched with DB rating history."""
from __future__ import annotations

import structlog

from asmo_commons.llm.ollama_client import OllamaClient

from .jellyfin_client import JellyfinClient
from ..db import service as db

logger = structlog.get_logger()

_REC_SYSTEM = """Tu es GIORGIO, un connaisseur passionné d'art et de cinéma, d'origine italienne.
Tu recommandes des films et séries avec enthousiasme et conviction, en t'appuyant sur
l'historique de notation de l'utilisateur et la bibliothèque Jellyfin disponible.
Tu glisses parfois des expressions italiennes pour exprimer ton enthousiasme ou ta déception.
"""


class RecommendationEngine:
    """Generate personalised media recommendations using LLM + DB history."""

    def __init__(self, jellyfin: JellyfinClient, ollama: OllamaClient) -> None:
        self._jellyfin = jellyfin
        self._ollama = ollama

    async def recommend(self, mood: str | None = None, genre: str | None = None) -> str:
        """Generate a recommendation based on mood/genre + past ratings."""
        # Jellyfin library context
        recent = await self._jellyfin.get_recent_items(limit=15)

        # DB taste profile
        try:
            top_rated = db.get_top_rated(limit=8, min_ratings=1)
            if top_rated:
                top_str = ", ".join(
                    f"{r['title']} ({r['avg_rating']}/10)"
                    for r in top_rated[:5]
                )
                taste_ctx = f"Contenus les mieux notés : {top_str}"
            else:
                taste_ctx = "Pas encore d'historique de notation disponible."
        except Exception:
            taste_ctx = "Historique de notation indisponible."

        query_parts = []
        if mood:
            query_parts.append(f"humeur : {mood}")
        if genre:
            query_parts.append(f"genre : {genre}")
        user_request = " | ".join(query_parts) if query_parts else "surprise-moi"

        prompt = (
            f"Bibliothèque Jellyfin (ajouts récents) :\n{recent}\n\n"
            f"{taste_ctx}\n\n"
            f"Recommande quelque chose pour : **{user_request}**\n"
            "Justifie ton choix avec passion et indique si le contenu est dans Jellyfin."
        )

        try:
            return await self._ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=_REC_SYSTEM,
            )
        except Exception as exc:
            return f"❌ Recommandation impossible : {exc}"

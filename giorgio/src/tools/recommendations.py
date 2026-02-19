"""Recommendation engine — LLM-powered suggestions."""
from __future__ import annotations

import structlog
from asmo_commons.llm.ollama_client import OllamaClient
from .jellyfin_client import JellyfinClient

logger = structlog.get_logger()

_REC_SYSTEM = """Tu es GIORGIO, expert en recommandations culturelles.
Basé sur la bibliothèque Jellyfin disponible et les préférences de l'utilisateur,
propose des contenus pertinents avec enthousiasme et conviction.
Mentionne toujours si le contenu est disponible dans la bibliothèque locale.
"""


class RecommendationEngine:
    """Generate personalised media recommendations using the LLM."""

    def __init__(self, jellyfin: JellyfinClient, ollama: OllamaClient) -> None:
        self._jellyfin = jellyfin
        self._ollama = ollama

    async def recommend(self, mood: str | None = None, genre: str | None = None) -> str:
        """Generate a recommendation based on mood and/or genre."""
        # Fetch library context
        recent = await self._jellyfin.get_recent_items(limit=20)

        context = f"Contenu récent dans Jellyfin :\n{recent}\n\n"
        query_parts = []
        if mood:
            query_parts.append(f"humeur : {mood}")
        if genre:
            query_parts.append(f"genre : {genre}")
        user_request = " | ".join(query_parts) if query_parts else "surprise-moi"

        prompt = (
            f"{context}"
            f"Recommande quelque chose pour : **{user_request}**\n"
            "Sois enthousiaste, justifie ton choix, et indique si c'est dans Jellyfin."
        )

        try:
            return await self._ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=_REC_SYSTEM,
            )
        except Exception as exc:
            return f"❌ Recommandation impossible : {exc}"

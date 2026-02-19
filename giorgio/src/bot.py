"""GIORGIO Discord bot — media & culture."""
from __future__ import annotations

import structlog

from asmo_commons.config.settings import GiorgioSettings
from asmo_commons.discord.base_bot import BaseBot
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from .persona import SYSTEM_PROMPT
from .tools.jellyfin_client import JellyfinClient
from .tools.recommendations import RecommendationEngine

logger = structlog.get_logger()


class GiorgioBot(BaseBot):
    """GIORGIO — media & culture bot."""

    def __init__(self, settings: GiorgioSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.asmo_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
            ),
            command_prefix="!",
        )
        self.settings = settings

        self.jellyfin = JellyfinClient(
            settings.giorgio_jellyfin_url,
            settings.giorgio_jellyfin_api_key,
            settings.giorgio_jellyfin_user_id,
        )
        self.recommendations = RecommendationEngine(self.jellyfin, self.ollama)

        self._registry = ToolRegistry()
        self._register_tools()

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_registry(self) -> ToolRegistry:
        return self._registry

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register("get_recent_media", "Retourne les ajouts récents dans Jellyfin.")
        async def get_recent_media() -> str:
            return await self.jellyfin.get_recent_items()

        @reg.register(
            "search_media",
            "Cherche un film ou une série dans la bibliothèque Jellyfin.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Titre ou mot-clé à rechercher"}
                },
                "required": ["query"],
            },
        )
        async def search_media(query: str) -> str:
            return await self.jellyfin.search_media(query)

        @reg.register("get_libraries", "Liste les bibliothèques Jellyfin disponibles.")
        async def get_libraries() -> str:
            return await self.jellyfin.get_libraries()

        @reg.register(
            "get_recommendation",
            "Génère une recommandation de film/série personnalisée.",
            parameters={
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "description": "Humeur actuelle (ex: aventure, romantique, détente)"},
                    "genre": {"type": "string", "description": "Genre préféré (ex: sci-fi, thriller, comédie)"},
                },
                "required": [],
            },
        )
        async def get_recommendation(mood: str | None = None, genre: str | None = None) -> str:
            return await self.recommendations.recommend(mood, genre)

    async def close(self) -> None:
        await self.ollama.close()
        await super().close()

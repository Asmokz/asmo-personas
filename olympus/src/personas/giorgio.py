"""GiorgioPersona — GIORGIO media connoisseur in Olympus context."""
from __future__ import annotations

import structlog

from asmo_commons.config.settings import GiorgioSettings
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from giorgio.src.persona import SYSTEM_PROMPT
from giorgio.src.tools.jellyfin_client import JellyfinClient
from giorgio.src.tools.library_index import LibraryIndex
from giorgio.src.tools.recommendations import RecommendationEngine
from giorgio.src.tools.web_search import WebSearchTool
from giorgio.src.tools.stats_tools import (
    get_global_statistics,
    get_most_watched_contents,
    get_recent_watches,
    get_top_rated_contents,
)

from .base import OlympusPersona

logger = structlog.get_logger()


class GiorgioPersona(OlympusPersona):
    """GIORGIO media persona — Olympus version."""

    PERSONA_ID = "giorgio"
    PERSONA_NAME = "GIORGIO"
    PERSONA_DESCRIPTION = "Connaisseur de cinéma — Jellyfin, recommandations, statistiques"
    PERSONA_COLOR = "#9B2226"

    def __init__(self, settings: GiorgioSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.giorgio_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            )
        )
        self.settings = settings
        self.jellyfin = JellyfinClient(
            settings.giorgio_jellyfin_url,
            settings.giorgio_jellyfin_api_key,
            settings.giorgio_jellyfin_user_id,
        )
        self.web_search_tool = WebSearchTool(settings.giorgio_searxng_url)
        self.library_index = LibraryIndex(
            self.jellyfin,
            self.ollama,
            embed_model=settings.giorgio_embed_model,
            db_path=settings.giorgio_vector_db_path,
        )
        self.recommendations = RecommendationEngine(self.jellyfin, self.ollama, self.web_search_tool)

        self._registry = ToolRegistry()
        self._register_tools()

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_registry(self) -> ToolRegistry:
        return self._registry

    async def init(self) -> None:
        """Initialise the semantic library index."""
        await self.library_index.init()

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register(
            "get_top_rated",
            "Retourne les contenus les mieux notés par les utilisateurs.",
        )
        async def _top_rated() -> str:
            return await get_top_rated_contents()

        @reg.register(
            "get_most_watched",
            "Retourne les films et séries les plus regardés.",
        )
        async def _most_watched() -> str:
            return await get_most_watched_contents()

        @reg.register(
            "get_recent_watches",
            "Retourne l'activité de visionnage récente.",
        )
        async def _recent() -> str:
            return await get_recent_watches()

        @reg.register(
            "get_global_stats",
            "Retourne les statistiques globales : catalogue, visionnages, notes.",
        )
        async def _global_stats() -> str:
            return await get_global_statistics()

        @reg.register(
            "get_recent_media",
            "Retourne les ajouts récents dans la bibliothèque Jellyfin.",
        )
        async def _recent_media() -> str:
            return await self.jellyfin.get_recent_items()

        @reg.register(
            "search_media",
            "Cherche un film ou une série dans Jellyfin.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        async def _search(query: str) -> str:
            return await self.jellyfin.search_media(query)

        @reg.register(
            "get_recommendation",
            "Génère une recommandation personnalisée.",
            parameters={
                "type": "object",
                "properties": {
                    "mood": {"type": "string"},
                    "genre": {"type": "string"},
                },
                "required": [],
            },
        )
        async def _recommend(mood: str | None = None, genre: str | None = None) -> str:
            return await self.recommendations.recommend(mood, genre)

        @reg.register(
            "web_search",
            "Recherche sur le web via SearXNG.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        )
        async def _web_search(query: str, num_results: int = 5) -> str:
            return await self.web_search_tool.search(query, num_results)

        @reg.register(
            "browse_library_by_genre",
            "Parcourt la bibliothèque Jellyfin par genre.",
            parameters={
                "type": "object",
                "properties": {
                    "genres": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 12},
                },
                "required": ["genres"],
            },
        )
        async def _browse_by_genre(genres: list[str], limit: int = 12) -> str:
            return await self.jellyfin.browse_items_by_genre(genres, limit)

        @reg.register(
            "semantic_search_library",
            "Recherche sémantique dans la bibliothèque Jellyfin.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
        )
        async def _semantic_search(query: str, limit: int = 6) -> str:
            return await self.library_index.semantic_search(query, limit)

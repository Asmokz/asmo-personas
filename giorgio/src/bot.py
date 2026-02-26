"""GIORGIO Discord bot — media connoisseur with rating system and LLM chat."""
from __future__ import annotations

from typing import Optional

import discord
from discord import ButtonStyle
from discord.ext import commands
from discord.ui import Button, View
import structlog

from asmo_commons.config.settings import GiorgioSettings
from asmo_commons.discord.base_bot import BaseBot, send_long_message
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.pubsub.redis_client import RedisPubSub
from asmo_commons.tools.registry import ToolRegistry

from .persona import RATING_REACTIONS, SYSTEM_PROMPT
from .db import service as db_service
from .tools.jellyfin_client import JellyfinClient
from .tools.recommendations import RecommendationEngine
from .tools.stats_tools import (
    get_global_statistics,
    get_most_watched_contents,
    get_recent_watches,
    get_top_rated_contents,
)

logger = structlog.get_logger()


class RatingView(View):
    """Discord UI view with 1–10 rating buttons.

    Two rows of 5 buttons each.  Button colours signal quality:
    red (1-3) → grey (4-6) → blurple (7-8) → green (9-10).
    """

    def __init__(
        self,
        watchlog_id: int,
        content_name: str,
        content_type: str = "movie",
        on_rated=None,
    ) -> None:
        super().__init__(timeout=86400)  # 24 h to respond
        self.watchlog_id = watchlog_id
        self.content_name = content_name
        self.content_type = content_type
        self._on_rated = on_rated  # optional async callback(rating, name, type)

        for i in range(1, 11):
            btn = Button(
                label=str(i),
                style=self._style(i),
                custom_id=f"rating_{watchlog_id}_{i}",
                row=0 if i <= 5 else 1,
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    @staticmethod
    def _style(rating: int) -> ButtonStyle:
        if rating <= 3:
            return ButtonStyle.red
        if rating <= 6:
            return ButtonStyle.grey
        if rating <= 8:
            return ButtonStyle.blurple
        return ButtonStyle.green

    def _make_callback(self, rating: int):
        async def callback(interaction: discord.Interaction) -> None:
            # Disable all buttons immediately
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]

            reaction = RATING_REACTIONS.get(rating, "🤔 *Interessante...*")
            await interaction.response.edit_message(
                content=(
                    f"✅ Tu as noté **{self.content_name}** : **{rating}/10**\n\n{reaction}"
                ),
                view=self,
            )

            db_service.update_rating(self.watchlog_id, rating)
            logger.info("rating_saved", content=self.content_name, rating=rating)
            if self._on_rated:
                try:
                    await self._on_rated(rating, self.content_name, self.content_type)
                except Exception as exc:
                    logger.debug("on_rated_callback_error", error=str(exc))
            self.stop()

        return callback


class GiorgioBot(BaseBot):
    """GIORGIO — Italian media connoisseur with rating system and LLM chat."""

    def __init__(self, settings: GiorgioSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.asmo_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            ),
            command_prefix="!",
        )
        self.settings = settings
        self._channel_id = settings.giorgio_channel_id
        self._notification_channel: Optional[discord.abc.Messageable] = None

        self.jellyfin = JellyfinClient(
            settings.giorgio_jellyfin_url,
            settings.giorgio_jellyfin_api_key,
            settings.giorgio_jellyfin_user_id,
        )
        self.recommendations = RecommendationEngine(self.jellyfin, self.ollama)
        self.pubsub = RedisPubSub(settings.asmo_redis_url)

        self._registry = ToolRegistry()
        self._register_tools()

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_registry(self) -> ToolRegistry:
        return self._registry

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        if isinstance(message.channel, discord.DMChannel) or self.user in message.mentions:
            return True
        channel_id = self.settings.giorgio_recommendation_channel_id
        if channel_id and message.channel.id == channel_id:
            return True
        return False

    # ------------------------------------------------------------------
    # LLM tool registration
    # ------------------------------------------------------------------

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
            "Retourne les films et séries les plus regardés (épisodes agrégés par série).",
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
            "Cherche un film ou une série dans la bibliothèque Jellyfin.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Titre ou mot-clé à rechercher",
                    }
                },
                "required": ["query"],
            },
        )
        async def _search(query: str) -> str:
            return await self.jellyfin.search_media(query)

        @reg.register(
            "get_recommendation",
            "Génère une recommandation personnalisée basée sur l'historique de notation.",
            parameters={
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "description": "Humeur actuelle (aventure, romantique, détente…)",
                    },
                    "genre": {
                        "type": "string",
                        "description": "Genre préféré (sci-fi, thriller, comédie…)",
                    },
                },
                "required": [],
            },
        )
        async def _recommend(mood: str | None = None, genre: str | None = None) -> str:
            return await self.recommendations.recommend(mood, genre)

    # ------------------------------------------------------------------
    # Discord lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        self._register_prefix_commands()
        try:
            await self.pubsub.connect()
            logger.info("giorgio_pubsub_connected")
        except Exception as exc:
            logger.warning("giorgio_pubsub_unavailable", error=str(exc))
        await super().setup_hook()

    async def on_ready(self) -> None:
        await super().on_ready()
        channel = self.get_channel(self._channel_id)
        if channel:
            self._notification_channel = channel
        else:
            logger.warning("notification_channel_not_found", channel_id=self._channel_id)

    async def close(self) -> None:
        try:
            await self.pubsub.disconnect()
        except Exception:
            pass
        await self.ollama.close()
        await super().close()

    # ------------------------------------------------------------------
    # Rating notification (called by webhook via asyncio.create_task)
    # ------------------------------------------------------------------

    async def send_rating_request(
        self,
        user_id: str,
        username: str,
        content_id: str,
        content_name: str,
        content_type: str,
        watchlog_id: int,
    ) -> None:
        """Send a rating prompt to the notification channel."""
        if not self._notification_channel:
            logger.error("rating_channel_unavailable", channel_id=self._channel_id)
            return

        if content_type.lower() == "episode":
            intro = f"📺 *Ecco!* **{username}** vient de terminer **{content_name}**!"
        else:
            intro = f"🎬 *Bellissimo!* **{username}** vient de terminer **{content_name}**!"

        msg = (
            f"{intro}\n\n"
            "Alors, *caro mio*, c'était comment? Note cette œuvre de 1 à 10!\n"
            "*(1 = mamma mia quelle horreur, 10 = chef-d'œuvre absolu)*"
        )
        async def _publish_rating(rating: int, name: str, media_type: str) -> None:
            try:
                await self.pubsub.publish(
                    "asmo.media.rated",
                    source="giorgio",
                    event_type="rating",
                    data={
                        "title": name,
                        "rating": rating,
                        "media_type": media_type,
                    },
                )
            except Exception as exc:
                logger.debug("rating_publish_error", error=str(exc))

        view = RatingView(
            watchlog_id=watchlog_id,
            content_name=content_name,
            content_type=content_type,
            on_rated=_publish_rating,
        )
        await self._notification_channel.send(content=msg, view=view)
        logger.info("rating_request_sent", content=content_name, user=username)

    # ------------------------------------------------------------------
    # Prefix commands (no LLM needed)
    # ------------------------------------------------------------------

    def _register_prefix_commands(self) -> None:
        @self.command(name="stats", help="Statistiques globales du catalogue")
        async def cmd_stats(ctx: commands.Context) -> None:
            async with ctx.typing():
                result = await get_global_statistics()
                await send_long_message(ctx.channel, result)

        @self.command(name="toprated", help="Top contenus les mieux notés")
        async def cmd_toprated(ctx: commands.Context, limit: int = 10) -> None:
            async with ctx.typing():
                result = await get_top_rated_contents(limit)
                await send_long_message(ctx.channel, result)

        @self.command(name="mostwatched", help="Top contenus les plus vus")
        async def cmd_mostwatched(ctx: commands.Context, limit: int = 10) -> None:
            async with ctx.typing():
                result = await get_most_watched_contents(limit)
                await send_long_message(ctx.channel, result)

        @self.command(name="recent", help="Activité de visionnage récente")
        async def cmd_recent(ctx: commands.Context, limit: int = 10) -> None:
            async with ctx.typing():
                result = await get_recent_watches(limit)
                await send_long_message(ctx.channel, result)

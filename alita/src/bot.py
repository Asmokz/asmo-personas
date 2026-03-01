"""ALITA Discord bot — personal assistant."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import discord
import structlog
from discord.ext import commands

from asmo_commons.config.settings import AlitaSettings
from asmo_commons.discord.base_bot import BaseBot, send_long_message
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from .db.manager import AlitaDbManager
from .persona import build_system_prompt
from .pubsub.subscriber import AlitaSubscriber
from .scheduler import AlitaScheduler
from .tools.anytype import AnytypeTool
from .tools.fetch_url import FetchUrlTool
from .tools.home_assistant import HomeAssistantTool
from .tools.long_term_memory import LongTermMemory
from .tools.memory import MemoryTool
from .tools.spotify import SpotifyTool
from .tools.stocks import StocksTool
from .tools.weather import WeatherTool
from .tools.web_search import WebSearchTool

logger = structlog.get_logger()


class AlitaBot(BaseBot):
    """ALITA — personal assistant bot."""

    def __init__(self, settings: AlitaSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.alita_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            ),
            command_prefix="!",
        )
        self.settings = settings

        # Persistent memory
        self.db = AlitaDbManager(settings.alita_db_path)

        # Tools
        self.weather = WeatherTool(settings.alita_weather_api_key, settings.alita_weather_city)
        self.stocks = StocksTool(self.db)
        self.ha = HomeAssistantTool(settings.alita_ha_url, settings.alita_ha_token)
        self.web_search = WebSearchTool(settings.alita_searxng_url)
        self.spotify = SpotifyTool(
            settings.alita_spotify_client_id,
            settings.alita_spotify_client_secret,
            settings.alita_spotify_redirect_uri,
            self.db,
        )
        self.memory = MemoryTool(self.db)
        self.ltm = LongTermMemory(self.db, self.ollama, settings.alita_embed_model)
        self.fetch_url = FetchUrlTool()
        self.anytype = AnytypeTool(
            settings.alita_anytype_url,
            settings.alita_anytype_api_key,
            settings.alita_anytype_space_id,
        )

        # Registry + scheduler + pubsub
        self._registry = ToolRegistry()
        self._register_tools()
        self._scheduler = AlitaScheduler(self)
        self._subscriber = AlitaSubscriber(self)

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        # This is called synchronously by BaseBot; we return a cached version.
        # The prompt is refreshed at each briefing and on demand via _refresh_prompt().
        return self._cached_system_prompt

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Dynamic system prompt (async, includes live preferences/reminders)
    # ------------------------------------------------------------------

    _cached_system_prompt: str = build_system_prompt()

    async def _refresh_prompt(self) -> None:
        """Reload preferences and reminders into the system prompt cache."""
        try:
            prefs = await self.db.list_preferences()
            reminders = await self.db.get_pending_reminders()
            self._cached_system_prompt = build_system_prompt(prefs, reminders)
        except Exception as exc:
            logger.warning("prompt_refresh_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Respond on dedicated channel without requiring a mention
    # ------------------------------------------------------------------

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        # DMs and explicit mentions always work
        if isinstance(message.channel, discord.DMChannel) or self.user in message.mentions:
            return True
        # On the dedicated channel, respond to every message
        channel_id = self.settings.alita_discord_channel_id
        if channel_id and message.channel.id == channel_id:
            return True
        return False

    # ------------------------------------------------------------------
    # Long-term memory hooks
    # ------------------------------------------------------------------

    async def _get_context_prefix(self, message: discord.Message) -> str:
        return await self.ltm.search_relevant(message.clean_content)

    async def _on_final_response(self, message: discord.Message, reply: str) -> None:
        # Fire-and-forget — embedding is slow; don't block the response
        asyncio.create_task(
            self.ltm.embed_exchange(
                user_msg=message.clean_content,
                assistant_msg=reply,
                channel_id=str(message.channel.id),
            )
        )

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        # --- Weather ---
        @reg.register(
            "get_current_weather",
            "Retourne la météo actuelle à Marseille (ou une autre ville si précisée).",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Ville (défaut : Marseille,FR)"},
                },
                "required": [],
            },
        )
        async def get_current_weather(city: str | None = None) -> str:
            return await self.weather.get_current_weather(city)

        @reg.register(
            "get_weather_forecast",
            "Retourne les prévisions météo pour les prochains jours.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer", "default": 3},
                },
                "required": [],
            },
        )
        async def get_weather_forecast(city: str | None = None, days: int = 3) -> str:
            return await self.weather.get_forecast(city, days)

        @reg.register(
            "should_i_ride",
            "Analyse si les conditions météo sont favorables pour prendre la moto aujourd'hui (8h-19h). "
            "Appelle cet outil systématiquement le matin ou si on parle de déplacement en moto.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Ville (défaut : Marseille,FR)"},
                },
                "required": [],
            },
        )
        async def should_i_ride(city: str | None = None) -> str:
            return await self.weather.should_i_ride(city)

        # --- Stocks ---
        @reg.register(
            "get_portfolio_summary",
            "Retourne le résumé du portefeuille boursier avec les performances et P&L.",
        )
        async def get_portfolio_summary() -> str:
            return await self.stocks.get_portfolio_summary()

        @reg.register(
            "get_stock_quote",
            "Retourne le cours actuel d'une action (ex: AAPL, MSFT, MC.PA).",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker boursier (ex: AAPL)"},
                },
                "required": ["symbol"],
            },
        )
        async def get_stock_quote(symbol: str) -> str:
            return await self.stocks.get_stock_quote(symbol)

        @reg.register(
            "update_portfolio_position",
            "Met à jour une position dans le portefeuille boursier persistant. "
            "Utilise action='buy' pour un achat (recalcule le PRU), 'sell' pour une vente (réduit les parts, "
            "supprime la ligne si tout est vendu), 'set' pour forcer les valeurs (corrections manuelles). "
            "Appelle TOUJOURS cet outil quand Asmo annonce un achat ou une vente d'actions.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker boursier exact (ex: AI.PA pour Air Liquide, AIR.PA pour Airbus)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["buy", "sell", "set"],
                        "description": "buy=achat, sell=vente, set=correction manuelle",
                    },
                    "shares": {
                        "type": "number",
                        "description": "Nombre d'actions concernées",
                    },
                    "price": {
                        "type": "number",
                        "description": "Prix unitaire en euros",
                    },
                    "label": {
                        "type": "string",
                        "description": "Nom lisible de l'action (ex: 'Air Liquide'). Optionnel si déjà connu.",
                    },
                },
                "required": ["symbol", "action", "shares", "price"],
            },
        )
        async def update_portfolio_position(
            symbol: str,
            action: str,
            shares: float,
            price: float,
            label: Optional[str] = None,
        ) -> str:
            symbol = symbol.upper()
            existing = await self.db.get_position(symbol)

            if action == "set":
                await self.db.upsert_position(symbol, shares, price, label)
                lbl = label or (existing and existing["label"]) or symbol
                return (
                    f"✅ Position {symbol} ({lbl}) forcée : {shares:.0f} actions à {price:.2f}€ de PRU."
                )

            elif action == "buy":
                if existing:
                    total_shares = existing["shares"] + shares
                    new_avg = (existing["shares"] * existing["avg_price"] + shares * price) / total_shares
                    await self.db.upsert_position(symbol, total_shares, new_avg, label)
                    lbl = label or existing["label"] or symbol
                    return (
                        f"✅ Achat enregistré — {symbol} ({lbl}) : +{shares:.0f} actions à {price:.2f}€. "
                        f"Total : {total_shares:.0f} actions | Nouveau PRU : {new_avg:.2f}€."
                    )
                else:
                    await self.db.upsert_position(symbol, shares, price, label)
                    lbl = label or symbol
                    return (
                        f"✅ Nouvelle position — {symbol} ({lbl}) : {shares:.0f} actions à {price:.2f}€."
                    )

            elif action == "sell":
                if not existing:
                    return f"❌ Position {symbol} introuvable dans le portefeuille."
                if shares > existing["shares"]:
                    return (
                        f"❌ Impossible : tu n'as que {existing['shares']:.0f} actions {symbol}, "
                        f"pas {shares:.0f}."
                    )
                new_shares = existing["shares"] - shares
                lbl = label or existing["label"] or symbol
                if new_shares == 0:
                    await self.db.delete_position(symbol)
                    return (
                        f"✅ Position {symbol} ({lbl}) clôturée — toutes les actions vendues à {price:.2f}€."
                    )
                else:
                    await self.db.upsert_position(symbol, new_shares, existing["avg_price"], label)
                    return (
                        f"✅ Vente enregistrée — {symbol} ({lbl}) : -{shares:.0f} actions à {price:.2f}€. "
                        f"Restant : {new_shares:.0f} actions | PRU inchangé : {existing['avg_price']:.2f}€."
                    )

            return f"❌ Action inconnue : {action}. Utilise buy, sell ou set."

        # --- Home Assistant ---
        @reg.register(
            "get_ha_states",
            "Liste les entités Home Assistant. Utilise domain pour filtrer (light, switch, sensor, climate…).",
            parameters={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domaine HA (light, switch, sensor…)"},
                },
                "required": [],
            },
        )
        async def get_ha_states(domain: str | None = None) -> str:
            return await self.ha.get_ha_states(domain)

        @reg.register(
            "get_ha_entity",
            "Retourne l'état détaillé d'une entité Home Assistant spécifique.",
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "ID de l'entité (ex: light.salon)"},
                },
                "required": ["entity_id"],
            },
        )
        async def get_ha_entity(entity_id: str) -> str:
            return await self.ha.get_ha_entity(entity_id)

        @reg.register(
            "call_ha_service",
            "Appelle un service Home Assistant (turn_on, turn_off, toggle, activate scene…).",
            parameters={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domaine (light, switch, scene…)"},
                    "service": {"type": "string", "description": "Service (turn_on, turn_off, toggle…)"},
                    "entity_id": {"type": "string", "description": "ID de l'entité"},
                    "data": {"type": "object", "description": "Données supplémentaires (ex: brightness)"},
                },
                "required": ["domain", "service", "entity_id"],
            },
        )
        async def call_ha_service(
            domain: str, service: str, entity_id: str, data: dict | None = None
        ) -> str:
            return await self.ha.call_ha_service(domain, service, entity_id, data)

        @reg.register(
            "get_ha_sensors_summary",
            "Retourne un résumé des capteurs clés de la maison (température, humidité, énergie).",
        )
        async def get_ha_sensors_summary() -> str:
            return await self.ha.get_ha_sensors_summary()

        # --- Web Search ---
        @reg.register(
            "web_search",
            "Recherche sur le web via SearXNG. Utilise cet outil pour les questions d'actualité "
            "ou toute information récente que tu ne connais pas.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "La requête de recherche"},
                    "num_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        )
        async def web_search(query: str, num_results: int = 5) -> str:
            return await self.web_search.search(query, num_results)

        # --- Spotify ---
        @reg.register(
            "get_now_playing",
            "Retourne la musique en cours de lecture sur Spotify.",
        )
        async def get_now_playing() -> str:
            return await self.spotify.get_now_playing()

        @reg.register(
            "control_spotify",
            "Contrôle la lecture Spotify : play, pause, next, previous.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "next", "previous"],
                        "description": "Action à effectuer",
                    }
                },
                "required": ["action"],
            },
        )
        async def control_spotify(action: str) -> str:
            return await self.spotify.control_playback(action)

        @reg.register(
            "search_spotify",
            "Recherche un morceau, artiste ou playlist sur Spotify.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "search_type": {
                        "type": "string",
                        "enum": ["track", "artist", "playlist"],
                        "default": "track",
                    },
                },
                "required": ["query"],
            },
        )
        async def search_spotify(query: str, search_type: str = "track") -> str:
            return await self.spotify.search_spotify(query, search_type)

        @reg.register(
            "get_recent_tracks",
            "Retourne les derniers morceaux écoutés sur Spotify.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        )
        async def get_recent_tracks(limit: int = 10) -> str:
            return await self.spotify.get_recent_tracks(limit)

        @reg.register(
            "add_to_spotify_queue",
            "Ajoute un morceau à la file de lecture Spotify (URI spotify:track:xxx).",
            parameters={
                "type": "object",
                "properties": {
                    "track_uri": {"type": "string", "description": "URI Spotify du morceau"},
                },
                "required": ["track_uri"],
            },
        )
        async def add_to_spotify_queue(track_uri: str) -> str:
            return await self.spotify.add_to_queue(track_uri)

        # --- Memory ---
        @reg.register(
            "remember",
            "Mémorise une préférence ou information sur Asmo (persiste entre les sessions).",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Clé (ex: genre_musical_prefere)"},
                    "value": {"type": "string", "description": "Valeur à mémoriser"},
                },
                "required": ["key", "value"],
            },
        )
        async def remember(key: str, value: str) -> str:
            result = await self.memory.remember(key, value)
            await self._refresh_prompt()
            return result

        @reg.register(
            "recall",
            "Récupère une préférence mémorisée.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                },
                "required": ["key"],
            },
        )
        async def recall(key: str) -> str:
            return await self.memory.recall(key)

        @reg.register(
            "list_preferences",
            "Liste toutes les préférences mémorisées.",
        )
        async def list_preferences() -> str:
            return await self.memory.list_preferences()

        @reg.register(
            "add_reminder",
            "Crée un rappel avec optionnellement une date d'échéance.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Contenu du rappel"},
                    "due_at": {"type": "string", "description": "Date/heure ISO 8601 (optionnel)"},
                },
                "required": ["content"],
            },
        )
        async def add_reminder(content: str, due_at: str | None = None) -> str:
            return await self.memory.add_reminder(content, due_at)

        @reg.register(
            "get_reminders",
            "Liste les rappels en attente.",
        )
        async def get_reminders() -> str:
            return await self.memory.get_reminders()

        @reg.register(
            "complete_reminder",
            "Marque un rappel comme terminé.",
            parameters={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID du rappel"},
                },
                "required": ["reminder_id"],
            },
        )
        async def complete_reminder(reminder_id: int) -> str:
            return await self.memory.complete_reminder(reminder_id)

        # --- Fetch URL ---
        @reg.register(
            "fetch_url",
            "Récupère et retourne le contenu d'une page web (GitHub, documentation, article…). "
            "Utilise cet outil quand l'utilisateur partage un lien et demande de le lire, "
            "résumer ou analyser.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL complète à récupérer"},
                },
                "required": ["url"],
            },
        )
        async def fetch_url(url: str) -> str:
            return await self.fetch_url.fetch(url)

        # --- Anytype ---
        @reg.register(
            "anytype_create_note",
            "Crée une note ou capture une idée dans Anytype (base de connaissances personnelle). "
            "Utilise cet outil dès que l'utilisateur mentionne une idée à noter, quelque chose "
            "à retenir, ou demande explicitement de créer une note ou une page.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre de la note"},
                    "body": {
                        "type": "string",
                        "description": "Contenu de la note en Markdown (optionnel)",
                    },
                    "type_key": {
                        "type": "string",
                        "description": "Type Anytype : 'page' (défaut), 'bookmark', 'collection'",
                        "default": "page",
                    },
                },
                "required": ["title"],
            },
        )
        async def anytype_create_note(
            title: str, body: str = "", type_key: str = "page"
        ) -> str:
            return await self.anytype.create_note(title, body, type_key)

        @reg.register(
            "anytype_search",
            "Recherche dans Anytype par mots-clés. Utilise cet outil pour retrouver des notes, "
            "projets ou idées existants — notamment avant de les résumer ou quand l'utilisateur "
            "demande 'mes projets homelab', 'mes idées sur X', etc.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termes de recherche"},
                    "limit": {
                        "type": "integer",
                        "description": "Nombre max de résultats (défaut : 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        )
        async def anytype_search(query: str, limit: int = 10) -> str:
            return await self.anytype.search(query, limit)

        @reg.register(
            "anytype_get_object",
            "Récupère et affiche le contenu complet d'une note ou d'un projet Anytype à partir "
            "de son ID. Utilise cet outil après anytype_search pour lire ou résumer un objet.",
            parameters={
                "type": "object",
                "properties": {
                    "object_id": {
                        "type": "string",
                        "description": "ID de l'objet Anytype (obtenu via anytype_search)",
                    },
                },
                "required": ["object_id"],
            },
        )
        async def anytype_get_object(object_id: str) -> str:
            return await self.anytype.get_object(object_id)

        @reg.register(
            "anytype_list_objects",
            "Liste les notes et projets récents dans Anytype. Utilise cet outil pour un aperçu "
            "général de la base de connaissances, ou quand l'utilisateur demande un suivi de "
            "ses projets homelab et dev en cours.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Nombre max d'objets à lister (défaut : 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        )
        async def anytype_list_objects(limit: int = 20) -> str:
            return await self.anytype.list_objects(limit)

    # ------------------------------------------------------------------
    # Discord lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        await self.db.init()
        await self._seed_portfolio_from_env()
        await self._refresh_prompt()
        self._register_prefix_commands()
        self._scheduler.start()
        await self._subscriber.start(self.settings.asmo_redis_url)
        await super().setup_hook()

    async def _seed_portfolio_from_env(self) -> None:
        """One-time migration: seed DB portfolio from ALITA_PORTFOLIO env var if DB is empty."""
        if not self.settings.alita_portfolio or self.settings.alita_portfolio == "[]":
            return
        if not await self.db.portfolio_is_empty():
            return
        try:
            positions = json.loads(self.settings.alita_portfolio)
            count = 0
            for pos in positions:
                symbol = pos.get("symbol", "").strip().upper()
                shares = float(pos.get("shares", 0))
                avg_price = float(pos.get("avg_price", 0))
                label = pos.get("label") or pos.get("name")
                if symbol and shares > 0 and avg_price >= 0:
                    await self.db.upsert_position(symbol, shares, avg_price, label)
                    count += 1
            logger.info("portfolio_seeded_from_env", count=count)
        except Exception as exc:
            logger.warning("portfolio_seed_failed", error=str(exc))

    async def close(self) -> None:
        self._scheduler.stop()
        await self._subscriber.stop()
        await self.ollama.close()
        await super().close()

    # ------------------------------------------------------------------
    # Prefix commands
    # ------------------------------------------------------------------

    def _register_prefix_commands(self) -> None:
        @self.command(name="spotify-auth", help="Obtenir l'URL d'authentification Spotify")
        async def cmd_spotify_auth(ctx: commands.Context) -> None:
            url = self.spotify.get_auth_url()
            if url.startswith("⚠️"):
                await ctx.send(url)
            else:
                await ctx.send(
                    f"🎵 **Authentification Spotify**\n"
                    f"Visite ce lien pour autoriser l'accès :\n{url}"
                )

        @self.command(name="briefing", help="Forcer le briefing matinal immédiatement")
        async def cmd_briefing(ctx: commands.Context) -> None:
            async with ctx.typing():
                await self._scheduler.post_briefing(ctx.channel)

        @self.command(name="rappels", help="Lister les rappels en attente")
        async def cmd_rappels(ctx: commands.Context) -> None:
            async with ctx.typing():
                result = await self.memory.get_reminders()
                await send_long_message(ctx.channel, result)

        @self.command(name="prefs", help="Lister les préférences mémorisées")
        async def cmd_prefs(ctx: commands.Context) -> None:
            async with ctx.typing():
                result = await self.memory.list_preferences()
                await send_long_message(ctx.channel, result)

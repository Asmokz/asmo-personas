"""AlitaPersona — ALITA personal assistant in Olympus context."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

from asmo_commons.config.settings import AlitaSettings
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from alita.src.db.manager import AlitaDbManager
from alita.src.db.training_logger import TrainingLogger
from alita.src.persona import build_system_prompt
from alita.src.tools.anytype import AnytypeTool
from alita.src.tools.fetch_url import FetchUrlTool
from alita.src.tools.home_assistant import HomeAssistantTool
from alita.src.tools.long_term_memory import LongTermMemory
from alita.src.tools.memory import MemoryTool
from alita.src.tools.spotify import SpotifyTool
from alita.src.tools.stocks import StocksTool
from alita.src.tools.weather import WeatherTool
from alita.src.tools.web_search import WebSearchTool

from .base import OlympusPersona

logger = structlog.get_logger()

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_MAX_AUTO_FETCH = 2

_ANYTYPE_CREATE_RE = re.compile(
    r"\b(anytype|crée[- ]?(?:moi\s+)?(?:une?\s+)?(?:note|page|mémo)|"
    r"note[- ](?:ça|cela|cette|ce)|noter\s+(?:dans|sur)\s+anytype)\b",
    re.IGNORECASE,
)
_MEMORY_REMEMBER_RE = re.compile(
    r"\b(souviens[- ]toi|mémorise|retiens|n'oublie pas|remember\s+that|garde\s+en\s+m[eé]moire)\b",
    re.IGNORECASE,
)
_REMINDER_ADD_RE = re.compile(
    r"\b(rappelle[- ]moi|un rappel|remind\s+me|ajoute\s+un\s+rappel|crée\s+un\s+rappel)\b",
    re.IGNORECASE,
)
_HA_SERVICE_RE = re.compile(
    r"\b(allume|éteins|étein[st]|ferme|ouvre|baisse|monte|règle|toggle|"
    r"turn\s+on|turn\s+off|switch\s+on|switch\s+off)\b",
    re.IGNORECASE,
)
_SPOTIFY_CONTROL_RE = re.compile(
    r"\b(joue|mets?\s+en\s+pause|pause\s+(?:la\s+)?musique|chanson\s+suivante|"
    r"passe\s+[àa]\s+la\s+suite|next\s+(?:song|track)|skip|"
    r"reprends?(?:\s+la\s+musique)?|ajoute\s+[àa]\s+la\s+file)\b",
    re.IGNORECASE,
)


class AlitaPersona(OlympusPersona):
    """ALITA personal assistant — Olympus version."""

    PERSONA_ID = "alita"
    PERSONA_NAME = "Alita"
    PERSONA_DESCRIPTION = "Assistante personnelle — météo, bourse, domotique, musique, notes"
    PERSONA_COLOR = "#E85D04"

    def __init__(self, settings: AlitaSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.alita_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            )
        )
        self.settings = settings
        self.db = AlitaDbManager(settings.alita_db_path)

        self.weather = WeatherTool(settings.alita_weather_api_key, settings.alita_weather_city)
        self.stocks = StocksTool(self.db)
        self.ha = HomeAssistantTool(settings.alita_ha_url, settings.alita_ha_token)
        self.web_search_tool = WebSearchTool(settings.alita_searxng_url)
        self.spotify = SpotifyTool(
            settings.alita_spotify_client_id,
            settings.alita_spotify_client_secret,
            settings.alita_spotify_redirect_uri,
            self.db,
        )
        self.memory = MemoryTool(self.db)
        self.ltm = LongTermMemory(self.db, self.ollama, settings.alita_embed_model)
        self.fetch_url = FetchUrlTool()
        self.training_logger = TrainingLogger(settings.alita_training_db_path)
        self.anytype = AnytypeTool(
            settings.alita_anytype_url,
            settings.alita_anytype_api_key,
            settings.alita_anytype_space_id,
        )

        self._registry = ToolRegistry()
        self._cached_system_prompt: str = build_system_prompt()
        self._register_tools()

    # ------------------------------------------------------------------
    # APIEngine interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return self._cached_system_prompt

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise DB and seed portfolio from env."""
        await self.db.init()
        await self.training_logger.init()
        await self._seed_portfolio_from_env()
        await self._refresh_prompt()

    async def _refresh_prompt(self) -> None:
        try:
            prefs = await self.db.list_preferences()
            reminders = await self.db.get_pending_reminders()
            self._cached_system_prompt = build_system_prompt(prefs, reminders)
        except Exception as exc:
            logger.warning("prompt_refresh_failed", error=str(exc))

    async def _seed_portfolio_from_env(self) -> None:
        import json as _json
        if not self.settings.alita_portfolio or self.settings.alita_portfolio == "[]":
            return
        if not await self.db.portfolio_is_empty():
            return
        try:
            positions = _json.loads(self.settings.alita_portfolio)
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

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def _get_context_prefix(self, conv_id: str, content: str) -> str:
        parts = []

        ltm = await self.ltm.search_relevant(content, conversation_id=conv_id)
        if ltm:
            parts.append(ltm)

        urls = _URL_RE.findall(content)[:_MAX_AUTO_FETCH]
        for url in urls:
            fetched = await self.fetch_url.fetch(url)
            if fetched:
                parts.append(f"[Contenu récupéré depuis {url}]\n{fetched}\n[Fin du contenu]")

        reminders_injected = []

        if _ANYTYPE_CREATE_RE.search(content):
            parts.append(
                "[RAPPEL OUTIL : L'utilisateur demande de créer une note Anytype. "
                "Appelle anytype_create_note EN PREMIER avec tout le contenu dans body. "
                "Ne pas écrire la note dans le chat.]"
            )
            reminders_injected.append("anytype_create")

        if _MEMORY_REMEMBER_RE.search(content):
            parts.append(
                "[RAPPEL OUTIL : L'utilisateur demande de mémoriser quelque chose. "
                "Appelle memory avec action='remember' IMMÉDIATEMENT. "
                "Ne pas juste acquiescer — persister dans la DB.]"
            )
            reminders_injected.append("memory_remember")

        if _REMINDER_ADD_RE.search(content):
            parts.append(
                "[RAPPEL OUTIL : L'utilisateur demande un rappel. "
                "Appelle reminders avec action='add' IMMÉDIATEMENT avec le contenu et la date si précisée.]"
            )
            reminders_injected.append("reminders_add")

        if _HA_SERVICE_RE.search(content):
            parts.append(
                "[RAPPEL OUTIL : L'utilisateur demande de contrôler un appareil domotique. "
                "Appelle call_ha_service IMMÉDIATEMENT. Ne pas décrire l'action sans l'exécuter.]"
            )
            reminders_injected.append("ha_service")

        if _SPOTIFY_CONTROL_RE.search(content):
            parts.append(
                "[RAPPEL OUTIL : L'utilisateur demande de contrôler Spotify. "
                "Appelle spotify_control IMMÉDIATEMENT avec la bonne action.]"
            )
            reminders_injected.append("spotify_control")

        if reminders_injected:
            logger.debug("tool_reminders_injected", tools=reminders_injected)

        return "\n\n".join(parts)

    async def _on_final_response(self, conv_id: str, reply: str) -> None:
        # LTM embedding is handled by the router (which has access to user_msg).
        # No-op here to avoid duplicates.
        pass

    async def embed_exchange(self, conv_id: str, user_msg: str, reply: str) -> None:
        """Public entry point for fire-and-forget LTM embedding (called from router)."""
        await self.ltm.embed_exchange(
            user_msg=user_msg,
            assistant_msg=reply,
            channel_id=conv_id,
        )

    async def _on_exchange_complete(
        self, conv_id: str, history: list[dict], meta: dict
    ) -> None:
        asyncio.create_task(
            self.training_logger.log_exchange(
                conv_id=meta.get("conv_id", ""),
                channel_id=conv_id,
                system_prompt=self.get_system_prompt(),
                messages=history,
                meta=meta,
            )
        )

    # ------------------------------------------------------------------
    # Tool registration (mirrors AlitaBot._register_tools())
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
            "Analyse si les conditions météo sont favorables pour prendre la moto aujourd'hui.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                },
                "required": [],
            },
        )
        async def should_i_ride(city: str | None = None) -> str:
            return await self.weather.should_i_ride(city)

        # --- Stocks ---
        @reg.register(
            "get_portfolio_info",
            "Retourne le résumé du portefeuille boursier avec les performances et P&L.",
        )
        async def get_portfolio_info() -> str:
            return await self.stocks.get_portfolio_summary()

        @reg.register(
            "get_stock_quote",
            "Retourne le cours actuel d'une action (ex: AAPL, MSFT, MC.PA).",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                },
                "required": ["symbol"],
            },
        )
        async def get_stock_quote(symbol: str) -> str:
            return await self.stocks.get_stock_quote(symbol)

        @reg.register(
            "update_portfolio_position",
            "Met à jour une position dans le portefeuille boursier persistant.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell", "set"]},
                    "shares": {"type": "number"},
                    "price": {"type": "number"},
                    "label": {"type": "string"},
                },
                "required": ["symbol", "action", "shares", "price"],
            },
        )
        async def update_portfolio_position(
            symbol: str, action: str, shares: float, price: float, label: Optional[str] = None
        ) -> str:
            symbol = symbol.upper()
            existing = await self.db.get_position(symbol)
            if action == "set":
                await self.db.upsert_position(symbol, shares, price, label)
                lbl = label or (existing and existing["label"]) or symbol
                return f"✅ Position {symbol} ({lbl}) forcée : {shares:.0f} actions à {price:.2f}€ de PRU."
            elif action == "buy":
                if existing:
                    total_shares = existing["shares"] + shares
                    new_avg = (existing["shares"] * existing["avg_price"] + shares * price) / total_shares
                    await self.db.upsert_position(symbol, total_shares, new_avg, label)
                    lbl = label or existing["label"] or symbol
                    return (f"✅ Achat enregistré — {symbol} ({lbl}) : +{shares:.0f} actions à {price:.2f}€. "
                            f"Total : {total_shares:.0f} actions | Nouveau PRU : {new_avg:.2f}€.")
                else:
                    await self.db.upsert_position(symbol, shares, price, label)
                    return f"✅ Nouvelle position — {symbol} ({label or symbol}) : {shares:.0f} actions à {price:.2f}€."
            elif action == "sell":
                if not existing:
                    return f"❌ Position {symbol} introuvable dans le portefeuille."
                if shares > existing["shares"]:
                    return f"❌ Impossible : tu n'as que {existing['shares']:.0f} actions {symbol}."
                new_shares = existing["shares"] - shares
                lbl = label or existing["label"] or symbol
                if new_shares == 0:
                    await self.db.delete_position(symbol)
                    return f"✅ Position {symbol} ({lbl}) clôturée — toutes les actions vendues à {price:.2f}€."
                else:
                    await self.db.upsert_position(symbol, new_shares, existing["avg_price"], label)
                    return (f"✅ Vente enregistrée — {symbol} ({lbl}) : -{shares:.0f} actions à {price:.2f}€. "
                            f"Restant : {new_shares:.0f} actions | PRU inchangé : {existing['avg_price']:.2f}€.")
            return f"❌ Action inconnue : {action}."

        # --- Home Assistant ---
        @reg.register(
            "get_ha_info",
            "Consulte Home Assistant en lecture.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["states", "entity", "sensors"]},
                    "entity_id": {"type": "string"},
                    "domain": {"type": "string"},
                },
                "required": ["action"],
            },
        )
        async def get_ha_info(action: str, entity_id: str | None = None, domain: str | None = None) -> str:
            if action == "states":
                return await self.ha.get_ha_states(domain)
            if action == "entity":
                if not entity_id:
                    return "❌ entity_id requis."
                return await self.ha.get_ha_entity(entity_id)
            if action == "sensors":
                return await self.ha.get_ha_sensors_summary()
            return f"❌ action inconnue : {action}."

        @reg.register(
            "call_ha_service",
            "Exécute une action dans Home Assistant.",
            parameters={
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "service": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["domain", "service", "entity_id"],
            },
        )
        async def call_ha_service(domain: str, service: str, entity_id: str, data: dict | None = None) -> str:
            return await self.ha.call_ha_service(domain, service, entity_id, data)

        # --- Web Search ---
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
        async def web_search(query: str, num_results: int = 5) -> str:
            return await self.web_search_tool.search(query, num_results)

        # --- Spotify ---
        @reg.register(
            "get_spotify_info",
            "Consulte Spotify en lecture.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["now_playing", "recent_tracks", "search"]},
                    "query": {"type": "string"},
                    "search_type": {"type": "string", "enum": ["track", "artist", "playlist"]},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
        )
        async def get_spotify_info(action: str, query: str | None = None, search_type: str = "track", limit: int = 10) -> str:
            if action == "now_playing":
                return await self.spotify.get_now_playing()
            if action == "recent_tracks":
                return await self.spotify.get_recent_tracks(limit)
            if action == "search":
                if not query:
                    return "❌ query requis."
                return await self.spotify.search_spotify(query, search_type)
            return f"❌ action inconnue : {action}."

        @reg.register(
            "spotify_control",
            "Contrôle la lecture Spotify.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "pause", "next", "previous", "queue"]},
                    "track_uri": {"type": "string"},
                },
                "required": ["action"],
            },
        )
        async def spotify_control(action: str, track_uri: str | None = None) -> str:
            if action == "queue":
                if not track_uri:
                    return "❌ track_uri requis."
                return await self.spotify.add_to_queue(track_uri)
            if action in ("play", "pause", "next", "previous"):
                return await self.spotify.control_playback(action)
            return f"❌ action inconnue : {action}."

        # --- Memory ---
        @reg.register(
            "memory",
            "Gère la mémoire persistante sur Asmo.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["remember", "recall", "list"]},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["action"],
            },
        )
        async def memory(action: str, key: str | None = None, value: str | None = None) -> str:
            if action == "remember":
                if not key or not value:
                    return "❌ key et value requis."
                result = await self.memory.remember(key, value)
                await self._refresh_prompt()
                return result
            if action == "recall":
                if not key:
                    return "❌ key requis."
                return await self.memory.recall(key)
            if action == "list":
                return await self.memory.list_preferences()
            return f"❌ action inconnue : {action}."

        # --- Reminders ---
        @reg.register(
            "reminders",
            "Gère les rappels.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "complete"]},
                    "content": {"type": "string"},
                    "due_at": {"type": "string"},
                    "reminder_id": {"type": "integer"},
                },
                "required": ["action"],
            },
        )
        async def reminders(action: str, content: str | None = None, due_at: str | None = None, reminder_id: int | None = None) -> str:
            if action == "add":
                if not content:
                    return "❌ content requis."
                return await self.memory.add_reminder(content, due_at)
            if action == "list":
                return await self.memory.get_reminders()
            if action == "complete":
                if reminder_id is None:
                    return "❌ reminder_id requis."
                return await self.memory.complete_reminder(reminder_id)
            return f"❌ action inconnue : {action}."

        # --- Anytype ---
        @reg.register(
            "anytype_create_note",
            "Crée une note dans Anytype.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "type_key": {"type": "string", "default": "page"},
                },
                "required": ["title"],
            },
        )
        async def anytype_create_note(title: str, body: str = "", type_key: str = "page") -> str:
            return await self.anytype.create_note(title, body, type_key)

        @reg.register(
            "anytype_read",
            "Consulte Anytype en lecture.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["search", "get", "list"]},
                    "query": {"type": "string"},
                    "object_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
        )
        async def anytype_read(action: str, query: str | None = None, object_id: str | None = None, limit: int | None = None) -> str:
            if action == "search":
                if not query:
                    return "❌ query requis."
                return await self.anytype.search(query, limit or 10)
            if action == "get":
                if not object_id:
                    return "❌ object_id requis."
                return await self.anytype.get_object(object_id)
            if action == "list":
                return await self.anytype.list_objects(limit or 20)
            return f"❌ action inconnue : {action}."

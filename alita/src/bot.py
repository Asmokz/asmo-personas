"""ALITA Discord bot — briefing & life assistant."""
from __future__ import annotations

import structlog

from asmo_commons.config.settings import AlitaSettings
from asmo_commons.discord.base_bot import BaseBot
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from .persona import SYSTEM_PROMPT
from .scheduler import AlitaScheduler
from .tools.weather import WeatherTool
from .tools.calendar import CalendarTool
from .tools.stocks import StocksTool

logger = structlog.get_logger()


class AlitaBot(BaseBot):
    """ALITA — briefing & life assistant bot."""

    def __init__(self, settings: AlitaSettings) -> None:
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

        self.weather = WeatherTool(settings.alita_weather_api_key, settings.alita_weather_city)
        self.calendar = CalendarTool()
        self.stocks = StocksTool()

        self._registry = ToolRegistry()
        self._register_tools()
        self._scheduler = AlitaScheduler(self)

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register(
            "get_current_weather",
            "Retourne la météo actuelle pour une ville.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Nom de la ville (défaut : Paris)"},
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

        @reg.register("get_today_events", "Retourne les événements du calendrier aujourd'hui.")
        async def get_today_events() -> str:
            return await self.calendar.get_today_events()

        @reg.register(
            "get_crypto_prices",
            "Retourne les cours actuels des cryptomonnaies.",
            parameters={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste de symboles (ex: ['BTC', 'ETH'])",
                    }
                },
                "required": [],
            },
        )
        async def get_crypto_prices(symbols: list[str] | None = None) -> str:
            return await self.stocks.get_crypto_prices(symbols)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        self._scheduler.start()
        await super().setup_hook()

    async def close(self) -> None:
        self._scheduler.stop()
        await self.ollama.close()
        await super().close()

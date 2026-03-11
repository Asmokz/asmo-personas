"""VegasBot — analyste financier PEA Discord bot."""
from __future__ import annotations

import os
from typing import Optional

import discord
import structlog

from asmo_commons.causality.client import CausalityClient
from asmo_commons.config.settings import VegasSettings
from asmo_commons.discord.base_bot import BaseBot
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from .cron.market_sync import MarketSyncCron
from .db.market_db import MarketDB
from .db.vectors_db import VectorsDB
from .persona import build_system_prompt
from .pubsub.publisher import VegasPublisher
from .rag.vegas_rag import VegasRAG
from .scheduler import VegasScheduler
from .tools.backtest_strategy import BacktestStrategy
from .tools.compare_stocks import CompareStocks
from .tools.market_news import MarketNews
from .tools.portfolio_diagnostic import PortfolioDiagnostic
from .tools.screen_pea_stocks import ScreenPEAStocks
from .tools.sector_overview import SectorOverview
from .tools.stock_analysis import StockAnalysis
from .tools.web_search import VegasWebSearch

logger = structlog.get_logger()

# Chemin du dossier knowledge relatif à ce fichier
_KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge")


class VegasBot(BaseBot):
    """VEGAS — analyste financier PEA bot Discord."""

    def __init__(self, settings: VegasSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.vegas_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
                num_ctx=8192,
            ),
            command_prefix="!",
        )
        self.settings = settings
        self.ollama.causality = CausalityClient(settings.asmo_redis_url, persona="vegas")

        # Bases de données
        self.market_db = MarketDB(settings.vegas_market_db_path)
        self.vectors_db = VectorsDB(settings.vegas_vectors_db_path)

        # RAG
        self.rag = VegasRAG(
            db=self.vectors_db,
            ollama=self.ollama,
            embed_model=settings.vegas_embed_model,
            knowledge_dir=os.path.abspath(_KNOWLEDGE_DIR),
        )

        # Outils
        self.screener = ScreenPEAStocks(self.market_db)
        self.stock_analysis = StockAnalysis()
        self.compare = CompareStocks()
        self.sector = SectorOverview(self.market_db)
        self.market_news = MarketNews(self.rag)
        self.portfolio_diag = PortfolioDiagnostic(settings.alita_db_path)
        self.backtest = BacktestStrategy()
        self.web_search_tool = VegasWebSearch(settings.vegas_searxng_url)

        # Publisher Redis
        self.publisher = VegasPublisher(settings.asmo_redis_url)

        # Cron
        self.cron = MarketSyncCron(
            market_db=self.market_db,
            rag=self.rag,
            tickers_csv_path=os.path.join(
                os.path.dirname(__file__), "..", "data", "pea_tickers.csv"
            ),
        )

        # Registry + scheduler
        self._registry = ToolRegistry()
        self._register_tools()
        self._scheduler = VegasScheduler(self)
        self._cached_system_prompt: str = build_system_prompt()

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return self._cached_system_prompt

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Canal dédié — répondre à tous les messages sans mention
    # ------------------------------------------------------------------

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        if isinstance(message.channel, discord.DMChannel) or self.user in message.mentions:
            return True
        channel_id = self.settings.vegas_discord_channel_id
        if channel_id and message.channel.id == channel_id:
            return True
        return False

    # ------------------------------------------------------------------
    # Hooks contextuels
    # ------------------------------------------------------------------

    async def _get_context_prefix(self, message: discord.Message) -> str:
        """Injecte le contexte RAG + date + résumé portfolio."""
        parts = []

        # RAG search (couches 1+2)
        rag_result = await self.rag.search(message.clean_content, top_k=4)
        if rag_result:
            parts.append(rag_result)

        # Date du jour
        from datetime import datetime
        today = datetime.now().strftime("%A %d %B %Y")
        parts.append(f"[Date du jour : {today}]")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Discord lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        await self.market_db.init()
        await self.vectors_db.init()
        await self.publisher.connect()
        self._cached_system_prompt = build_system_prompt()
        # Indexation knowledge au démarrage (fire-and-forget)
        import asyncio
        asyncio.create_task(
            self.rag.build_knowledge_index(), name="vegas-knowledge-index"
        )
        self._scheduler.start()
        await super().setup_hook()

    async def close(self) -> None:
        self._scheduler.stop()
        await self.publisher.disconnect()
        if self.ollama.causality:
            await self.ollama.causality.close()
        await self.ollama.close()
        await super().close()

    # ------------------------------------------------------------------
    # Enregistrement des outils
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        # --- Screening ---
        @reg.register(
            "screen_pea_stocks",
            "Filtre les actions PEA éligibles par critères fondamentaux "
            "(secteur, P/E, dividende, bêta, capitalisation).",
            parameters={
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": "Secteur Euronext (ex: Technologie, Finance, Santé)",
                    },
                    "max_pe": {
                        "type": "number",
                        "description": "P/E maximum (ex: 20 pour filtrer les actions bon marché)",
                    },
                    "min_dividend_yield": {
                        "type": "number",
                        "description": "Rendement dividende minimum en décimal (ex: 0.03 pour 3%)",
                    },
                    "max_beta": {
                        "type": "number",
                        "description": "Bêta maximum pour filtrer les valeurs défensives",
                    },
                    "min_market_cap": {
                        "type": "number",
                        "description": "Capitalisation boursière minimum",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximum de résultats (défaut : 15)",
                    },
                },
                "required": [],
            },
        )
        async def screen_pea_stocks(
            sector: Optional[str] = None,
            max_pe: Optional[float] = None,
            min_dividend_yield: Optional[float] = None,
            max_beta: Optional[float] = None,
            min_market_cap: Optional[float] = None,
            limit: int = 15,
        ) -> str:
            return await self.screener.screen(
                sector=sector,
                max_pe=max_pe,
                min_dividend_yield=min_dividend_yield,
                max_beta=max_beta,
                min_market_cap=min_market_cap,
                limit=limit,
            )

        # --- Analyse action ---
        @reg.register(
            "get_stock_analysis",
            "Analyse détaillée d'un ticker : valorisation, dividendes, risque, volatilité. "
            "Exemples : MC.PA (LVMH), AIR.PA (Airbus), ASML.AS",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Ticker boursier Euronext (ex: MC.PA, ASML.AS)",
                    },
                },
                "required": ["ticker"],
            },
        )
        async def get_stock_analysis(ticker: str) -> str:
            return await self.stock_analysis.analyze(ticker)

        # --- Comparaison ---
        @reg.register(
            "compare_stocks",
            "Compare côte à côte 2 à 5 tickers sur les métriques clés (P/E, P/B, dividende, ROE, bêta).",
            parameters={
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste de 2 à 5 tickers (ex: [\"MC.PA\", \"KER.PA\", \"RMS.PA\"])",
                    },
                },
                "required": ["tickers"],
            },
        )
        async def compare_stocks(tickers: list) -> str:
            return await self.compare.compare(list(tickers))

        # --- Secteur ---
        @reg.register(
            "get_sector_overview",
            "Vue d'ensemble d'un secteur Euronext avec métriques agrégées et liste des actions.",
            parameters={
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": "Secteur Euronext (Luxe, Finance, Technologie, Santé, etc.)",
                    },
                },
                "required": ["sector"],
            },
        )
        async def get_sector_overview(sector: str) -> str:
            return await self.sector.get_overview(sector)

        # --- News RAG ---
        @reg.register(
            "get_market_news",
            "Recherche les dernières news financières dans la base RAG VEGAS "
            "(couche knowledge + market intel). Cite les sources et dates.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Sujet de recherche (ex: 'LVMH résultats T3', 'taux BCE', 'CAC40')",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Nombre de résultats (défaut : 5)",
                    },
                },
                "required": ["query"],
            },
        )
        async def get_market_news(query: str, top_k: int = 5) -> str:
            return await self.market_news.get_news(query, top_k)

        # --- Diagnostic portefeuille ---
        @reg.register(
            "portfolio_diagnostic",
            "Analyse le portefeuille PEA depuis la base Alita : P&L, valorisation, concentration.",
        )
        async def portfolio_diagnostic() -> str:
            return await self.portfolio_diag.diagnose()

        # --- Backtest ---
        @reg.register(
            "backtest_strategy",
            "Simule une stratégie d'investissement sur historique yfinance. "
            "Stratégies : 'dca' (DCA mensuel), 'buy_and_hold', 'momentum' (MA50).",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Ticker à backtester (ex: MC.PA)",
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["dca", "buy_and_hold", "momentum"],
                        "description": "Stratégie : dca, buy_and_hold ou momentum",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1y", "2y", "3y", "5y", "10y", "max"],
                        "description": "Période historique (défaut : 3y)",
                    },
                    "monthly_amount": {
                        "type": "number",
                        "description": "Montant mensuel en euros pour DCA (défaut : 500)",
                    },
                },
                "required": ["ticker"],
            },
        )
        async def backtest_strategy(
            ticker: str,
            strategy: str = "dca",
            period: str = "3y",
            monthly_amount: float = 500.0,
        ) -> str:
            return await self.backtest.backtest(ticker, strategy, period, monthly_amount)

        # --- Web search ---
        @reg.register(
            "web_search",
            "Recherche web via SearXNG — dernier recours pour les données non disponibles dans le RAG.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Requête de recherche financière"},
                    "num_results": {"type": "integer", "description": "Nombre de résultats (défaut : 5)"},
                },
                "required": ["query"],
            },
        )
        async def web_search(query: str, num_results: int = 5) -> str:
            return await self.web_search_tool.search(query, num_results)

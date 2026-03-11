"""VegasPersona — analyste financier PEA dans le contexte Olympus."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

import structlog

from asmo_commons.causality.client import CausalityClient
from asmo_commons.config.settings import VegasSettings
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.registry import ToolRegistry

from vegas.src.cron.market_sync import MarketSyncCron
from vegas.src.db.market_db import MarketDB
from vegas.src.db.vectors_db import VectorsDB
from vegas.src.persona import build_system_prompt
from vegas.src.pubsub.publisher import VegasPublisher
from vegas.src.rag.vegas_rag import VegasRAG
from vegas.src.tools.backtest_strategy import BacktestStrategy
from vegas.src.tools.compare_stocks import CompareStocks
from vegas.src.tools.market_news import MarketNews
from vegas.src.tools.portfolio_diagnostic import PortfolioDiagnostic
from vegas.src.tools.screen_pea_stocks import ScreenPEAStocks
from vegas.src.tools.sector_overview import SectorOverview
from vegas.src.tools.stock_analysis import StockAnalysis
from vegas.src.tools.web_search import VegasWebSearch

from .base import OlympusPersona

logger = structlog.get_logger()

_KNOWLEDGE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "vegas", "knowledge"
)
_TICKERS_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "vegas", "data", "pea_tickers.csv"
)


class VegasPersona(OlympusPersona):
    """VEGAS — analyste financier PEA, version Olympus."""

    PERSONA_ID = "vegas"
    PERSONA_NAME = "VEGAS"
    PERSONA_DESCRIPTION = "Analyste financier PEA — screening, analyse, rapport portefeuille"
    PERSONA_COLOR = "#00C853"

    def __init__(self, settings: VegasSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.vegas_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            )
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
        self.stock_analysis_tool = StockAnalysis()
        self.compare_tool = CompareStocks()
        self.sector_tool = SectorOverview(self.market_db)
        self.market_news_tool = MarketNews(self.rag)
        self.portfolio_diag = PortfolioDiagnostic(settings.alita_db_path)
        self.backtest_tool = BacktestStrategy()
        self.web_search_tool = VegasWebSearch(settings.vegas_searxng_url)

        # Publisher Redis
        self.publisher = VegasPublisher(settings.asmo_redis_url)

        # Cron
        self.cron = MarketSyncCron(
            market_db=self.market_db,
            rag=self.rag,
            tickers_csv_path=os.path.abspath(_TICKERS_CSV),
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
        """Initialise les DBs et démarre le publisher Redis."""
        await self.market_db.init()
        await self.vectors_db.init()
        await self.publisher.connect()
        self._cached_system_prompt = build_system_prompt()

    # ------------------------------------------------------------------
    # Hooks contextuels
    # ------------------------------------------------------------------

    async def _get_context_prefix(self, conv_id: str, content: str) -> str:
        """Injecte le contexte RAG + date du jour + résumé portfolio."""
        parts: list[str] = []

        # RAG search (couches 1+2)
        rag_result = await self.rag.search(content, top_k=4)
        if rag_result:
            parts.append(rag_result)

        # Date du jour
        today = datetime.now().strftime("%A %d %B %Y")
        parts.append(f"[Date du jour : {today}]")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        # --- Screening ---
        @reg.register(
            "screen_pea_stocks",
            "Filtre les actions PEA éligibles par critères fondamentaux.",
            parameters={
                "type": "object",
                "properties": {
                    "sector": {"type": "string"},
                    "max_pe": {"type": "number"},
                    "min_dividend_yield": {"type": "number"},
                    "max_beta": {"type": "number"},
                    "min_market_cap": {"type": "number"},
                    "limit": {"type": "integer"},
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

        # --- Analyse ---
        @reg.register(
            "get_stock_analysis",
            "Analyse détaillée d'un ticker Euronext.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                },
                "required": ["ticker"],
            },
        )
        async def get_stock_analysis(ticker: str) -> str:
            return await self.stock_analysis_tool.analyze(ticker)

        # --- Comparaison ---
        @reg.register(
            "compare_stocks",
            "Compare 2 à 5 tickers sur les métriques clés.",
            parameters={
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["tickers"],
            },
        )
        async def compare_stocks(tickers: list) -> str:
            return await self.compare_tool.compare(list(tickers))

        # --- Secteur ---
        @reg.register(
            "get_sector_overview",
            "Vue d'ensemble d'un secteur Euronext.",
            parameters={
                "type": "object",
                "properties": {
                    "sector": {"type": "string"},
                },
                "required": ["sector"],
            },
        )
        async def get_sector_overview(sector: str) -> str:
            return await self.sector_tool.get_overview(sector)

        # --- News RAG ---
        @reg.register(
            "get_market_news",
            "Recherche les news financières dans la base RAG VEGAS.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        )
        async def get_market_news(query: str, top_k: int = 5) -> str:
            return await self.market_news_tool.get_news(query, top_k)

        # --- Diagnostic portefeuille ---
        @reg.register(
            "portfolio_diagnostic",
            "Analyse le portefeuille PEA (P&L, valorisation, concentration).",
        )
        async def portfolio_diagnostic() -> str:
            return await self.portfolio_diag.diagnose()

        # --- Backtest ---
        @reg.register(
            "backtest_strategy",
            "Simule une stratégie d'investissement sur historique yfinance.",
            parameters={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "strategy": {
                        "type": "string",
                        "enum": ["dca", "buy_and_hold", "momentum"],
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1y", "2y", "3y", "5y", "10y", "max"],
                    },
                    "monthly_amount": {"type": "number"},
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
            return await self.backtest_tool.backtest(ticker, strategy, period, monthly_amount)

        # --- Web search ---
        @reg.register(
            "web_search",
            "Recherche web SearXNG — dernier recours.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        )
        async def web_search(query: str, num_results: int = 5) -> str:
            return await self.web_search_tool.search(query, num_results)

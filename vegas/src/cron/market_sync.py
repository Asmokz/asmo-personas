"""Jobs quotidiens VEGAS : yfinance sync + news scraping + purge."""
from __future__ import annotations

import asyncio
import csv
import os
import time
from typing import TYPE_CHECKING, Optional

import aiohttp
import structlog

if TYPE_CHECKING:
    from ..db.market_db import MarketDB
    from ..rag.vegas_rag import VegasRAG

logger = structlog.get_logger()

_BATCH_SIZE = 20
_RETRY_DELAYS = [5, 15, 30]  # secondes de backoff sur rate limit
_SCRAPE_DELAY = 2.0           # secondes entre requêtes scraping

# Sources financières à scraper (sections gratuites)
_NEWS_SOURCES = [
    {
        "url": "https://www.boursobank.com/bourse/cours-bourse/actualites/",
        "name": "Boursobank",
    },
    {
        "url": "https://www.zonebourse.com/actualite-bourse/",
        "name": "Zonebourse",
    },
]

_USER_AGENT = (
    "VEGAS-Financial-Bot/1.0 (educational; https://github.com/asmo-personas)"
)


def _fetch_batch_yfinance(tickers: list[str]) -> list[dict]:
    """Récupère les données yfinance pour un batch de tickers (synchrone)."""
    import yfinance as yf
    results = []
    for ticker in tickers:
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                if not info:
                    break

                # Calcul des variations historiques
                hist = t.history(period="1y")
                change_1d = change_1m = change_6m = change_1y = None

                if not hist.empty and len(hist) >= 2:
                    prices = hist["Close"]
                    cur = float(prices.iloc[-1])
                    prev = float(prices.iloc[-2])
                    change_1d = (cur - prev) / prev * 100 if prev else None

                    if len(prices) >= 21:
                        p1m = float(prices.iloc[-21])
                        change_1m = (cur - p1m) / p1m * 100 if p1m else None
                    if len(prices) >= 126:
                        p6m = float(prices.iloc[-126])
                        change_6m = (cur - p6m) / p6m * 100 if p6m else None
                    if len(prices) >= 252:
                        p1y = float(prices.iloc[-252])
                        change_1y = (cur - p1y) / p1y * 100 if p1y else None

                results.append({
                    "ticker": ticker,
                    "name": info.get("longName") or info.get("shortName") or ticker,
                    "sector": info.get("sector"),
                    "market_cap": info.get("marketCap"),
                    "currency": info.get("currency", "EUR"),
                    "last_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "change_1d": change_1d,
                    "change_1m": change_1m,
                    "change_6m": change_6m,
                    "change_1y": change_1y,
                    "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                    "dividend_yield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                    "volume_avg": info.get("averageVolume"),
                })
                break  # succès
            except Exception as exc:
                err_str = str(exc).lower()
                if "rate" in err_str or "429" in err_str:
                    if attempt < len(_RETRY_DELAYS):
                        delay = _RETRY_DELAYS[attempt]
                        logger.warning(
                            "yfinance_rate_limit",
                            ticker=ticker,
                            retry=attempt + 1,
                            delay=delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error("yfinance_rate_limit_exhausted", ticker=ticker)
                        break
                else:
                    logger.warning("yfinance_fetch_error", ticker=ticker, error=str(exc))
                    break
    return results


class MarketSyncCron:
    """Jobs quotidiens : yfinance sync + news scraping + purge."""

    def __init__(
        self,
        market_db: "MarketDB",
        rag: "VegasRAG",
        tickers_csv_path: str,
    ) -> None:
        self._market_db = market_db
        self._rag = rag
        self._tickers_csv_path = tickers_csv_path

    async def sync_market_data(self) -> None:
        """Batch yfinance pour tous les tickers du CSV + upsert dans pea_stocks."""
        tickers = self._load_tickers()
        if not tickers:
            logger.warning("no_tickers_found", path=self._tickers_csv_path)
            return

        logger.info("market_sync_start", total=len(tickers))
        loop = asyncio.get_event_loop()
        success = 0
        errors = 0

        for i in range(0, len(tickers), _BATCH_SIZE):
            batch = tickers[i: i + _BATCH_SIZE]
            try:
                results = await loop.run_in_executor(
                    None, _fetch_batch_yfinance, batch
                )
                for data in results:
                    try:
                        await self._market_db.upsert_stock(data)
                        success += 1
                    except Exception as exc:
                        logger.warning(
                            "upsert_stock_error",
                            ticker=data.get("ticker"),
                            error=str(exc),
                        )
                        errors += 1
            except Exception as exc:
                logger.error("batch_fetch_error", batch=batch, error=str(exc))
                errors += len(batch)

            # Petite pause entre batches pour éviter le rate limiting
            if i + _BATCH_SIZE < len(tickers):
                await asyncio.sleep(1.0)

        logger.info(
            "market_sync_complete",
            success=success,
            errors=errors,
            total=len(tickers),
        )

    async def scrape_financial_news(self) -> None:
        """Scrape les sources d'actualité financière publiques.

        Respecte les délais entre requêtes et le User-Agent honnête.
        Les articles sont chunked et ajoutés au RAG market_intel.
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for source in _NEWS_SOURCES:
                try:
                    await self._scrape_source(session, source)
                    await asyncio.sleep(_SCRAPE_DELAY)
                except Exception as exc:
                    logger.warning(
                        "scrape_source_error",
                        source=source["name"],
                        error=str(exc),
                    )

    async def _scrape_source(
        self, session: aiohttp.ClientSession, source: dict
    ) -> None:
        """Scrape une source et indexe les articles trouvés."""
        from bs4 import BeautifulSoup

        url = source["url"]
        name = source["name"]

        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning("scrape_http_error", source=name, status=resp.status)
                    return
                html = await resp.text()
        except Exception as exc:
            logger.warning("scrape_fetch_error", source=name, error=str(exc))
            return

        soup = BeautifulSoup(html, "lxml")

        # Extraction générique : titres + paragraphes
        articles_added = 0
        # Cherche les blocs d'article communs
        article_elements = soup.find_all(["article", "div"], limit=20)
        seen_texts: set[str] = set()

        for elem in article_elements:
            title_tag = elem.find(["h1", "h2", "h3", "h4"])
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            paragraphs = elem.find_all("p")
            text_parts = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
            content = "\n".join(text_parts)

            if len(content) < 50:
                continue
            # Déduplication simple
            key = title[:50]
            if key in seen_texts:
                continue
            seen_texts.add(key)

            await self._rag.add_market_intel(
                source_url=url,
                title=f"[{name}] {title}",
                content=f"{title}\n{content[:1000]}",
            )
            articles_added += 1
            if articles_added >= 10:
                break

        logger.info("scrape_source_done", source=name, articles_added=articles_added)

    async def purge_old_data(self, max_days: int = 30) -> None:
        """Purge market_intel > max_days jours."""
        count = await self._rag.purge_old_intel(max_days)
        logger.info("purge_done", deleted=count, max_days=max_days)

    def _load_tickers(self) -> list[str]:
        """Charge la liste des tickers depuis le CSV."""
        if not os.path.isfile(self._tickers_csv_path):
            logger.error("tickers_csv_not_found", path=self._tickers_csv_path)
            return []
        tickers = []
        try:
            with open(self._tickers_csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ticker = (row.get("ticker") or "").strip()
                    if ticker:
                        tickers.append(ticker)
        except Exception as exc:
            logger.error("tickers_csv_read_error", error=str(exc))
        return tickers

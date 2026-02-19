"""Stocks / crypto price tool — free API (CoinGecko for crypto)."""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Map common symbols to CoinGecko IDs
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
}


class StocksTool:
    """Fetch crypto prices via CoinGecko (no API key required for basic use)."""

    async def get_crypto_prices(self, symbols: Optional[list[str]] = None) -> str:
        """Return current prices for *symbols* (e.g. ['BTC', 'ETH'])."""
        targets = symbols or ["BTC", "ETH"]
        ids = [CRYPTO_IDS.get(s.upper(), s.lower()) for s in targets]

        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": ",".join(ids),
            "vs_currencies": "usd,eur",
            "include_24hr_change": "true",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur cours HTTP {resp.status}"
                    data = await resp.json()
            return _format_prices(data, targets, ids)
        except Exception as exc:
            logger.error("stocks_error", error=str(exc))
            return f"❌ Cours indisponibles : {exc}"


def _format_prices(data: dict, symbols: list[str], ids: list[str]) -> str:
    lines = ["📊 **Cours crypto**"]
    for sym, cg_id in zip(symbols, ids):
        info = data.get(cg_id, {})
        if not info:
            lines.append(f"**{sym}** : données indisponibles")
            continue
        usd = info.get("usd", "?")
        eur = info.get("eur", "?")
        chg = info.get("usd_24h_change")
        trend = ""
        if chg is not None:
            trend = f" ({'+' if chg > 0 else ''}{chg:.2f}% 24h)"
        lines.append(f"**{sym}** : ${usd:,.0f} / €{eur:,.0f}{trend}")
    return "\n".join(lines)

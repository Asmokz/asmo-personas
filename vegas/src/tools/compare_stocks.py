"""Outil de comparaison de 2 à 5 tickers."""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : comparaison fournie à titre informatif uniquement. "
    "Ne constitue pas un conseil en investissement.*"
)


def _fetch_ticker_info(ticker: str) -> dict:
    """Récupère le résumé yfinance d'un ticker (synchrone)."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    info = t.info or {}
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "currency": info.get("currency", "EUR"),
        "market_cap": info.get("marketCap"),
        "pe": info.get("trailingPE") or info.get("forwardPE"),
        "pb": info.get("priceToBook"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "div_yield": info.get("dividendYield"),
        "roe": info.get("returnOnEquity"),
        "beta": info.get("beta"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "sector": info.get("sector", "N/A"),
    }


class CompareStocks:
    """Comparaison côte à côte de plusieurs tickers."""

    async def compare(self, tickers: list[str]) -> str:
        """Compare les tickers donnés et retourne un tableau formaté."""
        if len(tickers) < 2:
            return "Fournissez au moins 2 tickers pour une comparaison."
        if len(tickers) > 5:
            tickers = tickers[:5]

        tickers = [t.upper().strip() for t in tickers]
        loop = asyncio.get_event_loop()

        # Récupération concurrente
        results = await asyncio.gather(
            *[loop.run_in_executor(None, _fetch_ticker_info, t) for t in tickers],
            return_exceptions=True,
        )

        data = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("compare_fetch_error", error=str(r))
                continue
            data.append(r)

        if not data:
            return "Impossible de récupérer les données pour ces tickers."

        def fmt(val, suffix: str = "", decimals: int = 2) -> str:
            if val is None:
                return "N/A"
            return f"{val:.{decimals}f}{suffix}"

        def cap_str(cap) -> str:
            if not cap:
                return "N/A"
            return f"{cap/1e9:.1f}Md" if cap >= 1e9 else f"{cap/1e6:.0f}M"

        # Construit le tableau
        header = ["Métrique"] + [d["ticker"] for d in data]
        rows = [
            ["Nom"] + [d["name"][:20] for d in data],
            ["Secteur"] + [d["sector"][:15] for d in data],
            ["Cours"] + [f"{fmt(d['price'])} {d['currency']}" for d in data],
            ["Cap boursière"] + [cap_str(d["market_cap"]) for d in data],
            ["P/E"] + [fmt(d["pe"], "x") for d in data],
            ["P/B"] + [fmt(d["pb"], "x") for d in data],
            ["EV/EBITDA"] + [fmt(d["ev_ebitda"], "x") for d in data],
            ["Rend. div."] + [fmt(d["div_yield"]*100 if d["div_yield"] else None, "%") for d in data],
            ["ROE"] + [fmt(d["roe"]*100 if d["roe"] else None, "%") for d in data],
            ["Bêta"] + [fmt(d["beta"]) for d in data],
            ["52s haut"] + [fmt(d["52w_high"]) for d in data],
            ["52s bas"] + [fmt(d["52w_low"]) for d in data],
        ]

        # Formatage texte tabulaire
        col_widths = [max(len(str(row[i])) for row in [header] + rows) for i in range(len(header))]
        sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

        def fmt_row(row):
            return "|" + "|".join(f" {str(row[i]):<{col_widths[i]}} " for i in range(len(row))) + "|"

        lines = [
            f"**Comparaison : {', '.join(tickers)}**\n",
            sep,
            fmt_row(header),
            sep,
        ]
        for row in rows:
            lines.append(fmt_row(row))
        lines.append(sep)

        return "\n".join(lines) + _DISCLAIMER

"""Outil diagnostic du portefeuille PEA — lit alita.db en read-only."""
from __future__ import annotations

import asyncio
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : diagnostic fourni à titre informatif uniquement. "
    "Ne constitue pas un conseil en investissement. "
    "Données de cours issues de yfinance, susceptibles de délais.*"
)


def _fetch_current_prices(tickers: list[str]) -> dict[str, Optional[float]]:
    """Récupère les cours actuels via yfinance (synchrone)."""
    import yfinance as yf
    prices = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prices[ticker] = price
        except Exception:
            prices[ticker] = None
    return prices


class PortfolioDiagnostic:
    """Analyse le portefeuille PEA depuis alita.db (lecture seule)."""

    def __init__(self, alita_db_path: str) -> None:
        self._alita_db_path = alita_db_path

    async def diagnose(self) -> str:
        """Retourne un diagnostic complet du portefeuille PEA."""
        # Lecture du portefeuille depuis alita.db
        try:
            positions = await self._read_portfolio()
        except Exception as exc:
            return f"Impossible de lire le portefeuille Alita : {exc}"

        if not positions:
            return "Portefeuille vide ou non renseigné dans Alita."

        # Récupération des cours actuels
        tickers = [p["symbol"] for p in positions]
        try:
            loop = asyncio.get_event_loop()
            prices = await loop.run_in_executor(None, _fetch_current_prices, tickers)
        except Exception as exc:
            logger.warning("portfolio_prices_fetch_error", error=str(exc))
            prices = {t: None for t in tickers}

        # Calcul des P&L
        lines = ["**Diagnostic Portefeuille PEA**\n"]
        lines.append(
            f"{'Ticker':<10} {'Nom':<20} {'Actions':>7} {'PRU':>8} {'Cours':>8} "
            f"{'P&L€':>10} {'P&L%':>7}"
        )
        lines.append("-" * 75)

        total_cost = 0.0
        total_value = 0.0
        has_prices = False

        for pos in positions:
            symbol = pos["symbol"]
            label = (pos.get("label") or symbol)[:19]
            shares = pos.get("shares", 0) or 0
            avg_price = pos.get("avg_price", 0) or 0
            current = prices.get(symbol)

            cost = shares * avg_price
            total_cost += cost

            if current:
                value = shares * current
                total_value += value
                pnl_eur = value - cost
                pnl_pct = ((current - avg_price) / avg_price * 100) if avg_price > 0 else 0
                has_prices = True
                lines.append(
                    f"{symbol:<10} {label:<20} {shares:>7.0f} {avg_price:>8.2f} "
                    f"{current:>8.2f} {pnl_eur:>+10.2f} {pnl_pct:>+7.1f}%"
                )
            else:
                lines.append(
                    f"{symbol:<10} {label:<20} {shares:>7.0f} {avg_price:>8.2f} "
                    f"{'N/A':>8} {'N/A':>10} {'N/A':>7}"
                )

        lines.append("-" * 75)

        if has_prices and total_cost > 0:
            total_pnl = total_value - total_cost
            total_pnl_pct = (total_pnl / total_cost) * 100
            lines.append(f"\n**Total investi** : {total_cost:,.2f} €")
            lines.append(f"**Valorisation** : {total_value:,.2f} €")
            lines.append(
                f"**P&L total** : {total_pnl:+,.2f} € ({total_pnl_pct:+.1f}%)"
            )

        # Analyse de concentration sectorielle (si disponible)
        if len(positions) > 0:
            lines.append(f"\n**Positions** : {len(positions)} ligne(s)")

        return "\n".join(lines) + _DISCLAIMER

    async def _read_portfolio(self) -> list[dict]:
        """Lit le portefeuille depuis alita.db en read-only."""
        async with aiosqlite.connect(f"file:{self._alita_db_path}?mode=ro", uri=True) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT symbol, shares, avg_price, label FROM portfolio ORDER BY symbol"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

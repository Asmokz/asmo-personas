"""Stocks tool — yfinance portfolio + individual quotes (async via executor)."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..db.manager import AlitaDbManager

logger = structlog.get_logger()


class StocksTool:
    """Fetch stock quotes via yfinance (no API key required)."""

    def __init__(self, db: AlitaDbManager) -> None:
        self._db = db

    async def get_portfolio_summary(self) -> str:
        """Return P&L summary for the portfolio stored in DB."""
        portfolio = await self._db.get_portfolio()
        if not portfolio:
            return "📭 Aucune position dans le portefeuille. Utilise `update_portfolio_position` pour en ajouter."
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._sync_portfolio_summary, portfolio)
            return result
        except Exception as exc:
            logger.error("portfolio_error", error=str(exc))
            return f"❌ Erreur portefeuille : {exc}"

    async def get_stock_quote(self, symbol: str) -> str:
        """Return current quote for a single symbol."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._sync_quote, symbol.upper())
            return result
        except Exception as exc:
            logger.error("stock_quote_error", symbol=symbol, error=str(exc))
            return f"❌ Cours indisponible pour {symbol} : {exc}"

    # ------------------------------------------------------------------
    # Sync helpers (run in executor to avoid blocking the event loop)
    # ------------------------------------------------------------------

    def _sync_quote(self, symbol: str) -> str:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="2d")
        if hist.empty:
            return f"❌ Pas de données pour {symbol}"
        prix = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else float(hist["Open"].iloc[-1])
        var = prix - prev
        var_pct = (var / prev * 100) if prev else 0
        trend = "📈" if var >= 0 else "📉"
        sign = "+" if var >= 0 else ""
        return (
            f"{trend} **{symbol}** : {prix:.2f} "
            f"({sign}{var:.2f} / {sign}{var_pct:.2f}%)"
        )

    def _sync_portfolio_summary(self, portfolio: list[dict]) -> str:
        import yfinance as yf
        lines = ["📊 **Portefeuille**\n"]
        total_invested = 0.0
        total_current = 0.0

        for pos in portfolio:
            symbol = pos["symbol"].upper()
            shares = float(pos["shares"])
            avg_price = float(pos["avg_price"])
            label = pos.get("label") or symbol
            try:
                t = yf.Ticker(symbol)
                hist = t.history(period="2d")
                if hist.empty:
                    lines.append(f"• **{symbol}** ({label}) : données indisponibles")
                    continue
                prix = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else float(hist["Open"].iloc[-1])
                var_jour = prix - prev
                var_jour_pct = (var_jour / prev * 100) if prev else 0
                invested = shares * avg_price
                current_val = shares * prix
                pl = current_val - invested
                pl_pct = (pl / invested * 100) if invested else 0
                total_invested += invested
                total_current += current_val
                trend = "📈" if var_jour >= 0 else "📉"
                pl_emoji = "🟢" if pl >= 0 else "🔴"
                sign_j = "+" if var_jour >= 0 else ""
                sign_pl = "+" if pl >= 0 else ""
                lines.append(
                    f"• {trend} **{symbol}** — {label} ({shares:.0f} actions)\n"
                    f"  Prix : {prix:.2f}€ ({sign_j}{var_jour_pct:.2f}% jour) | PRU : {avg_price:.2f}€\n"
                    f"  {pl_emoji} P&L : {sign_pl}{pl:.2f}€ ({sign_pl}{pl_pct:.2f}%)"
                )
            except Exception as exc:
                lines.append(f"• **{symbol}** ({label}) : erreur ({exc})")

        if total_invested > 0:
            total_pl = total_current - total_invested
            total_pl_pct = (total_pl / total_invested * 100)
            total_emoji = "🟢" if total_pl >= 0 else "🔴"
            sign_t = "+" if total_pl >= 0 else ""
            lines.append(
                f"\n**Total** : {total_current:.2f}€ | Investi : {total_invested:.2f}€\n"
                f"{total_emoji} P&L global : {sign_t}{total_pl:.2f}€ ({sign_t}{total_pl_pct:.2f}%)"
            )
        return "\n".join(lines)

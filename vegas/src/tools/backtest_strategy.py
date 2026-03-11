"""Outil de backtesting de stratégie sur historique yfinance."""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : backtesting basé sur données historiques. "
    "Les performances passées ne présagent pas des performances futures. "
    "Simulation simplifiée — ne tient pas compte des frais de courtage, impôts ni dividendes réinvestis.*"
)

_STRATEGIES = ["dca", "buy_and_hold", "momentum"]


def _run_backtest(ticker: str, strategy: str, period: str, monthly_amount: float) -> dict:
    """Exécute le backtest (synchrone, via run_in_executor)."""
    import yfinance as yf
    import pandas as pd

    t = yf.Ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        return {"error": f"Pas d'historique disponible pour {ticker} sur {period}."}

    close = hist["Close"].dropna()
    if len(close) < 5:
        return {"error": "Historique trop court pour un backtest."}

    if strategy == "buy_and_hold":
        # Achat en une fois au début, vente à la fin
        entry_price = float(close.iloc[0])
        exit_price = float(close.iloc[-1])
        shares = monthly_amount / entry_price
        final_value = shares * exit_price
        total_invested = monthly_amount
        pnl = final_value - total_invested
        pnl_pct = (pnl / total_invested) * 100

        return {
            "strategy": "Buy & Hold",
            "ticker": ticker,
            "period": period,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "total_invested": total_invested,
            "final_value": final_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "total_trades": 1,
        }

    elif strategy == "dca":
        # DCA mensuel — achat le premier jour ouvré de chaque mois
        monthly = close.resample("MS").first()
        if len(monthly) == 0:
            monthly = close

        total_shares = 0.0
        total_invested = 0.0
        for price in monthly:
            price = float(price)
            if price > 0:
                shares_bought = monthly_amount / price
                total_shares += shares_bought
                total_invested += monthly_amount

        exit_price = float(close.iloc[-1])
        final_value = total_shares * exit_price
        pnl = final_value - total_invested
        pnl_pct = (pnl / total_invested) * 100 if total_invested > 0 else 0

        avg_cost = total_invested / total_shares if total_shares > 0 else 0

        return {
            "strategy": "DCA Mensuel",
            "ticker": ticker,
            "period": period,
            "monthly_investment": monthly_amount,
            "total_trades": len(monthly),
            "avg_cost": avg_cost,
            "exit_price": exit_price,
            "total_invested": total_invested,
            "total_shares": total_shares,
            "final_value": final_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

    elif strategy == "momentum":
        # Momentum simple : achat si cours > MA50, sinon cash
        if len(close) < 50:
            return {"error": "Historique insuffisant pour le momentum (< 50 jours)."}

        ma50 = close.rolling(50).mean()
        position = 0.0
        total_invested = monthly_amount
        cash = monthly_amount
        trades = 0

        for i in range(50, len(close)):
            price = float(close.iloc[i])
            ma = float(ma50.iloc[i])
            if pd.isna(ma):
                continue
            if cash > 0 and price > ma:
                # Achat
                position = cash / price
                cash = 0.0
                trades += 1
            elif position > 0 and price < ma:
                # Vente
                cash = position * price
                position = 0.0
                trades += 1

        # Liquidation finale
        final_price = float(close.iloc[-1])
        final_value = (position * final_price + cash) if position > 0 else cash
        pnl = final_value - total_invested
        pnl_pct = (pnl / total_invested) * 100

        return {
            "strategy": "Momentum (MA50)",
            "ticker": ticker,
            "period": period,
            "initial_investment": total_invested,
            "final_value": final_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "total_trades": trades,
        }

    return {"error": f"Stratégie inconnue : {strategy}. Options : {', '.join(_STRATEGIES)}"}


class BacktestStrategy:
    """Simulation de stratégie d'investissement sur historique."""

    async def backtest(
        self,
        ticker: str,
        strategy: str = "dca",
        period: str = "3y",
        monthly_amount: float = 500.0,
    ) -> str:
        """Lance le backtest et retourne les résultats formatés."""
        ticker = ticker.upper().strip()
        strategy = strategy.lower().strip()

        if strategy not in _STRATEGIES:
            return (
                f"Stratégie inconnue : « {strategy} ». "
                f"Options disponibles : {', '.join(_STRATEGIES)}"
            )

        valid_periods = ["1y", "2y", "3y", "5y", "10y", "max"]
        if period not in valid_periods:
            period = "3y"

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, _run_backtest, ticker, strategy, period, monthly_amount
            )
        except Exception as exc:
            return f"Erreur lors du backtest : {exc}"

        if "error" in result:
            return f"Backtest échoué : {result['error']}"

        strat_name = result.get("strategy", strategy)
        pnl = result.get("pnl", 0)
        pnl_pct = result.get("pnl_pct", 0)
        final_value = result.get("final_value", 0)
        total_invested = result.get("total_invested") or result.get("initial_investment", 0)

        lines = [
            f"**Backtest : {ticker} — {strat_name} ({period})**\n",
            f"Capital investi total : {total_invested:,.2f} €",
            f"Valeur finale du portefeuille : {final_value:,.2f} €",
            f"P&L : {pnl:+,.2f} € ({pnl_pct:+.1f}%)",
            f"Nombre de transactions : {result.get('total_trades', 'N/A')}",
        ]

        if "avg_cost" in result:
            lines.append(f"Prix de revient moyen (DCA) : {result['avg_cost']:.2f} €")
        if "entry_price" in result:
            lines.append(f"Prix d'entrée : {result['entry_price']:.2f} €")
        if "exit_price" in result:
            lines.append(f"Prix de sortie : {result['exit_price']:.2f} €")

        return "\n".join(lines) + _DISCLAIMER

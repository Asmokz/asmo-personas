"""Outil d'analyse détaillée d'un ticker via yfinance."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : analyse fournie à titre informatif uniquement. "
    "Ne constitue pas un conseil en investissement. "
    "Données yfinance susceptibles de délais ou d'imprécisions.*"
)


def _safe_get(d: dict, *keys: str, default: Any = None) -> Any:
    """Accès sécurisé dans un dict imbriqué."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, default)
        else:
            return default
    return d


def _fetch_yfinance_info(ticker: str) -> dict:
    """Récupère les données yfinance (synchrone, appelé via run_in_executor)."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    info = t.info or {}
    # Historique 1 an pour calculer drawdown et volatilité
    hist = t.history(period="1y")
    if not hist.empty:
        close = hist["Close"]
        roll_max = close.cummax()
        drawdown = ((close - roll_max) / roll_max * 100).min()
        vol_ann = close.pct_change().std() * (252 ** 0.5) * 100
    else:
        drawdown = None
        vol_ann = None
    return {"info": info, "max_drawdown_1y": drawdown, "volatility_1y_ann": vol_ann}


class StockAnalysis:
    """Analyse fondamentale et technique d'un ticker."""

    async def analyze(self, ticker: str) -> str:
        """Retourne une analyse détaillée du ticker."""
        ticker = ticker.upper().strip()
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, _fetch_yfinance_info, ticker)
        except Exception as exc:
            logger.error("stock_analysis_fetch_error", ticker=ticker, error=str(exc))
            return f"Impossible de récupérer les données pour {ticker} : {exc}"

        info = data.get("info", {})
        if not info:
            return f"Aucune donnée disponible pour {ticker}."

        name = info.get("longName") or info.get("shortName") or ticker
        currency = info.get("currency", "EUR")
        exchange = info.get("exchange") or info.get("fullExchangeName", "")
        sector = info.get("sector", "N/A")
        industry = info.get("industry", "N/A")
        country = info.get("country", "N/A")

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose")
        change_1d = ((price - prev_close) / prev_close * 100) if price and prev_close else None

        market_cap = info.get("marketCap")
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        pb_ratio = info.get("priceToBook")
        ps_ratio = info.get("priceToSalesTrailing12Months")
        ev_ebitda = info.get("enterpriseToEbitda")
        div_yield = info.get("dividendYield")
        payout_ratio = info.get("payoutRatio")
        roe = info.get("returnOnEquity")
        roa = info.get("returnOnAssets")
        debt_equity = info.get("debtToEquity")
        fcf = info.get("freeCashflow")
        beta = info.get("beta")
        week_52_high = info.get("fiftyTwoWeekHigh")
        week_52_low = info.get("fiftyTwoWeekLow")
        avg_volume = info.get("averageVolume")

        drawdown = data.get("max_drawdown_1y")
        vol_ann = data.get("volatility_1y_ann")

        def fmt(val: Optional[float], suffix: str = "", decimals: int = 2) -> str:
            if val is None:
                return "N/A"
            return f"{val:.{decimals}f}{suffix}"

        cap_str = "N/A"
        if market_cap:
            cap_str = (
                f"{market_cap/1e9:.1f} Md{currency}"
                if market_cap >= 1e9
                else f"{market_cap/1e6:.0f} M{currency}"
            )

        lines = [
            f"**Analyse : {name} ({ticker})**",
            f"Bourse : {exchange} | Secteur : {sector} | Industrie : {industry} | Pays : {country}",
            "",
            "**Prix & Performance**",
            f"  Cours actuel : {fmt(price)} {currency}",
            f"  Variation 1j : {fmt(change_1d, '%')}",
            f"  52 sem. haut : {fmt(week_52_high)} {currency} | bas : {fmt(week_52_low)} {currency}",
            "",
            "**Valorisation**",
            f"  Capitalisation : {cap_str}",
            f"  P/E  : {fmt(pe_ratio, 'x')}",
            f"  P/B  : {fmt(pb_ratio, 'x')}",
            f"  P/S  : {fmt(ps_ratio, 'x')}",
            f"  EV/EBITDA : {fmt(ev_ebitda, 'x')}",
            "",
            "**Dividendes & Rentabilité**",
            f"  Rendement dividende : {fmt(div_yield*100 if div_yield else None, '%')}",
            f"  Payout ratio : {fmt(payout_ratio*100 if payout_ratio else None, '%')}",
            f"  ROE : {fmt(roe*100 if roe else None, '%')}",
            f"  ROA : {fmt(roa*100 if roa else None, '%')}",
            f"  Free Cash Flow : {fmt(fcf/1e6 if fcf else None)} M{currency}",
            "",
            "**Risque & Volatilité**",
            f"  Bêta : {fmt(beta)}",
            f"  Volatilité annualisée (1 an) : {fmt(vol_ann, '%')}",
            f"  Drawdown max (1 an) : {fmt(drawdown, '%')}",
            f"  Dette/Fonds propres : {fmt(debt_equity)}",
            f"  Volume moyen : {f'{avg_volume:,.0f}' if avg_volume else 'N/A'}",
        ]

        return "\n".join(lines) + _DISCLAIMER

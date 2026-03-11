"""Outil screening des actions PEA éligibles par critères."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import structlog

if TYPE_CHECKING:
    from ..db.market_db import MarketDB

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : ces données sont fournies à titre informatif uniquement. "
    "Elles ne constituent pas un conseil en investissement. "
    "Consultez un professionnel agréé avant toute décision financière.*"
)


class ScreenPEAStocks:
    """Filtre les actions PEA selon des critères fondamentaux."""

    def __init__(self, market_db: "MarketDB") -> None:
        self._db = market_db

    async def screen(
        self,
        sector: Optional[str] = None,
        max_pe: Optional[float] = None,
        min_dividend_yield: Optional[float] = None,
        max_beta: Optional[float] = None,
        min_market_cap: Optional[float] = None,
        limit: int = 15,
    ) -> str:
        """Retourne les actions correspondant aux filtres sous forme de texte."""
        filters: dict[str, Any] = {}
        if sector:
            filters["sector"] = sector
        if max_pe is not None:
            filters["max_pe"] = max_pe
        if min_dividend_yield is not None:
            filters["min_dividend_yield"] = min_dividend_yield
        if max_beta is not None:
            filters["max_beta"] = max_beta
        if min_market_cap is not None:
            filters["min_market_cap"] = min_market_cap

        try:
            rows = await self._db.screen_stocks(filters)
        except Exception as exc:
            logger.error("screen_stocks_error", error=str(exc))
            return f"Erreur lors du screening : {exc}"

        if not rows:
            return "Aucune action trouvée avec ces critères."

        rows = rows[:limit]
        filter_desc = _describe_filters(
            sector, max_pe, min_dividend_yield, max_beta, min_market_cap
        )
        lines = [f"**Screening PEA — {len(rows)} résultat(s)** {filter_desc}\n"]
        lines.append(
            f"{'Ticker':<12} {'Nom':<25} {'Secteur':<18} {'Cours':>8} "
            f"{'P/E':>6} {'Rend.':>6} {'Bêta':>5}"
        )
        lines.append("-" * 85)

        for r in rows:
            ticker = r.get("ticker") or ""
            name = (r.get("name") or "")[:24]
            sector_str = (r.get("sector") or "")[:17]
            price = f"{r['last_price']:.2f}" if r.get("last_price") else "N/A"
            pe = f"{r['pe_ratio']:.1f}" if r.get("pe_ratio") else "N/A"
            div = f"{r['dividend_yield']*100:.1f}%" if r.get("dividend_yield") else "N/A"
            beta = f"{r['beta']:.2f}" if r.get("beta") else "N/A"
            lines.append(
                f"{ticker:<12} {name:<25} {sector_str:<18} {price:>8} "
                f"{pe:>6} {div:>6} {beta:>5}"
            )

        return "\n".join(lines) + _DISCLAIMER


def _describe_filters(
    sector: Optional[str],
    max_pe: Optional[float],
    min_dividend_yield: Optional[float],
    max_beta: Optional[float],
    min_market_cap: Optional[float],
) -> str:
    parts = []
    if sector:
        parts.append(f"secteur={sector}")
    if max_pe is not None:
        parts.append(f"P/E≤{max_pe}")
    if min_dividend_yield is not None:
        parts.append(f"rendement≥{min_dividend_yield*100:.1f}%")
    if max_beta is not None:
        parts.append(f"bêta≤{max_beta}")
    if min_market_cap is not None:
        parts.append(f"cap≥{min_market_cap:.0f}M€")
    return f"({', '.join(parts)})" if parts else "(tous critères)"

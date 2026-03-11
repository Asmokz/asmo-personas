"""Outil vue d'ensemble d'un secteur Euronext."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..db.market_db import MarketDB

logger = structlog.get_logger()

_DISCLAIMER = (
    "\n\n*Disclaimer : données à titre informatif uniquement. "
    "Ne constitue pas un conseil en investissement.*"
)

_SECTORS = [
    "Luxe", "Consommation", "Énergie", "Santé", "Industrie",
    "Finance", "Matériaux", "Télécoms", "Utilities", "Technologie", "Pharma",
]


class SectorOverview:
    """Vue d'ensemble d'un secteur Euronext depuis la base locale."""

    def __init__(self, market_db: "MarketDB") -> None:
        self._db = market_db

    async def get_overview(self, sector: str) -> str:
        """Retourne un résumé des actions du secteur avec métriques agrégées."""
        try:
            rows = await self._db.get_sector_stocks(sector)
        except Exception as exc:
            return f"Erreur lors de la récupération du secteur {sector} : {exc}"

        if not rows:
            sectors_str = ", ".join(_SECTORS)
            return (
                f"Aucune action trouvée pour le secteur « {sector} ».\n"
                f"Secteurs disponibles : {sectors_str}"
            )

        # Calcul des métriques agrégées (en ignorant les N/A)
        prices = [r["last_price"] for r in rows if r.get("last_price")]
        pe_ratios = [r["pe_ratio"] for r in rows if r.get("pe_ratio") and r["pe_ratio"] > 0]
        div_yields = [r["dividend_yield"] for r in rows if r.get("dividend_yield")]
        betas = [r["beta"] for r in rows if r.get("beta")]
        changes_1d = [r["change_1d"] for r in rows if r.get("change_1d") is not None]

        def avg(lst) -> str:
            if not lst:
                return "N/A"
            return f"{sum(lst)/len(lst):.2f}"

        lines = [
            f"**Secteur {sector} — {len(rows)} action(s) dans la base**\n",
            f"P/E moyen : {avg(pe_ratios)}x  |  "
            f"Rendement moyen : {avg([y*100 for y in div_yields])}%  |  "
            f"Bêta moyen : {avg(betas)}",
            f"Variation moyenne (1j) : {avg(changes_1d)}%",
            "",
            f"{'Ticker':<12} {'Nom':<25} {'Cours':>8} {'1j%':>6} {'P/E':>6} {'Rend.':>6} {'Bêta':>5}",
            "-" * 72,
        ]

        for r in rows:
            ticker = r.get("ticker") or ""
            name = (r.get("name") or "")[:24]
            price = f"{r['last_price']:.2f}" if r.get("last_price") else "N/A"
            chg = f"{r['change_1d']:+.1f}%" if r.get("change_1d") is not None else "N/A"
            pe = f"{r['pe_ratio']:.1f}" if r.get("pe_ratio") else "N/A"
            div = f"{r['dividend_yield']*100:.1f}%" if r.get("dividend_yield") else "N/A"
            beta = f"{r['beta']:.2f}" if r.get("beta") else "N/A"
            lines.append(
                f"{ticker:<12} {name:<25} {price:>8} {chg:>6} {pe:>6} {div:>6} {beta:>5}"
            )

        return "\n".join(lines) + _DISCLAIMER

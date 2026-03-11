"""Base de données SQLite pour les données de marché PEA."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pea_stocks (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    market_cap REAL,
    currency TEXT,
    last_price REAL,
    change_1d REAL,
    change_1m REAL,
    change_6m REAL,
    change_1y REAL,
    pe_ratio REAL,
    dividend_yield REAL,
    beta REAL,
    volume_avg REAL,
    updated_at TEXT
);
"""


class MarketDB:
    """Gestion SQLite de la table pea_stocks."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Crée la table si elle n'existe pas."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        logger.info("market_db_initialized", path=self._db_path)

    async def upsert_stock(self, data: dict[str, Any]) -> None:
        """Insère ou met à jour un ticker dans pea_stocks."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO pea_stocks
                    (ticker, name, sector, market_cap, currency, last_price,
                     change_1d, change_1m, change_6m, change_1y,
                     pe_ratio, dividend_yield, beta, volume_avg, updated_at)
                VALUES
                    (:ticker, :name, :sector, :market_cap, :currency, :last_price,
                     :change_1d, :change_1m, :change_6m, :change_1y,
                     :pe_ratio, :dividend_yield, :beta, :volume_avg, :updated_at)
                ON CONFLICT(ticker) DO UPDATE SET
                    name = excluded.name,
                    sector = excluded.sector,
                    market_cap = excluded.market_cap,
                    currency = excluded.currency,
                    last_price = excluded.last_price,
                    change_1d = excluded.change_1d,
                    change_1m = excluded.change_1m,
                    change_6m = excluded.change_6m,
                    change_1y = excluded.change_1y,
                    pe_ratio = excluded.pe_ratio,
                    dividend_yield = excluded.dividend_yield,
                    beta = excluded.beta,
                    volume_avg = excluded.volume_avg,
                    updated_at = excluded.updated_at
                """,
                {**data, "updated_at": now},
            )
            await db.commit()

    async def get_all_stocks(self) -> list[dict]:
        """Retourne tous les tickers de la base."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pea_stocks ORDER BY market_cap DESC NULLS LAST") as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def screen_stocks(self, filters: dict[str, Any]) -> list[dict]:
        """Filtre les actions selon des critères dynamiques.

        filters peut contenir :
        - sector : str
        - max_pe : float
        - min_dividend_yield : float
        - max_beta : float
        - min_market_cap : float (en milliards EUR)
        """
        conditions: list[str] = []
        params: list[Any] = []

        if sector := filters.get("sector"):
            conditions.append("sector = ?")
            params.append(sector)
        if max_pe := filters.get("max_pe"):
            conditions.append("pe_ratio IS NOT NULL AND pe_ratio > 0 AND pe_ratio <= ?")
            params.append(float(max_pe))
        if min_div := filters.get("min_dividend_yield"):
            conditions.append("dividend_yield IS NOT NULL AND dividend_yield >= ?")
            params.append(float(min_div))
        if max_beta := filters.get("max_beta"):
            conditions.append("beta IS NOT NULL AND beta <= ?")
            params.append(float(max_beta))
        if min_cap := filters.get("min_market_cap"):
            # market_cap stocké en unité native (souvent en unité locale)
            conditions.append("market_cap IS NOT NULL AND market_cap >= ?")
            params.append(float(min_cap))

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM pea_stocks {where} ORDER BY market_cap DESC NULLS LAST"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_sector_stocks(self, sector: str) -> list[dict]:
        """Retourne toutes les actions d'un secteur donné."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM pea_stocks WHERE sector = ? ORDER BY market_cap DESC NULLS LAST",
                (sector,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_stock(self, ticker: str) -> Optional[dict]:
        """Retourne les données d'un ticker précis."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM pea_stocks WHERE ticker = ?", (ticker.upper(),)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

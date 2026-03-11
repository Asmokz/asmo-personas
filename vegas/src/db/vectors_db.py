"""Base de données SQLite pour les vecteurs RAG VEGAS.

Deux couches :
- knowledge_vectors  : knowledge statique (fichiers MD indexés au démarrage)
- market_intel_vectors : market intelligence dynamique (news, articles scraped)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

_CREATE_KNOWLEDGE = """
CREATE TABLE IF NOT EXISTS knowledge_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    chunk_idx INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    file_hash TEXT
);
"""

_MIGRATE_KNOWLEDGE_HASH = "ALTER TABLE knowledge_vectors ADD COLUMN file_hash TEXT"

_CREATE_MARKET_INTEL = """
CREATE TABLE IF NOT EXISTS market_intel_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT,
    title TEXT,
    content TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class VectorsDB:
    """Gestion des deux tables de vecteurs RAG VEGAS."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        """Crée les tables si elles n'existent pas et applique les migrations."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_KNOWLEDGE)
            await db.execute(_CREATE_MARKET_INTEL)
            # Migration : ajouter file_hash si absent (idempotent)
            try:
                await db.execute(_MIGRATE_KNOWLEDGE_HASH)
            except Exception:
                pass  # colonne déjà présente
            await db.commit()
        logger.info("vectors_db_initialized", path=self._db_path)

    # ------------------------------------------------------------------
    # Knowledge vectors (couche statique)
    # ------------------------------------------------------------------

    async def knowledge_exists(self, source: str) -> bool:
        """Vérifie si un fichier source a déjà été indexé."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM knowledge_vectors WHERE source = ?", (source,)
            ) as cur:
                row = await cur.fetchone()
        return (row[0] if row else 0) > 0

    async def get_knowledge_hash(self, source: str) -> Optional[str]:
        """Retourne le hash MD5 stocké pour une source, ou None si absent."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT file_hash FROM knowledge_vectors WHERE source = ? LIMIT 1",
                (source,),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def save_knowledge_chunk(
        self,
        source: str,
        chunk_idx: int,
        content: str,
        embedding: list[float],
        file_hash: Optional[str] = None,
    ) -> None:
        """Persiste un chunk de knowledge avec son embedding."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO knowledge_vectors (source, chunk_idx, content, embedding, indexed_at, file_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source, chunk_idx, content, json.dumps(embedding), now, file_hash),
            )
            await db.commit()

    async def get_all_knowledge_vectors(self) -> list[dict]:
        """Retourne tous les chunks de knowledge avec leur embedding désérialisé."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, source, chunk_idx, content, embedding, indexed_at FROM knowledge_vectors"
            ) as cur:
                rows = await cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            try:
                r["embedding"] = json.loads(r["embedding"])
            except Exception:
                r["embedding"] = []
            result.append(r)
        return result

    async def delete_knowledge_source(self, source: str) -> None:
        """Supprime tous les chunks d'une source (pour réindexation)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM knowledge_vectors WHERE source = ?", (source,))
            await db.commit()

    # ------------------------------------------------------------------
    # Market intel vectors (couche dynamique)
    # ------------------------------------------------------------------

    async def save_market_intel(
        self,
        source_url: Optional[str],
        title: Optional[str],
        content: str,
        embedding: list[float],
    ) -> None:
        """Persiste un chunk de market intelligence avec son embedding."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO market_intel_vectors (source_url, title, content, embedding, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_url, title, content, json.dumps(embedding), now),
            )
            await db.commit()

    async def get_all_market_intel_vectors(self) -> list[dict]:
        """Retourne tous les chunks de market intel avec embedding désérialisé."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, source_url, title, content, embedding, created_at FROM market_intel_vectors"
            ) as cur:
                rows = await cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            try:
                r["embedding"] = json.loads(r["embedding"])
            except Exception:
                r["embedding"] = []
            result.append(r)
        return result

    async def purge_old_intel(self, max_days: int = 30) -> int:
        """Supprime les chunks de market_intel plus vieux que max_days jours.

        Retourne le nombre de lignes supprimées.
        """
        from datetime import timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_days)
        ).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM market_intel_vectors WHERE created_at < ?",
                (cutoff,),
            ) as cur:
                row = await cur.fetchone()
                count = row[0] if row else 0
            if count > 0:
                await db.execute(
                    "DELETE FROM market_intel_vectors WHERE created_at < ?", (cutoff,)
                )
                await db.commit()
        if count > 0:
            logger.info("market_intel_purged", count=count, max_days=max_days)
        return count

    async def count_market_intel(self) -> int:
        """Retourne le nombre de chunks de market intel."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM market_intel_vectors") as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

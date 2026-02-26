"""Semantic library index — Ollama embeddings + SQLite vector store.

Workflow:
- On startup: init DB, check existing index size, fire background sync.
- sync(): fetches all Jellyfin items, embeds those not yet indexed.
- semantic_search(query): embeds query, cosine similarity against all stored
  vectors (in-memory numpy, fast enough for < 5000 items).

The index is stored in a dedicated SQLite file (/data/giorgio_vectors.db),
separate from the MariaDB used for watch history.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

import aiosqlite
import structlog

if TYPE_CHECKING:
    from asmo_commons.llm.ollama_client import OllamaClient
    from .jellyfin_client import JellyfinClient

logger = structlog.get_logger()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS content_vectors (
    content_id  TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    indexed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class LibraryIndex:
    """Semantic search index over the Jellyfin library."""

    def __init__(
        self,
        jellyfin: JellyfinClient,
        ollama: OllamaClient,
        embed_model: str,
        db_path: str = "/data/giorgio_vectors.db",
    ) -> None:
        self._jellyfin = jellyfin
        self._ollama = ollama
        self._embed_model = embed_model
        self._db_path = db_path
        self._ready = False

    async def init(self) -> None:
        """Create the DB table and mark ready if already populated."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_CREATE_SQL)
            await db.commit()
            async with db.execute("SELECT COUNT(*) FROM content_vectors") as cur:
                row = await cur.fetchone()
            count = row[0] if row else 0
        if count > 0:
            self._ready = True
            logger.info("library_index_ready", indexed=count)
        else:
            logger.info("library_index_empty")

    async def sync(self) -> None:
        """Embed all Jellyfin items not yet in the index."""
        items = await self._jellyfin.get_all_items_raw()
        if not items:
            logger.warning("library_index_sync_no_items")
            return

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT content_id FROM content_vectors") as cur:
                existing = {row[0] async for row in cur}

        new_items = [it for it in items if it.get("Id") not in existing]
        if not new_items:
            logger.info("library_index_sync_up_to_date", total=len(items))
            self._ready = True
            return

        logger.info("library_index_sync_start", total=len(items), to_embed=len(new_items))
        embedded = 0

        for item in new_items:
            try:
                text = _item_to_text(item)
                vec = await self._ollama.embed(text, model=self._embed_model)
                meta = {
                    "type": (item.get("Type") or "").lower(),
                    "year": item.get("ProductionYear"),
                    "genres": item.get("Genres", []),
                    "overview": (item.get("Overview") or "")[:300],
                }
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO content_vectors "
                        "(content_id, title, metadata, embedding) VALUES (?, ?, ?, ?)",
                        (
                            item["Id"],
                            item.get("Name", ""),
                            json.dumps(meta),
                            json.dumps(vec),
                        ),
                    )
                    await db.commit()
                embedded += 1
                # Yield control to avoid starving the event loop
                if embedded % 20 == 0:
                    await asyncio.sleep(0)
            except Exception as exc:
                logger.debug(
                    "library_index_embed_error",
                    title=item.get("Name"),
                    error=str(exc),
                )

        self._ready = True
        logger.info("library_index_sync_done", embedded=embedded, skipped=len(existing))

    async def semantic_search(self, query: str, limit: int = 6) -> str:
        """Find content semantically similar to the query."""
        if not self._ready:
            return (
                "⏳ L'index sémantique est en cours de construction "
                "(première synchronisation). Utilise `browse_library_by_genre` "
                "en attendant."
            )
        try:
            import numpy as np

            query_vec = await self._ollama.embed(query, model=self._embed_model)
            q = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q))
            if q_norm == 0:
                return "❌ Impossible de calculer l'embedding de la requête."

            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT title, metadata, embedding FROM content_vectors"
                ) as cur:
                    rows = await cur.fetchall()

            if not rows:
                return "📭 Index vide — synchronisation en cours."

            scores: list[tuple[float, str, dict]] = []
            for title, metadata_json, embedding_json in rows:
                try:
                    vec = np.array(json.loads(embedding_json), dtype=np.float32)
                    v_norm = float(np.linalg.norm(vec))
                    if v_norm == 0:
                        continue
                    score = float(np.dot(q, vec) / (q_norm * v_norm))
                    scores.append((score, title, json.loads(metadata_json)))
                except Exception:
                    continue

            scores.sort(key=lambda x: x[0], reverse=True)

            lines = [f"🔍 **Recherche sémantique** — « {query} »\n"]
            for score, title, meta in scores[:limit]:
                year = meta.get("year") or ""
                genres = ", ".join((meta.get("genres") or [])[:3])
                overview = (meta.get("overview") or "")[:120]
                icon = "🎬" if meta.get("type") == "movie" else "📺"
                meta_str = " | ".join(filter(None, [str(year), genres]))
                lines.append(f"{icon} **{title}** ({meta_str})")
                if overview:
                    lines.append(f"  _{overview}_")
            return "\n".join(lines)

        except Exception as exc:
            logger.error("semantic_search_error", query=query, error=str(exc))
            return f"❌ Recherche sémantique indisponible : {exc}"


def _item_to_text(item: dict) -> str:
    """Build a rich text for embedding from a Jellyfin item dict."""
    parts = [item.get("Name", "")]
    if year := item.get("ProductionYear"):
        parts.append(str(year))
    if item_type := item.get("Type"):
        parts.append(item_type)
    if genres := item.get("Genres"):
        parts.append("Genres: " + ", ".join(genres))
    if overview := (item.get("Overview") or "")[:300]:
        parts.append(overview)
    return " | ".join(p for p in parts if p)

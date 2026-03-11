"""VegasRAG — RAG à deux couches : knowledge statique + market intel dynamique.

Couche 1 : fichiers MD indexés au démarrage (knowledge/)
Couche 2 : articles et news financières scraped quotidiennement (market_intel_vectors)

La recherche fusionne les deux couches avec recency weight sur la couche 2.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from asmo_commons.llm.ollama_client import OllamaClient
    from ..db.vectors_db import VectorsDB

logger = structlog.get_logger()

# Poids de récence pour la couche 2 : (max_jours, weight)
_RECENCY_WEIGHTS: list[tuple[int, float]] = [
    (1, 1.0),
    (3, 0.8),
    (7, 0.5),
    (14, 0.2),
]
_RECENCY_MAX_DAYS = 14  # au-delà : exclusion

# Paramètres de chunking
_CHUNK_MAX_TOKENS = 500    # environ 500 tokens ≈ 375 mots
_CHUNK_OVERLAP_TOKENS = 50  # chevauchement entre chunks
_WORDS_PER_TOKEN = 0.75    # estimation : 1 token ≈ 0.75 mot

_SIMILARITY_THRESHOLD = 0.55  # seuil cosine minimum


def _get_recency_weight(created_at: str) -> float:
    """Calcule le poids de récence d'un chunk selon sa date de création.

    Retourne 0.0 si le chunk est trop vieux (> _RECENCY_MAX_DAYS jours).
    """
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        if days_ago > _RECENCY_MAX_DAYS:
            return 0.0
        for max_days, weight in _RECENCY_WEIGHTS:
            if days_ago <= max_days:
                return weight
        return 0.0
    except Exception:
        return 0.5  # valeur par défaut si date invalide


def _chunk_text(text: str, source: str) -> list[str]:
    """Découpe un texte en chunks avec overlap.

    Stratégie : split par paragraphes, puis agrège jusqu'à ~500 tokens.
    """
    max_words = int(_CHUNK_MAX_TOKENS * _WORDS_PER_TOKEN)
    overlap_words = int(_CHUNK_OVERLAP_TOKENS * _WORDS_PER_TOKEN)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current_words: list[str] = []

    for para in paragraphs:
        para_words = para.split()
        if len(current_words) + len(para_words) > max_words:
            if current_words:
                chunks.append(" ".join(current_words))
                # overlap : garder les derniers overlap_words
                current_words = current_words[-overlap_words:] if overlap_words > 0 else []
        current_words.extend(para_words)

    if current_words:
        chunks.append(" ".join(current_words))

    logger.debug("text_chunked", source=source, chunks=len(chunks))
    return chunks


class VegasRAG:
    """RAG à deux couches : knowledge statique + market intel dynamique."""

    def __init__(
        self,
        db: "VectorsDB",
        ollama: "OllamaClient",
        embed_model: str,
        knowledge_dir: str,
    ) -> None:
        self._db = db
        self._ollama = ollama
        self._embed_model = embed_model
        self._knowledge_dir = knowledge_dir

    async def build_knowledge_index(self) -> None:
        """Indexe tous les fichiers MD du dossier knowledge/ au démarrage.

        Ignore les fichiers déjà indexés (idempotent).
        """
        if not os.path.isdir(self._knowledge_dir):
            logger.warning("knowledge_dir_not_found", path=self._knowledge_dir)
            return

        md_files = sorted(
            f for f in os.listdir(self._knowledge_dir) if f.endswith(".md")
        )
        indexed = 0
        for filename in md_files:
            filepath = os.path.join(self._knowledge_dir, filename)
            if await self._db.knowledge_exists(filename):
                logger.debug("knowledge_already_indexed", source=filename)
                continue
            try:
                with open(filepath, encoding="utf-8") as fh:
                    text = fh.read()
                chunks = _chunk_text(text, filename)
                for i, chunk in enumerate(chunks):
                    embedding = await self._ollama.embed(chunk, model=self._embed_model)
                    await self._db.save_knowledge_chunk(filename, i, chunk, embedding)
                logger.info(
                    "knowledge_indexed",
                    source=filename,
                    chunks=len(chunks),
                )
                indexed += 1
            except Exception as exc:
                logger.error("knowledge_index_failed", source=filename, error=str(exc))

        logger.info("knowledge_index_complete", files_indexed=indexed, total=len(md_files))

    async def search(self, query: str, top_k: int = 5) -> str:
        """Recherche fusionnée couches 1+2 avec recency weight sur couche 2.

        Retourne une chaîne formatée avec les sources et dates, ou une chaîne vide.
        """
        try:
            import numpy as np

            query_vec = await self._ollama.embed(query, model=self._embed_model)
            q = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q))
            if q_norm == 0:
                return ""

            scored: list[tuple[float, dict]] = []

            # --- Couche 1 : knowledge statique ---
            knowledge_rows = await self._db.get_all_knowledge_vectors()
            for row in knowledge_rows:
                if not row.get("embedding"):
                    continue
                try:
                    vec = np.array(row["embedding"], dtype=np.float32)
                    v_norm = float(np.linalg.norm(vec))
                    if v_norm == 0:
                        continue
                    cosine = float(np.dot(q, vec) / (q_norm * v_norm))
                    if cosine < _SIMILARITY_THRESHOLD:
                        continue
                    scored.append((cosine, {**row, "_layer": "knowledge"}))
                except Exception:
                    continue

            # --- Couche 2 : market intel dynamique ---
            intel_rows = await self._db.get_all_market_intel_vectors()
            for row in intel_rows:
                if not row.get("embedding"):
                    continue
                try:
                    vec = np.array(row["embedding"], dtype=np.float32)
                    v_norm = float(np.linalg.norm(vec))
                    if v_norm == 0:
                        continue
                    cosine = float(np.dot(q, vec) / (q_norm * v_norm))
                    if cosine < _SIMILARITY_THRESHOLD:
                        continue
                    recency = _get_recency_weight(row.get("created_at", ""))
                    if recency == 0.0:
                        continue  # trop vieux, exclu
                    weighted_score = cosine * recency
                    scored.append((weighted_score, {**row, "_layer": "market_intel"}))
                except Exception:
                    continue

            if not scored:
                return ""

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:top_k]

            logger.info(
                "rag_search",
                query_len=len(query),
                hits=len(top),
                knowledge_total=len(knowledge_rows),
                intel_total=len(intel_rows),
            )

            lines = ["[Contexte RAG VEGAS — sources financières]"]
            for score, row in top:
                layer = row.get("_layer", "")
                if layer == "knowledge":
                    source = row.get("source", "")
                    date = row.get("indexed_at", "")[:10]
                    lines.append(f"\n**Source** : {source} (indexé le {date})")
                else:
                    title = row.get("title") or "Sans titre"
                    url = row.get("source_url") or ""
                    date = row.get("created_at", "")[:10]
                    ref = f"{title} ({url})" if url else title
                    lines.append(f"\n**Source** : {ref} — {date}")
                lines.append(row.get("content", "")[:500])
            lines.append("\n[Fin du contexte RAG]")
            return "\n".join(lines)

        except Exception as exc:
            logger.warning("rag_search_failed", error=str(exc))
            return ""

    async def add_market_intel(
        self,
        source_url: Optional[str],
        title: Optional[str],
        content: str,
    ) -> None:
        """Ajoute un chunk de market intelligence dynamique avec son embedding."""
        try:
            embedding = await self._ollama.embed(content, model=self._embed_model)
            await self._db.save_market_intel(source_url, title, content, embedding)
            logger.debug(
                "market_intel_added",
                title=title,
                content_len=len(content),
            )
        except Exception as exc:
            logger.warning("market_intel_add_failed", error=str(exc))

    async def purge_old_intel(self, max_days: int = 30) -> int:
        """Supprime les chunks de market_intel > max_days jours.

        Retourne le nombre de chunks supprimés.
        """
        return await self._db.purge_old_intel(max_days)

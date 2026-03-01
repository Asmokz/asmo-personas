"""Long-term memory — embed conversations and retrieve relevant past exchanges.

Workflow:
- After each user/assistant exchange, embed the pair and save to SQLite.
- Before each LLM call, search for similar past exchanges via cosine similarity.
- Inject top results as context into the user message, helping Alita recall
  facts discussed weeks or months ago.

Storage: conversation_vectors table in the existing alita.db SQLite.
Embeddings: nomic-embed-text via Ollama /api/embed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from asmo_commons.llm.ollama_client import OllamaClient
    from ..db.manager import AlitaDbManager

logger = structlog.get_logger()

# Minimum message length worth storing (to skip trivial one-liners)
_MIN_USER_LEN = 20
_MIN_ASSISTANT_LEN = 40
# Similarity threshold below which a memory is considered irrelevant.
# nomic-embed-text produces scores of 0.60–0.68 for semantically related
# conversation pairs — 0.72 was too high and caused zero recalls in practice.
_SIMILARITY_THRESHOLD = 0.60
# Maximum number of memories to retrieve per query
_DEFAULT_LIMIT = 3


class LongTermMemory:
    """Semantic memory store for Alita's past conversations."""

    def __init__(
        self,
        db: AlitaDbManager,
        ollama: OllamaClient,
        embed_model: str = "nomic-embed-text",
    ) -> None:
        self._db = db
        self._ollama = ollama
        self._embed_model = embed_model

    async def embed_exchange(
        self,
        user_msg: str,
        assistant_msg: str,
        channel_id: str | None = None,
    ) -> None:
        """Embed a user/assistant exchange and persist it.

        Silently skips short or trivial exchanges — they rarely contain
        useful long-term information.
        """
        if len(user_msg) < _MIN_USER_LEN or len(assistant_msg) < _MIN_ASSISTANT_LEN:
            return

        text = f"Utilisateur: {user_msg}\nAlita: {assistant_msg}"
        try:
            vec = await self._ollama.embed(text, model=self._embed_model)
            await self._db.save_conversation_vector(
                user_msg=user_msg,
                assistant_msg=assistant_msg,
                embedding=vec,
                channel_id=channel_id,
            )
            logger.info("ltm_exchange_saved", user_len=len(user_msg), reply_len=len(assistant_msg))
        except Exception as exc:
            # Non-fatal — long-term memory is best-effort
            logger.warning("ltm_embed_failed", error=str(exc))

    async def search_relevant(self, query: str, limit: int = _DEFAULT_LIMIT) -> str:
        """Return a formatted context block of relevant past exchanges.

        Returns an empty string if nothing is relevant or the store is empty.
        """
        try:
            import numpy as np

            count = await self._db.count_conversation_vectors()
            if count == 0:
                return ""

            query_vec = await self._ollama.embed(query, model=self._embed_model)
            q = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q))
            if q_norm == 0:
                return ""

            rows = await self._db.get_all_conversation_vectors()

            scores: list[tuple[float, dict]] = []
            for row in rows:
                try:
                    vec = np.array(row["embedding"], dtype=np.float32)
                    v_norm = float(np.linalg.norm(vec))
                    if v_norm == 0:
                        continue
                    score = float(np.dot(q, vec) / (q_norm * v_norm))
                    if score >= _SIMILARITY_THRESHOLD:
                        scores.append((score, row))
                except Exception:
                    continue

            if not scores:
                return ""

            scores.sort(key=lambda x: x[0], reverse=True)
            top = scores[:limit]

            logger.info("ltm_search", query_len=len(query), hits=len(top), total=count, threshold=_SIMILARITY_THRESHOLD)

            lines = ["[Souvenirs pertinents de nos échanges passés]"]
            for _, row in top:
                date = (row.get("created_at") or "")[:10]
                lines.append(f"• ({date}) Toi: {row['user_msg']}")
                lines.append(f"  Moi: {row['assistant_msg'][:300]}")
            lines.append("[Fin des souvenirs]\n")
            return "\n".join(lines)

        except Exception as exc:
            logger.warning("ltm_search_failed", error=str(exc))
            return ""

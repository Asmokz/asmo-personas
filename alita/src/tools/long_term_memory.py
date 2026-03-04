"""Long-term memory — embed conversations and retrieve relevant past exchanges.

Workflow:
- After each user/assistant exchange, embed the pair and save to SQLite.
- Before each LLM call, search for similar past exchanges via cosine similarity.
- Inject top results as context into the user message, helping Alita recall
  facts discussed weeks or months ago.

Storage: conversation_vectors table in the existing alita.db SQLite.
Embeddings: nomic-embed-text via Ollama /api/embed.

Retrieval uses a hybrid score combining:
- Base cosine similarity (semantic relevance)
- Recency bonus: exponential decay with configurable half-life
- Session boost: flat bonus when the candidate belongs to the current conversation
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from asmo_commons.llm.ollama_client import OllamaClient
    from ..db.manager import AlitaDbManager

logger = structlog.get_logger()

# Minimum message length worth storing (to skip trivial one-liners)
_MIN_USER_LEN = 20
_MIN_ASSISTANT_LEN = 40
# Cosine similarity threshold — candidates below this are discarded before hybrid scoring.
# nomic-embed-text produces scores of 0.60–0.68 for semantically related pairs.
_SIMILARITY_THRESHOLD = 0.60
# Maximum number of memories to retrieve per query
_DEFAULT_LIMIT = 3

# Hybrid scoring parameters (tunable)
_RECENCY_WEIGHT: float = 0.15    # max recency contribution (at t=0)
_SESSION_BOOST: float = 0.25     # flat bonus for same-session candidates
_HALF_LIFE_HOURS: float = 7 * 24  # recency half-life (7 days)


def compute_hybrid_score(
    cosine: float,
    created_at: str | None,
    candidate_channel_id: str | None,
    current_session_id: str | None,
    recency_weight: float = _RECENCY_WEIGHT,
    session_boost: float = _SESSION_BOOST,
    half_life_hours: float = _HALF_LIFE_HOURS,
) -> float:
    """Combine cosine similarity with recency decay and session boost.

    Args:
        cosine: Base semantic similarity score [0, 1].
        created_at: ISO 8601 timestamp of the stored exchange.
        candidate_channel_id: channel_id stored with the vector.
        current_session_id: conv_id of the active conversation (or None).
        recency_weight: Max contribution of the recency term.
        session_boost: Flat bonus when candidate is from the current session.
        half_life_hours: Exponential decay half-life in hours.

    Returns:
        Hybrid score capped at 1.0.
    """
    score = cosine

    # Recency bonus: exponential decay — full weight at t=0, halves every half_life_hours
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at)
            hours_ago = (datetime.now() - dt).total_seconds() / 3600
            recency = math.exp(-math.log(2) * hours_ago / half_life_hours)
            score += recency_weight * recency
        except Exception:
            pass

    # Session boost: same conversation gets a flat priority bump
    if current_session_id and candidate_channel_id == current_session_id:
        score += session_boost

    return min(score, 1.0)


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

    async def search_relevant(
        self,
        query: str,
        limit: int = _DEFAULT_LIMIT,
        current_session_id: str | None = None,
    ) -> str:
        """Return a formatted context block of relevant past exchanges.

        Loads all stored vectors (cross-conversation), filters on cosine similarity,
        then ranks by hybrid score so that recent and same-session memories bubble up.

        Args:
            query: The user query to match against.
            limit: Maximum number of memories to return.
            current_session_id: Active conv_id — candidates from this session receive
                a session boost, ensuring they rank above cross-conversation results
                when semantically equivalent.

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

            # Load all vectors — hybrid scoring handles cross-session relevance
            rows = await self._db.get_all_conversation_vectors()

            scores: list[tuple[float, dict]] = []
            for row in rows:
                try:
                    vec = np.array(row["embedding"], dtype=np.float32)
                    v_norm = float(np.linalg.norm(vec))
                    if v_norm == 0:
                        continue
                    cosine = float(np.dot(q, vec) / (q_norm * v_norm))
                    if cosine < _SIMILARITY_THRESHOLD:
                        continue
                    hybrid = compute_hybrid_score(
                        cosine=cosine,
                        created_at=row.get("created_at"),
                        candidate_channel_id=row.get("channel_id"),
                        current_session_id=current_session_id,
                    )
                    scores.append((hybrid, row))
                except Exception:
                    continue

            if not scores:
                return ""

            scores.sort(key=lambda x: x[0], reverse=True)
            top = scores[:limit]

            logger.info(
                "ltm_search",
                query_len=len(query),
                hits=len(top),
                total=count,
                threshold=_SIMILARITY_THRESHOLD,
                session_id=current_session_id,
            )

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

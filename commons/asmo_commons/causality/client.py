"""Causality middleware — fire-and-forget Redis publisher for LLM call metrics."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

CHANNEL = "asmo.causality"


class CausalityClient:
    """Publishes LLM call events to Redis for the Causality monitoring service.

    Completely non-blocking: all publishes are fire-and-forget asyncio tasks.
    If Redis is unavailable, events are silently dropped — never blocks the bot.
    """

    def __init__(self, redis_url: str, persona: str) -> None:
        self._redis_url = redis_url
        self.persona = persona
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def _publish(self, data: dict) -> None:
        try:
            r = await self._get_redis()
            await r.publish(CHANNEL, json.dumps(data, default=str))
        except Exception as exc:
            logger.debug("causality_publish_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Public API — called from OllamaClient hooks
    # ------------------------------------------------------------------

    def record_call_start(
        self,
        call_id: str,
        conv_id: str | None,
        model: str,
        messages: list[dict],
        tool_names: list[str],
    ) -> None:
        """Fire-and-forget: publish call_start event."""
        asyncio.create_task(
            self._publish({
                "event": "call_start",
                "call_id": call_id,
                "conv_id": conv_id,
                "persona": self.persona,
                "model": model,
                "ts_start": time.time(),
                "messages": messages,
                "tool_names": tool_names,
            })
        )

    def record_call_end(
        self,
        call_id: str,
        ts_start: float,
        ollama_data: dict,
    ) -> None:
        """Fire-and-forget: publish call_end event with Ollama stats."""
        asyncio.create_task(self._emit_call_end(call_id, ts_start, ollama_data))

    async def _emit_call_end(
        self, call_id: str, ts_start: float, ollama_data: dict
    ) -> None:
        eval_count = ollama_data.get("eval_count", 0)
        eval_duration_ns = ollama_data.get("eval_duration", 0)
        prompt_eval_count = ollama_data.get("prompt_eval_count", 0)
        load_duration_ns = ollama_data.get("load_duration", 0)
        tokens_per_sec = (
            round(eval_count / (eval_duration_ns / 1e9), 1)
            if eval_duration_ns > 0 else 0.0
        )
        await self._publish({
            "event": "call_end",
            "call_id": call_id,
            "ts_end": time.time(),
            "duration_ms": round((time.time() - ts_start) * 1000),
            "prompt_tokens": prompt_eval_count,
            "completion_tokens": eval_count,
            "tokens_per_sec": tokens_per_sec,
            "load_duration_ms": round(load_duration_ns / 1e6),
            "response": ollama_data.get("message", {}),
        })

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

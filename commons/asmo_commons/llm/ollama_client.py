"""Async Ollama client with retry, timeout, and tool-calling support."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import aiohttp
import structlog

logger = structlog.get_logger()


class OllamaError(Exception):
    """Raised when Ollama returns an error or is unreachable."""


class OllamaClient:
    """Async client for the Ollama /api/chat endpoint.

    Supports:
    - Plain chat (text only)
    - Chat with tool calling (function calling)
    - Exponential-backoff retry on connection errors
    - Configurable per-request timeout
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "mistral:7b",
        timeout: int = 120,
        max_retries: int = 3,
        retry_min_wait: float = 1.0,
        retry_max_wait: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_retries = max_retries
        self._retry_min_wait = retry_min_wait
        self._retry_max_wait = retry_max_wait
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal HTTP helper with retry
    # ------------------------------------------------------------------

    async def _post_chat(self, payload: dict) -> dict:
        """POST to /api/chat with exponential-backoff retry."""
        session = await self._get_session()

        for attempt in range(self._max_retries):
            try:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise OllamaError(f"HTTP {resp.status}: {body[:300]}")
                    return await resp.json()

            except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError) as exc:
                if attempt >= self._max_retries - 1:
                    raise OllamaError(
                        f"Connection failed after {self._max_retries} attempts: {exc}"
                    ) from exc

                wait = min(
                    self._retry_min_wait * (2**attempt),
                    self._retry_max_wait,
                )
                logger.warning(
                    "ollama_retry",
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    wait_s=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)

        raise OllamaError("Unreachable")  # should never reach here

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send a conversation to Ollama and return the assistant text.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            system_prompt: Optional system message prepended to messages.

        Returns:
            Assistant reply as a plain string.
        """
        full_messages = _prepend_system(messages, system_prompt)
        payload = {"model": self.model, "messages": full_messages, "stream": False}

        logger.debug("ollama_chat", model=self.model, msg_count=len(full_messages))
        data = await self._post_chat(payload)
        return data["message"]["content"]

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: Optional[str] = None,
    ) -> dict:
        """Send a conversation with tool definitions to Ollama.

        Returns the raw ``message`` dict from Ollama, which may contain:
        - ``content`` (str): text reply
        - ``tool_calls`` (list): list of tool call requests

        The caller is responsible for executing tool calls and looping back.
        """
        full_messages = _prepend_system(messages, system_prompt)
        payload = {
            "model": self.model,
            "messages": full_messages,
            "tools": tools,
            "stream": False,
        }

        logger.debug(
            "ollama_chat_with_tools",
            model=self.model,
            msg_count=len(full_messages),
            tool_count=len(tools),
        )
        data = await self._post_chat(payload)
        return data["message"]

    async def embed(self, text: str, model: str) -> list[float]:
        """Return an embedding vector for the given text via /api/embed."""
        session = await self._get_session()
        try:
            async with session.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": text},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise OllamaError(f"Embed HTTP {resp.status}: {body[:200]}")
                data = await resp.json()
            embeddings = data.get("embeddings")
            if not embeddings or not embeddings[0]:
                raise OllamaError("Empty embedding response from Ollama")
            return embeddings[0]
        except aiohttp.ClientError as exc:
            raise OllamaError(f"Embed connection error: {exc}") from exc

    async def health_check(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/tags") as resp:
                return resp.status == 200
        except Exception:
            return False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _prepend_system(messages: list[dict], system_prompt: Optional[str]) -> list[dict]:
    if not system_prompt:
        return messages
    return [{"role": "system", "content": system_prompt}] + messages


def parse_tool_arguments(tool_call: dict) -> dict:
    """Parse tool call arguments, handling both dict and JSON-string formats."""
    args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}

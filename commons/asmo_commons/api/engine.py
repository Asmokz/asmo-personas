"""APIEngine — Discord-free LLM + tool-calling loop.

Mirrors the logic of BaseBot._process_with_llm() but:
- Receives (conv_id, history, user_content, images?) instead of discord.Message
- Yields JSON event dicts instead of sending to Discord
- History management is delegated to the caller (FastAPI layer)
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import structlog

from asmo_commons.llm.ollama_client import OllamaClient, parse_tool_arguments
from asmo_commons.tools.registry import ToolRegistry

logger = structlog.get_logger()

MAX_TOOL_ITERATIONS = 5
# Cap tool calls per single LLM response — prevents runaway parallel call generation
MAX_TOOL_CALLS_PER_TURN = 5

# Event type constants
EVT_TOKEN = "token"
EVT_TOOL_START = "tool_start"
EVT_TOOL_DONE = "tool_done"
EVT_DONE = "done"
EVT_ERROR = "error"


class APIEngine(ABC):
    """Abstract LLM processing engine — no Discord dependency.

    Subclasses must implement:
    - ``get_system_prompt()`` → str
    - ``get_registry()`` → ToolRegistry

    Optional hooks (same pattern as BaseBot):
    - ``_get_context_prefix(conv_id, content)`` → str
    - ``_on_final_response(conv_id, reply)`` → None
    - ``_on_exchange_complete(conv_id, history, meta)`` → None
    """

    def __init__(self, ollama: OllamaClient) -> None:
        self.ollama = ollama

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt defining this persona."""

    @abstractmethod
    def get_registry(self) -> ToolRegistry:
        """Return the ToolRegistry with all tools available to this persona."""

    # ------------------------------------------------------------------
    # Optional hooks — override in subclasses
    # ------------------------------------------------------------------

    async def _get_context_prefix(self, conv_id: str, content: str) -> str:
        """Return extra context to prepend to the user message (e.g. RAG memories)."""
        return ""

    async def _on_final_response(self, conv_id: str, reply: str) -> None:
        """Called once the final text reply is ready. Override to persist LTM."""

    async def _on_exchange_complete(
        self,
        conv_id: str,
        history: list[dict],
        meta: dict,
    ) -> None:
        """Called after a successful exchange. Override for training logging."""

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    async def process(
        self,
        conv_id: str,
        history: list[dict],
        user_content: str,
        images: list[str] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Run the LLM + tool-calling loop and yield JSON events.

        Event shapes:
            {"type": "token",      "content": "..."}
            {"type": "tool_start", "name": "...", "args": {...}}
            {"type": "tool_done",  "name": "...", "result": "..."}
            {"type": "done",       "entry_id": "..."}
            {"type": "error",      "message": "..."}

        history is mutated in-place — caller should persist it afterwards.
        """
        return self._run(conv_id, history, user_content, images)

    async def _run(
        self,
        conv_id: str,
        history: list[dict],
        user_content: str,
        images: list[str] | None,
    ) -> AsyncGenerator[dict, None]:
        registry = self.get_registry()
        system_prompt = self.get_system_prompt()
        tools = registry.to_ollama_tools()

        # Inject LTM / context prefix
        context_prefix = await self._get_context_prefix(conv_id, user_content)
        content = f"{context_prefix}\n{user_content}" if context_prefix else user_content

        # Build user message (with optional images)
        user_msg: dict = {"role": "user", "content": content}
        if images:
            user_msg["images"] = images

        history.append(user_msg)

        structlog.contextvars.bind_contextvars(conv_id=conv_id)
        t0 = time.monotonic()
        total_tool_calls = 0
        nudge_injected = False
        tools_called_names: list[str] = []
        entry_id: str = conv_id  # will be overwritten on success

        try:
            for iteration in range(MAX_TOOL_ITERATIONS):
                turn_t0 = time.monotonic()
                try:
                    response_msg = await self.ollama.chat_with_tools(
                        messages=list(history),
                        tools=tools,
                        system_prompt=system_prompt,
                        conv_id=conv_id,
                    )
                except Exception as exc:
                    err_msg = str(exc) or repr(exc) or type(exc).__name__
                    logger.error("ollama_error", error=err_msg)
                    yield {"type": EVT_ERROR, "message": err_msg}
                    return

                llm_ms = round((time.monotonic() - turn_t0) * 1000)

                tool_calls = response_msg.get("tool_calls")
                if not tool_calls:
                    tool_calls = _extract_tool_calls_from_content(
                        response_msg.get("content") or ""
                    )
                    if tool_calls:
                        response_msg["content"] = ""

                tool_names = (
                    [tc.get("function", {}).get("name") for tc in tool_calls]
                    if tool_calls else []
                )
                logger.info(
                    "llm_turn",
                    turn=iteration + 1,
                    tools=tool_names,
                    llm_ms=llm_ms,
                )

                # ── No tool calls → final text response ──────────────────
                if not tool_calls:
                    reply_text = (response_msg.get("content") or "").strip()

                    if reply_text:
                        history.append({"role": "assistant", "content": reply_text})

                        # Yield tokens (single chunk for non-streaming path)
                        yield {"type": EVT_TOKEN, "content": reply_text}

                        total_ms = round((time.monotonic() - t0) * 1000)
                        import uuid
                        entry_id = str(uuid.uuid4())

                        await self._on_final_response(conv_id, reply_text)

                        meta = {
                            "model": self.ollama.model,
                            "conv_id": conv_id,
                            "entry_id": entry_id,
                            "turns": iteration + 1,
                            "total_ms": total_ms,
                            "tools_called": tools_called_names,
                            "reply_len": len(reply_text),
                        }
                        await self._on_exchange_complete(conv_id, list(history), meta)

                        logger.info(
                            "llm_done",
                            total_ms=total_ms,
                            turns=iteration + 1,
                            tool_calls=total_tool_calls,
                            reply_len=len(reply_text),
                        )
                        yield {"type": EVT_DONE, "entry_id": entry_id}
                        return

                    # Empty response — retry with a nudge
                    logger.warning("empty_llm_response", turn=iteration + 1)
                    if not nudge_injected:
                        nudge_injected = True
                        history.append({
                            "role": "user",
                            "content": (
                                "Tu n'as pas répondu. Tu dois impérativement produire "
                                "une réponse textuelle, même si tu ne peux pas utiliser "
                                "d'outil. Réponds directement à ma question précédente."
                            ),
                        })
                        continue

                    yield {"type": EVT_ERROR, "message": "_(aucune réponse du LLM)_"}
                    return

                # ── Execute tool calls ────────────────────────────────────
                if len(tool_calls) > MAX_TOOL_CALLS_PER_TURN:
                    logger.warning(
                        "tool_calls_capped",
                        original=len(tool_calls),
                        capped=MAX_TOOL_CALLS_PER_TURN,
                    )
                    tool_calls = tool_calls[:MAX_TOOL_CALLS_PER_TURN]

                history.append({
                    "role": "assistant",
                    "content": response_msg.get("content", ""),
                    "tool_calls": tool_calls,
                })

                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    fn_args = parse_tool_arguments(tc)
                    tc_id = tc.get("id", f"call_{iteration}_{fn_name}")
                    total_tool_calls += 1

                    logger.info("tool_call", name=fn_name, args_keys=list(fn_args.keys()))
                    tools_called_names.append(fn_name)

                    yield {"type": EVT_TOOL_START, "name": fn_name, "args": fn_args}
                    result = await registry.execute(fn_name, fn_args)
                    yield {"type": EVT_TOOL_DONE, "name": fn_name, "result": result[:500]}

                    history.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc_id,
                    })

            # Safety: exhausted max iterations → final forced answer
            logger.warning("max_tool_iterations_reached", tool_calls=total_tool_calls)
            try:
                final = await self.ollama.chat(
                    messages=list(history),
                    system_prompt=system_prompt,
                    conv_id=conv_id,
                )
                history.append({"role": "assistant", "content": final})
                yield {"type": EVT_TOKEN, "content": final}
                import uuid
                entry_id = str(uuid.uuid4())
                yield {"type": EVT_DONE, "entry_id": entry_id}
            except Exception as exc:
                yield {"type": EVT_ERROR, "message": f"Trop d'appels d'outils imbriqués : {exc}"}

        finally:
            structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Utilities (copied from base_bot to avoid circular imports)
# ---------------------------------------------------------------------------

def _extract_tool_calls_from_content(content: str) -> list[dict]:
    """Normalise text-based tool calls into the standard tool_calls format."""
    if not content:
        return []

    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Mistral/Ministral text format: function_name[ARGS]{"key": "value"}
    m = re.match(r'^(\w+)\[ARGS\](\{.*\})\s*$', stripped, re.DOTALL)
    if m:
        try:
            arguments = json.loads(m.group(2))
            if isinstance(arguments, dict):
                return [{"function": {"name": m.group(1), "arguments": arguments}}]
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        data = json.loads(stripped.strip())
    except (json.JSONDecodeError, ValueError):
        match = re.search(r'\{[^{}]*"name"\s*:[^{}]*\}', content, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return []

    if not isinstance(data, dict):
        return []

    name = data.get("name") or data.get("function")
    if not name:
        return []

    arguments = data.get("arguments") or data.get("args") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, ValueError):
            arguments = {}

    return [{"function": {"name": name, "arguments": arguments}}]

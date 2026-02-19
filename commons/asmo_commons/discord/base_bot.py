"""Abstract base bot — LLM + tool-calling loop + conversation history."""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional

import discord
import structlog
from discord.ext import commands

from asmo_commons.llm.ollama_client import OllamaClient, parse_tool_arguments
from asmo_commons.tools.registry import ToolRegistry

logger = structlog.get_logger()

# Discord hard limit per message
DISCORD_MAX_LEN = 1990
# Maximum tool-calling iterations per user turn
MAX_TOOL_ITERATIONS = 5
# Conversation history depth per channel (messages kept)
HISTORY_MAX = 20


class BaseBot(commands.Bot, ABC):
    """Abstract Discord bot with built-in LLM + tool-calling loop.

    Subclasses must implement:
    - ``get_system_prompt()`` → str
    - ``get_registry()`` → ToolRegistry

    The bot responds to:
    - Direct mentions: ``@FEMTO ...``
    - DMs
    - Any message starting with the configured command_prefix (handled by
      discord.ext.commands framework, routed to ``@bot.command()`` handlers
      defined in the subclass).
    """

    def __init__(
        self,
        ollama: OllamaClient,
        command_prefix: str = "!",
        **kwargs,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=command_prefix, intents=intents, **kwargs)

        self.ollama = ollama
        # channel_id → deque of message dicts
        self._history: dict[int, deque[dict]] = {}

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt defining this bot's persona."""

    @abstractmethod
    def get_registry(self) -> ToolRegistry:
        """Return the ToolRegistry with all tools available to this bot."""

    # ------------------------------------------------------------------
    # Discord lifecycle hooks
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info(
            "bot_ready",
            user=str(self.user),
            guilds=[g.name for g in self.guilds],
        )
        try:
            synced = await self.tree.sync()
            logger.info("slash_commands_synced", count=len(synced))
        except Exception as exc:
            logger.warning("slash_sync_failed", error=str(exc))

    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages and other bots
        if message.author.bot:
            return

        # Let discord.ext.commands handle prefix commands first
        await self.process_commands(message)

        # If it's a prefix command, don't also run the LLM path
        if message.content.startswith(self.command_prefix):
            return

        # Respond via LLM only when mentioned or in DM
        if self._is_addressed_to_me(message):
            async with message.channel.typing():
                await self._process_with_llm(message)

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        return self.user is not None and (
            self.user in message.mentions
            or isinstance(message.channel, discord.DMChannel)
        )

    # ------------------------------------------------------------------
    # LLM + tool-calling loop
    # ------------------------------------------------------------------

    async def _process_with_llm(self, message: discord.Message) -> None:
        """Main LLM processing loop with tool execution."""
        channel_id = message.channel.id
        history = self._get_history(channel_id)
        registry = self.get_registry()
        system_prompt = self.get_system_prompt()
        tools = registry.to_ollama_tools()

        # Strip bot mention from message content
        content = message.clean_content.strip()
        history.append({"role": "user", "content": content})

        logger.info(
            "llm_request",
            channel=channel_id,
            user=str(message.author),
            history_len=len(history),
        )

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response_msg = await self.ollama.chat_with_tools(
                    messages=list(history),
                    tools=tools,
                    system_prompt=system_prompt,
                )
            except Exception as exc:
                logger.error("ollama_error", error=str(exc))
                await message.channel.send(
                    f"⚠️ Erreur de communication avec le LLM : `{exc}`"
                )
                return

            tool_calls = response_msg.get("tool_calls")

            # No tool calls → final text response
            if not tool_calls:
                reply_text = response_msg.get("content", "").strip()
                if reply_text:
                    history.append({"role": "assistant", "content": reply_text})
                    await send_long_message(message.channel, reply_text)
                else:
                    logger.warning("empty_llm_response", iteration=iteration)
                    await message.channel.send("_(aucune réponse du LLM)_")
                return

            # Execute tool calls
            history.append(
                {
                    "role": "assistant",
                    "content": response_msg.get("content", ""),
                    "tool_calls": tool_calls,
                }
            )

            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name", "unknown")
                fn_args = parse_tool_arguments(tc)
                tc_id = tc.get("id", f"call_{iteration}_{fn_name}")

                logger.info("tool_call", name=fn_name, args=fn_args)
                result = await registry.execute(fn_name, fn_args)

                history.append(
                    {
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc_id,
                    }
                )

        # Safety: if we exhausted iterations, ask LLM for a final answer
        logger.warning("max_tool_iterations_reached", channel=channel_id)
        try:
            final = await self.ollama.chat(
                messages=list(history),
                system_prompt=system_prompt,
            )
            await send_long_message(message.channel, final)
            history.append({"role": "assistant", "content": final})
        except Exception as exc:
            await message.channel.send(
                f"⚠️ Trop d'appels d'outils imbriqués : `{exc}`"
            )

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _get_history(self, channel_id: int) -> deque[dict]:
        if channel_id not in self._history:
            self._history[channel_id] = deque(maxlen=HISTORY_MAX)
        return self._history[channel_id]

    def clear_history(self, channel_id: Optional[int] = None) -> None:
        """Clear conversation history for one channel, or all channels."""
        if channel_id is not None:
            self._history.pop(channel_id, None)
        else:
            self._history.clear()

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return  # ignore unknown ! commands
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Argument manquant : `{error.param.name}`")
            return
        logger.error("command_error", command=ctx.command, error=str(error))
        await ctx.send(f"⚠️ Erreur : `{error}`")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

async def send_long_message(
    channel: discord.abc.Messageable,
    text: str,
    code_block: bool = False,
) -> None:
    """Send *text* to *channel*, splitting at DISCORD_MAX_LEN if needed."""
    prefix = "```\n" if code_block else ""
    suffix = "\n```" if code_block else ""
    effective_max = DISCORD_MAX_LEN - len(prefix) - len(suffix)

    if len(text) <= effective_max:
        await channel.send(f"{prefix}{text}{suffix}")
        return

    # Split on newlines when possible
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > effective_max:
            if current:
                chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)

    for chunk in chunks:
        await channel.send(f"{prefix}{chunk.rstrip()}{suffix}")
        await asyncio.sleep(0.3)  # respect Discord rate limits

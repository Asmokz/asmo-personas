"""FEMTO Discord bot — monitoring persona."""
from __future__ import annotations

import discord
from discord.ext import commands

import structlog

from asmo_commons.config.settings import FemtoSettings
from asmo_commons.discord.base_bot import BaseBot, send_long_message
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.executor import CommandExecutor
from asmo_commons.tools.registry import ToolDefinition, ToolRegistry

from .persona import SYSTEM_PROMPT
from .scheduler import FemtoScheduler
from .tools.system_metrics import SystemMetrics
from .tools.docker_status import DockerStatus
from .tools.network_monitor import NetworkMonitor
from .tools.log_analyzer import LogAnalyzer

logger = structlog.get_logger()


class FemtoBot(BaseBot):
    """FEMTO — ASMO-01 monitoring bot."""

    def __init__(self, settings: FemtoSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.asmo_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            ),
            command_prefix="!",
        )
        self.settings = settings

        # Tool infrastructure
        self._executor = CommandExecutor(default_timeout=settings.femto_cmd_timeout)
        self.system_metrics = SystemMetrics(self._executor)
        self.docker_status = DockerStatus(
            self._executor, max_log_lines=settings.femto_max_log_lines
        )
        self.network_monitor = NetworkMonitor(self._executor)
        self.log_analyzer = LogAnalyzer(self._executor, self.ollama)

        # Build registry
        self._registry = ToolRegistry()
        self._register_tools()

        # Scheduler (started in setup_hook when event loop is running)
        self._scheduler = FemtoScheduler(self)

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register(
            "get_disk_usage",
            "Retourne l'utilisation du disque (df -h). Appelle cet outil pour toute question sur l'espace disque.",
        )
        async def get_disk_usage() -> str:
            return await self.system_metrics.get_disk_usage()

        @reg.register(
            "get_memory_usage",
            "Retourne l'utilisation de la RAM et du swap (free -h).",
        )
        async def get_memory_usage() -> str:
            return await self.system_metrics.get_memory_usage()

        @reg.register(
            "get_cpu_usage",
            "Retourne l'utilisation CPU actuelle via mpstat.",
        )
        async def get_cpu_usage() -> str:
            return await self.system_metrics.get_cpu_usage()

        @reg.register(
            "get_system_uptime",
            "Retourne l'uptime et la charge système.",
        )
        async def get_system_uptime() -> str:
            return await self.system_metrics.get_system_uptime()

        @reg.register(
            "get_docker_status",
            "Retourne la liste des conteneurs Docker en cours d'exécution avec leur statut.",
        )
        async def get_docker_status() -> str:
            return await self.docker_status.get_docker_status()

        @reg.register(
            "get_all_containers",
            "Retourne tous les conteneurs Docker, y compris ceux qui sont arrêtés.",
        )
        async def get_all_containers() -> str:
            return await self.docker_status.get_all_containers()

        @reg.register(
            "get_container_logs",
            "Retourne les dernières lignes de logs d'un conteneur Docker.",
            parameters={
                "type": "object",
                "properties": {
                    "container": {
                        "type": "string",
                        "description": "Nom ou ID du conteneur Docker",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Nombre de lignes à retourner (défaut : 50)",
                        "default": 50,
                    },
                },
                "required": ["container"],
            },
        )
        async def get_container_logs(container: str, lines: int = 50) -> str:
            return await self.docker_status.get_container_logs(container, lines)

        @reg.register(
            "get_container_stats",
            "Retourne l'utilisation CPU/RAM/réseau de tous les conteneurs en cours.",
        )
        async def get_container_stats() -> str:
            return await self.docker_status.get_container_stats()

        @reg.register(
            "get_network_stats",
            "Retourne les statistiques réseau (TX/RX par interface).",
        )
        async def get_network_stats() -> str:
            return await self.network_monitor.get_network_stats()

        @reg.register(
            "analyze_logs",
            "Analyse intelligente des logs d'un conteneur via le LLM. Synthétise les erreurs et anomalies.",
            parameters={
                "type": "object",
                "properties": {
                    "container": {
                        "type": "string",
                        "description": "Nom ou ID du conteneur Docker",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "Nombre d'heures à analyser (défaut : 24)",
                        "default": 24,
                    },
                },
                "required": ["container"],
            },
        )
        async def analyze_logs(container: str, hours: int = 24) -> str:
            return await self.log_analyzer.analyze_logs(container, hours)

    # ------------------------------------------------------------------
    # Discord lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called by discord.py before the bot connects."""
        self._register_prefix_commands()
        self._scheduler.start()
        await super().setup_hook()

    async def close(self) -> None:
        self._scheduler.stop()
        await self.ollama.close()
        await super().close()

    # ------------------------------------------------------------------
    # Prefix commands
    # ------------------------------------------------------------------

    def _register_prefix_commands(self) -> None:
        """Register !status and !logs as fast prefix commands (no LLM needed)."""

        @self.command(name="status", help="Résumé rapide du système")
        async def cmd_status(ctx: commands.Context) -> None:
            async with ctx.typing():
                metrics = await self.system_metrics.get_all_metrics()
                docker = await self.docker_status.get_docker_status()

                reply = (
                    "⚙️ **Status ASMO-01**\n\n"
                    f"**Uptime** : `{metrics['uptime']}`\n\n"
                    f"**Mémoire** :\n```\n{metrics['memory']}\n```\n"
                    f"**Disque** :\n```\n{metrics['disk']}\n```\n"
                    f"**Conteneurs** :\n```\n{docker}\n```"
                )
                await send_long_message(ctx.channel, reply)

        @self.command(name="logs", help="Derniers logs d'un conteneur")
        async def cmd_logs(ctx: commands.Context, container: str, lines: int = 50) -> None:
            async with ctx.typing():
                try:
                    logs = await self.docker_status.get_container_logs(container, lines)
                    await send_long_message(ctx.channel, logs, code_block=True)
                except Exception as exc:
                    await ctx.send(f"❌ Erreur : `{exc}`")

        @self.command(name="analyze", help="Analyse LLM des logs d'un conteneur")
        async def cmd_analyze(
            ctx: commands.Context, container: str, hours: int = 24
        ) -> None:
            async with ctx.typing():
                result = await self.log_analyzer.analyze_logs(container, hours)
                await send_long_message(ctx.channel, result)

        @self.command(name="containers", help="Tous les conteneurs (running + stopped)")
        async def cmd_containers(ctx: commands.Context) -> None:
            async with ctx.typing():
                result = await self.docker_status.get_all_containers()
                await send_long_message(ctx.channel, result, code_block=True)

        @self.command(name="stats", help="Utilisation ressources des conteneurs")
        async def cmd_stats(ctx: commands.Context) -> None:
            async with ctx.typing():
                result = await self.docker_status.get_container_stats()
                await send_long_message(ctx.channel, result, code_block=True)

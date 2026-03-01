"""FEMTO Discord bot — monitoring persona."""
from __future__ import annotations

import discord
from discord.ext import commands

import structlog

from asmo_commons.config.settings import FemtoSettings
from asmo_commons.discord.base_bot import BaseBot, send_long_message
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.pubsub.redis_client import RedisPubSub
from asmo_commons.tools.executor import CommandExecutor
from asmo_commons.tools.registry import ToolDefinition, ToolRegistry

from .persona import get_system_prompt
from .scheduler import FemtoScheduler
from .tools.system_metrics import SystemMetrics
from .tools.docker_status import DockerStatus
from .tools.network_monitor import NetworkMonitor
from .tools.log_analyzer import LogAnalyzer
from .tools.disk_health import DiskHealth

logger = structlog.get_logger()


class FemtoBot(BaseBot):
    """FEMTO — ASMO-01 monitoring bot."""

    def __init__(self, settings: FemtoSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.femto_ollama_model,
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
            max_log_lines=settings.femto_max_log_lines
        )
        self.network_monitor = NetworkMonitor(self._executor)
        self.log_analyzer = LogAnalyzer(self._executor, self.ollama)
        self.disk_health = DiskHealth(self._executor, settings.femto_nas_device, settings.femto_nas_smart_type)

        # Build registry
        self._registry = ToolRegistry()
        self._register_tools()

        # Pub/Sub (optional — graceful if Redis unavailable)
        self.pubsub = RedisPubSub(settings.asmo_redis_url)

        # Scheduler (started in setup_hook when event loop is running)
        self._scheduler = FemtoScheduler(self)

    # ------------------------------------------------------------------
    # BaseBot interface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return get_system_prompt()

    def get_registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Respond on dedicated channel without requiring a mention
    # ------------------------------------------------------------------

    def _is_addressed_to_me(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        if isinstance(message.channel, discord.DMChannel) or self.user in message.mentions:
            return True
        channel_id = self.settings.femto_chat_channel_id
        if channel_id and message.channel.id == channel_id:
            return True
        return False

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register(
            "get_disk_usage",
            "Retourne l'utilisation de tous les disques (df -h). Appelle cet outil pour toute question sur l'espace disque.",
        )
        async def get_disk_usage() -> str:
            return await self.system_metrics.get_disk_usage()

        @reg.register(
            "get_nas_usage",
            "Retourne l'espace utilisé/disponible sur le NAS monté en /mnt/nas.",
        )
        async def get_nas_usage() -> str:
            return await self.system_metrics.get_nas_usage()

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
            "Retourne les logs d'un conteneur Docker. "
            "Pour diagnostiquer un problème à une heure précise (ex: 'hier à 21h'), "
            "utilise since et/ou until au format ISO 8601 en te basant sur la date actuelle. "
            "Sans since/until, retourne les N dernières lignes.",
            parameters={
                "type": "object",
                "properties": {
                    "container": {
                        "type": "string",
                        "description": "Nom ou ID du conteneur Docker",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Nombre de lignes max (défaut 50, ou 300 si since/until fournis)",
                        "default": 50,
                    },
                    "since": {
                        "type": "string",
                        "description": "Début de la fenêtre temporelle, format ISO 8601 (ex: '2026-02-21T21:00:00')",
                    },
                    "until": {
                        "type": "string",
                        "description": "Fin de la fenêtre temporelle, format ISO 8601 (ex: '2026-02-21T22:00:00')",
                    },
                },
                "required": ["container"],
            },
        )
        async def get_container_logs(
            container: str, lines: int = 50, since: str = None, until: str = None
        ) -> str:
            return await self.docker_status.get_container_logs(container, lines, since, until)

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

        @reg.register(
            "get_disk_health",
            "Retourne le statut SMART du disque NAS (/dev/sda) : santé globale, secteurs "
            "réalloués, secteurs en attente, température. Appelle cet outil pour diagnostiquer "
            "l'état physique du disque NAS ou répondre à des questions sur sa fiabilité.",
            parameters={
                "type": "object",
                "properties": {
                    "full": {
                        "type": "boolean",
                        "description": "True pour le rapport SMART complet, False pour juste le statut de santé (défaut)",
                        "default": False,
                    },
                },
                "required": [],
            },
        )
        async def get_disk_health(full: bool = False) -> str:
            if full:
                return await self.disk_health.get_full_report()
            return await self.disk_health.get_attributes()

    # ------------------------------------------------------------------
    # Discord lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called by discord.py before the bot connects."""
        self._register_prefix_commands()
        self._scheduler.start()
        try:
            await self.pubsub.connect()
            logger.info("femto_pubsub_connected")
        except Exception as exc:
            logger.warning("femto_pubsub_unavailable", error=str(exc))
        await super().setup_hook()

    async def close(self) -> None:
        self._scheduler.stop()
        try:
            await self.pubsub.disconnect()
        except Exception:
            pass
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

"""FemtoPersona — FEMTO monitoring assistant in Olympus context."""
from __future__ import annotations

import structlog

from asmo_commons.config.settings import FemtoSettings
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.executor import CommandExecutor
from asmo_commons.tools.registry import ToolRegistry

from femto.src.persona import get_system_prompt
from femto.src.tools.system_metrics import SystemMetrics
from femto.src.tools.docker_status import DockerStatus
from femto.src.tools.network_monitor import NetworkMonitor
from femto.src.tools.log_analyzer import LogAnalyzer
from femto.src.tools.disk_health import DiskHealth
from femto.src.tools.gpu_metrics import GpuMetrics

from .base import OlympusPersona

logger = structlog.get_logger()


class FemtoPersona(OlympusPersona):
    """FEMTO monitoring persona — Olympus version."""

    PERSONA_ID = "femto"
    PERSONA_NAME = "FEMTO"
    PERSONA_DESCRIPTION = "Monitoring homelab — système, Docker, réseau, disques"
    PERSONA_COLOR = "#00B4D8"

    def __init__(self, settings: FemtoSettings) -> None:
        super().__init__(
            ollama=OllamaClient(
                base_url=settings.asmo_ollama_base_url,
                model=settings.femto_ollama_model,
                timeout=settings.asmo_ollama_timeout,
                max_retries=settings.asmo_ollama_max_retries,
                retry_min_wait=settings.asmo_ollama_retry_min_wait,
                retry_max_wait=settings.asmo_ollama_retry_max_wait,
            )
        )
        self.settings = settings
        self._executor = CommandExecutor(default_timeout=settings.femto_cmd_timeout)
        self.system_metrics = SystemMetrics(self._executor)
        self.docker_status = DockerStatus(max_log_lines=settings.femto_max_log_lines)
        self.network_monitor = NetworkMonitor(self._executor)
        self.log_analyzer = LogAnalyzer(self._executor, self.ollama)
        self.disk_health = DiskHealth(
            self._executor, settings.femto_nas_device, settings.femto_nas_smart_type
        )
        self.gpu_metrics = GpuMetrics(self._executor)

        self._registry = ToolRegistry()
        self._register_tools()

    def get_system_prompt(self) -> str:
        return get_system_prompt()

    def get_registry(self) -> ToolRegistry:
        return self._registry

    def _register_tools(self) -> None:
        reg = self._registry

        @reg.register(
            "get_gpu_stats",
            "Retourne les statistiques GPU NVIDIA en temps réel : utilisation, température, "
            "VRAM utilisée/totale, puissance consommée, horloge, ventilateur. "
            "Appelle cet outil pour TOUTE question sur le GPU, la carte graphique, la VRAM, "
            "la température GPU ou l'utilisation GPU.",
        )
        async def get_gpu_stats() -> str:
            return await self.gpu_metrics.get_gpu_stats()

        @reg.register(
            "get_disk_usage",
            "Retourne l'utilisation de tous les disques (df -h).",
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
            "Retourne l'utilisation de la RAM et du swap.",
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
            "Retourne la liste des conteneurs Docker en cours d'exécution.",
        )
        async def get_docker_status() -> str:
            return await self.docker_status.get_docker_status()

        @reg.register(
            "get_all_containers",
            "Retourne tous les conteneurs Docker, y compris les arrêtés.",
        )
        async def get_all_containers() -> str:
            return await self.docker_status.get_all_containers()

        @reg.register(
            "get_container_logs",
            "Retourne les logs d'un conteneur Docker.",
            parameters={
                "type": "object",
                "properties": {
                    "container": {"type": "string"},
                    "lines": {"type": "integer", "default": 50},
                    "since": {"type": "string"},
                    "until": {"type": "string"},
                },
                "required": ["container"],
            },
        )
        async def get_container_logs(container: str, lines: int = 50, since: str = None, until: str = None) -> str:
            return await self.docker_status.get_container_logs(container, lines, since, until)

        @reg.register(
            "get_container_stats",
            "Retourne l'utilisation CPU/RAM/réseau de tous les conteneurs.",
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
            "Analyse intelligente des logs d'un conteneur via le LLM.",
            parameters={
                "type": "object",
                "properties": {
                    "container": {"type": "string"},
                    "hours": {"type": "integer", "default": 24},
                },
                "required": ["container"],
            },
        )
        async def analyze_logs(container: str, hours: int = 24) -> str:
            return await self.log_analyzer.analyze_logs(container, hours)

        @reg.register(
            "get_disk_health",
            "Retourne le statut SMART du disque NAS.",
            parameters={
                "type": "object",
                "properties": {
                    "full": {"type": "boolean", "default": False},
                },
                "required": [],
            },
        )
        async def get_disk_health(full: bool = False) -> str:
            if full:
                return await self.disk_health.get_full_report()
            return await self.disk_health.get_attributes()

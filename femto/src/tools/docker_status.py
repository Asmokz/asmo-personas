"""Docker monitoring tools — container status, logs, stats."""
from __future__ import annotations

import structlog
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()


class DockerStatus:
    """Read-only Docker inspection via the Docker CLI (socket mount)."""

    def __init__(self, executor: CommandExecutor, max_log_lines: int = 50) -> None:
        self._exec = executor
        self._max_log_lines = max_log_lines

    async def get_docker_status(self) -> str:
        """Return all running containers with their status (docker ps)."""
        return await self._exec.run(
            [
                "docker",
                "ps",
                "--format",
                "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
            ]
        )

    async def get_all_containers(self) -> str:
        """Return all containers including stopped ones."""
        return await self._exec.run(
            [
                "docker",
                "ps",
                "-a",
                "--format",
                "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.RunningFor}}",
            ]
        )

    async def get_container_logs(
        self, container: str, lines: int | None = None
    ) -> str:
        """Return the last *lines* log lines for *container*."""
        n = str(lines or self._max_log_lines)
        return await self._exec.run(
            ["docker", "logs", "--tail", n, "--timestamps", container],
            timeout=15,
        )

    async def get_container_stats(self) -> str:
        """Return resource usage snapshot for all running containers."""
        return await self._exec.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}",
            ],
            timeout=20,
        )

    async def inspect_container(self, container: str) -> str:
        """Return docker inspect output for *container*."""
        return await self._exec.run(["docker", "inspect", container], timeout=10)

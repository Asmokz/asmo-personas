"""System metrics tools — disk, memory, CPU, uptime."""
from __future__ import annotations

import structlog
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()


class SystemMetrics:
    """Read-only system metrics via whitelisted commands."""

    def __init__(self, executor: CommandExecutor) -> None:
        self._exec = executor

    async def get_disk_usage(self) -> str:
        """Return formatted disk usage (df -h)."""
        return await self._exec.run(["df", "-h", "--output=source,size,used,avail,pcent,target"])

    async def get_nas_usage(self) -> str:
        """Return disk usage for the NAS mount at /mnt/nas."""
        try:
            return await self._exec.run(["df", "-h", "/mnt/nas"])
        except Exception as exc:
            return f"NAS indisponible : {exc}"

    async def get_memory_usage(self) -> str:
        """Return formatted memory usage (free -h)."""
        return await self._exec.run(["free", "-h"])

    async def get_cpu_usage(self) -> str:
        """Return CPU usage from mpstat (1 sample, 1 second interval)."""
        try:
            return await self._exec.run(["mpstat", "1", "1"])
        except Exception:
            # Fallback: read /proc/loadavg
            try:
                loadavg = await self._exec.run(["cat", "/proc/loadavg"])
                return f"Load average: {loadavg}"
            except Exception as exc:
                return f"CPU info unavailable: {exc}"

    async def get_system_uptime(self) -> str:
        """Return system uptime."""
        return await self._exec.run(["uptime"])

    async def get_all_metrics(self) -> dict[str, str]:
        """Collect all metrics at once. Returns dict keyed by metric name."""
        import asyncio

        disk, mem, cpu, uptime, nas = await asyncio.gather(
            self.get_disk_usage(),
            self.get_memory_usage(),
            self.get_cpu_usage(),
            self.get_system_uptime(),
            self.get_nas_usage(),
            return_exceptions=True,
        )
        return {
            "disk": str(disk),
            "memory": str(mem),
            "cpu": str(cpu),
            "uptime": str(uptime),
            "nas": str(nas),
        }

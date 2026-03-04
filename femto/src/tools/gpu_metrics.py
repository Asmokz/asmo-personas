"""GPU metrics tool — nvidia-smi based monitoring."""
from __future__ import annotations

import structlog
from asmo_commons.tools.executor import CommandExecutor, ExecutorError

logger = structlog.get_logger()

_QUERY_FIELDS = (
    "name,"
    "temperature.gpu,"
    "utilization.gpu,"
    "utilization.memory,"
    "memory.used,"
    "memory.total,"
    "power.draw,"
    "power.limit,"
    "clocks.gr,"
    "fan.speed"
)


class GpuMetrics:
    """Read GPU stats via nvidia-smi."""

    def __init__(self, executor: CommandExecutor) -> None:
        self._exec = executor

    async def get_gpu_stats(self) -> str:
        """Return formatted GPU stats (utilization, temperature, memory, power)."""
        try:
            raw = await self._exec.run([
                "nvidia-smi",
                f"--query-gpu={_QUERY_FIELDS}",
                "--format=csv,noheader",
            ])
        except ExecutorError as exc:
            # nvidia-smi not available or no GPU
            return f"⚠️ GPU non disponible : {exc}"
        except Exception as exc:
            logger.error("gpu_metrics_error", error=str(exc))
            return f"❌ Erreur GPU : {exc}"

        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if not lines:
            return "⚠️ Aucun GPU détecté par nvidia-smi."

        results = []
        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 10:
                results.append(f"GPU {i}: données incomplètes — {line}")
                continue

            name, temp, util_gpu, util_mem, mem_used, mem_total, power, power_limit, clock, fan = parts[:10]

            # Strip units that nvidia-smi appends (e.g. " %", " MiB", " W", " MHz")
            def strip_unit(s: str) -> str:
                return s.split()[0] if s and s != "[N/A]" else "N/A"

            results.append(
                f"🎮 **{name}** (GPU {i})\n"
                f"  Température : {strip_unit(temp)}°C\n"
                f"  Utilisation GPU : {strip_unit(util_gpu)}%\n"
                f"  Utilisation mémoire : {strip_unit(util_mem)}%\n"
                f"  Mémoire : {strip_unit(mem_used)} / {strip_unit(mem_total)} MiB\n"
                f"  Puissance : {strip_unit(power)} W / {strip_unit(power_limit)} W\n"
                f"  Horloge GPU : {strip_unit(clock)} MHz\n"
                f"  Ventilateur : {strip_unit(fan)}%"
            )

        return "\n\n".join(results)

"""Hardware sampler — psutil (swap) + pynvml (GPU). Synchronous, < 1ms."""
from __future__ import annotations

import psutil
import structlog

logger = structlog.get_logger()


class HardwareSampler:
    """Samples swap and GPU metrics. Gracefully skips GPU if pynvml unavailable."""

    def __init__(self) -> None:
        self._nvml_ok = False
        self._handle = None
        self._pynvml = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self._handle)
            self._pynvml = pynvml
            self._nvml_ok = True
            logger.info("gpu_sampler_ready", gpu=name)
        except Exception as exc:
            logger.warning("gpu_sampler_unavailable", reason=str(exc))

    def sample(self) -> dict:
        """Return a hardware snapshot dict. Always includes swap; GPU if available."""
        swap = psutil.swap_memory()
        result: dict = {
            "swap_used_gb": round(swap.used / 1024**3, 2),
            "swap_pct": round(swap.percent, 1),
        }
        if self._nvml_ok and self._handle is not None:
            try:
                util = self._pynvml.nvmlDeviceGetUtilizationRates(self._handle)
                mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
                result.update({
                    "gpu_util_pct": util.gpu,
                    "vram_used_mb": round(mem.used / 1024**2),
                    "vram_total_mb": round(mem.total / 1024**2),
                })
            except Exception as exc:
                logger.debug("gpu_sample_error", error=str(exc))
        return result

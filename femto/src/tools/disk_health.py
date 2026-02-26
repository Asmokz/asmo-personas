"""Disk health monitoring via smartmontools (smartctl).

Only read-only SMART queries are executed:
  - smartctl -H  → overall health assessment (PASSED / FAILED)
  - smartctl -A  → all SMART attributes (reallocated sectors, pending, temperature…)
  - smartctl -a  → combined full report (-H + -i + -A)

Disk self-tests (-t short/long) are intentionally NOT supported here:
they cause measurable disk activity and should only be run manually.

Device note: SMART operates on the whole disk, not a partition. Pass
/dev/sda even if the NAS mount point is on /dev/sda1 — the class
normalises partition suffixes automatically.
"""
from __future__ import annotations

import re

import structlog
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()

_NAS_DEVICE = "/dev/sda"


def _normalize_device(device: str) -> str:
    """Strip trailing partition digit(s): /dev/sda1 → /dev/sda."""
    return re.sub(r"\d+$", "", device.strip())


class DiskHealth:
    """Read-only SMART status queries for a disk."""

    def __init__(self, executor: CommandExecutor, device: str = _NAS_DEVICE) -> None:
        self._exec = executor
        self._device = _normalize_device(device)

    async def get_health(self) -> str:
        """Return the overall SMART health assessment (PASSED / FAILED).

        smartctl -H reads only the cached SMART pass/fail flag —
        no physical disk activity, extremely fast.
        """
        try:
            result = await self._exec.run(
                ["smartctl", "-H", self._device], timeout=10
            )
            return result
        except Exception as exc:
            return f"❌ smartctl -H indisponible sur {self._device} : {exc}"

    async def get_attributes(self) -> str:
        """Return all SMART attributes (reallocated sectors, temperature, etc.).

        smartctl -A reads the cached attribute table — no disk activity.
        """
        try:
            result = await self._exec.run(
                ["smartctl", "-A", self._device], timeout=10
            )
            return result
        except Exception as exc:
            return f"❌ smartctl -A indisponible sur {self._device} : {exc}"

    async def get_full_report(self) -> str:
        """Return the full SMART report (-H + device info + all attributes)."""
        try:
            result = await self._exec.run(
                ["smartctl", "-a", self._device], timeout=10
            )
            return result
        except Exception as exc:
            return f"❌ smartctl -a indisponible sur {self._device} : {exc}"

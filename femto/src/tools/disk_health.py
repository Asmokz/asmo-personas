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

Device type: most SATA drives require '-d sat' to be passed explicitly.
Set smart_type="auto" to let smartctl detect it (may fail on some controllers).
"""
from __future__ import annotations

import re

import structlog
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()

_NAS_DEVICE = "/dev/sda"
_DEFAULT_SMART_TYPE = "sat"


def _normalize_device(device: str) -> str:
    """Strip trailing partition digit(s): /dev/sda1 → /dev/sda."""
    return re.sub(r"\d+$", "", device.strip())


class DiskHealth:
    """Read-only SMART status queries for a disk."""

    def __init__(
        self,
        executor: CommandExecutor,
        device: str = _NAS_DEVICE,
        smart_type: str = _DEFAULT_SMART_TYPE,
    ) -> None:
        self._exec = executor
        self._device = _normalize_device(device)
        self._smart_type = smart_type

    def _cmd(self, *flags: str) -> list[str]:
        """Build a smartctl command with the configured device type flag."""
        cmd = ["smartctl"]
        if self._smart_type and self._smart_type != "auto":
            cmd += ["-d", self._smart_type]
        cmd += list(flags)
        cmd.append(self._device)
        return cmd

    async def get_health(self) -> str:
        """Return the overall SMART health assessment (PASSED / FAILED).

        smartctl -H reads only the cached SMART pass/fail flag —
        no physical disk activity, extremely fast.
        """
        try:
            return await self._exec.run(self._cmd("-H"), timeout=10)
        except Exception as exc:
            return f"❌ smartctl -H indisponible sur {self._device} : {exc}"

    async def get_attributes(self) -> str:
        """Return all SMART attributes (reallocated sectors, temperature, etc.).

        smartctl -A reads the cached attribute table — no disk activity.
        """
        try:
            return await self._exec.run(self._cmd("-A"), timeout=10)
        except Exception as exc:
            return f"❌ smartctl -A indisponible sur {self._device} : {exc}"

    async def get_full_report(self) -> str:
        """Return the full SMART report (-H + device info + all attributes)."""
        try:
            return await self._exec.run(self._cmd("-a"), timeout=10)
        except Exception as exc:
            return f"❌ smartctl -a indisponible sur {self._device} : {exc}"

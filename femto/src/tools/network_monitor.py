"""Network monitoring tools.

Note: when running inside Docker without host network namespace,
these commands report container-level stats.  For host-level stats,
add ``network_mode: host`` or mount ``/proc/net`` read-only in
docker-compose.yml.
"""
from __future__ import annotations

import structlog
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()


class NetworkMonitor:
    """Read-only network statistics."""

    def __init__(self, executor: CommandExecutor) -> None:
        self._exec = executor

    async def get_network_stats(self) -> str:
        """Return interface TX/RX counters from /proc/net/dev."""
        try:
            raw = await self._exec.run(["cat", "/proc/net/dev"])
            return _format_net_dev(raw)
        except Exception as exc:
            return f"Network stats unavailable: {exc}"

    async def get_connections(self) -> str:
        """Return active TCP/UDP connections summary."""
        try:
            return await self._exec.run(
                ["ss", "-tunp", "--summary"],
                timeout=5,
            )
        except Exception as exc:
            return f"Connection stats unavailable: {exc}"

    async def get_ip_addresses(self) -> str:
        """Return IP address information."""
        return await self._exec.run(["ip", "addr", "show"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_net_dev(raw: str) -> str:
    """Parse /proc/net/dev and return a human-readable table."""
    lines = raw.strip().splitlines()
    # Skip header lines
    data_lines = [l for l in lines[2:] if l.strip()]

    rows = ["Interface          RX bytes        TX bytes"]
    rows.append("-" * 48)
    for line in data_lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        iface = parts[0].rstrip(":")
        rx_bytes = int(parts[1])
        tx_bytes = int(parts[9])
        rows.append(
            f"{iface:<18} {_human(rx_bytes):<16} {_human(tx_bytes)}"
        )
    return "\n".join(rows)


def _human(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"

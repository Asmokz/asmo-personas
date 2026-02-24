"""Docker monitoring tools — Docker Python SDK (no CLI required).

Communicates directly with /var/run/docker.sock via the docker Python package.
All blocking SDK calls are run in a thread executor to avoid blocking the
asyncio event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog

logger = structlog.get_logger()

SOCKET_URL = "unix://var/run/docker.sock"


class DockerStatus:
    """Read-only Docker inspection via the Docker Python SDK."""

    def __init__(self, max_log_lines: int = 50) -> None:
        self._max_log_lines = max_log_lines
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            import docker
            self._client = docker.DockerClient(base_url=SOCKET_URL)
        return self._client

    async def _run(self, fn, *args, **kwargs):
        """Run a blocking Docker SDK call in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_docker_status(self) -> str:
        """Return running containers as a formatted table."""
        try:
            client = self._get_client()
            containers = await self._run(client.containers.list)
        except Exception as exc:
            return f"❌ Impossible de contacter Docker : {exc}"

        if not containers:
            return "Aucun conteneur en cours d'exécution."

        lines = [f"{'NOM':<28} {'IMAGE':<35} {'STATUT':<15} PORTS"]
        lines.append("─" * 90)
        for c in containers:
            image = c.image.tags[0] if c.image.tags else c.image.short_id
            lines.append(
                f"{c.name:<28} {image:<35} {c.status:<15} {_fmt_ports(c.ports)}"
            )
        return "\n".join(lines)

    async def get_all_containers(self) -> str:
        """Return all containers (running and stopped)."""
        try:
            client = self._get_client()
            containers = await self._run(client.containers.list, all=True)
        except Exception as exc:
            return f"❌ Impossible de contacter Docker : {exc}"

        if not containers:
            return "Aucun conteneur."

        lines = [f"{'NOM':<28} {'IMAGE':<35} {'STATUT':<20} ID"]
        lines.append("─" * 95)
        for c in containers:
            image = c.image.tags[0] if c.image.tags else c.image.short_id
            lines.append(
                f"{c.name:<28} {image:<35} {c.status:<20} {c.short_id}"
            )
        return "\n".join(lines)

    async def get_container_logs(
        self,
        container: str,
        lines: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> str:
        """Return logs for *container*, optionally filtered to a time window.

        When *since* and/or *until* are given (ISO 8601 strings such as
        "2026-02-21T21:00:00"), returns logs from that window instead of the
        last N lines. A safety cap of 300 lines still applies to avoid
        flooding Discord.
        """
        from datetime import datetime, timezone

        kwargs: dict = {"timestamps": True}

        if since or until:
            # Time-window mode — cap lines to avoid huge output
            kwargs["tail"] = min(lines or 300, 500)
            if since:
                try:
                    dt = datetime.fromisoformat(since)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    kwargs["since"] = dt
                except ValueError:
                    return f"❌ Format `since` invalide : '{since}' (attendu ISO 8601, ex: '2026-02-21T21:00:00')"
            if until:
                try:
                    dt = datetime.fromisoformat(until)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    kwargs["until"] = dt
                except ValueError:
                    return f"❌ Format `until` invalide : '{until}' (attendu ISO 8601, ex: '2026-02-21T22:00:00')"
        else:
            # Default mode — last N lines
            kwargs["tail"] = lines or self._max_log_lines

        try:
            client = self._get_client()
            c = await self._run(client.containers.get, container)
            raw: bytes = await self._run(c.logs, **kwargs)
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:
            return f"❌ Logs de `{container}` indisponibles : {exc}"

    async def get_container_stats(self) -> str:
        """Return CPU/memory/network snapshot for all running containers."""
        try:
            client = self._get_client()
            containers = await self._run(client.containers.list)
        except Exception as exc:
            return f"❌ Impossible de contacter Docker : {exc}"

        if not containers:
            return "Aucun conteneur en cours d'exécution."

        lines = [f"{'NOM':<28} {'CPU %':<10} {'MEM':<25} NET RX/TX"]
        lines.append("─" * 80)

        async def _stats_one(c) -> str:
            try:
                raw = await self._run(c.stats, stream=False)
                cpu = _calc_cpu(raw)
                mem = _fmt_mem(raw)
                net = _fmt_net(raw)
                return f"{c.name:<28} {cpu:<10} {mem:<25} {net}"
            except Exception:
                return f"{c.name:<28} (stats indisponibles)"

        rows = await asyncio.gather(*[_stats_one(c) for c in containers])
        lines.extend(rows)
        return "\n".join(lines)

    async def inspect_container(self, container: str) -> str:
        """Return selected inspect fields for *container*."""
        try:
            client = self._get_client()
            c = await self._run(client.containers.get, container)
            subset = {
                "Id": c.attrs.get("Id", "")[:12],
                "Name": c.name,
                "Status": c.status,
                "Image": c.image.tags,
                "Created": c.attrs.get("Created"),
                "RestartCount": c.attrs.get("RestartCount"),
                "Mounts": [m.get("Source") for m in c.attrs.get("Mounts", [])],
                "Ports": c.ports,
            }
            return json.dumps(subset, indent=2, default=str)
        except Exception as exc:
            return f"❌ Inspect de `{container}` indisponible : {exc}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ports(ports: dict) -> str:
    if not ports:
        return ""
    parts = []
    for container_port, bindings in ports.items():
        if bindings:
            for b in bindings:
                parts.append(f"{b['HostPort']}→{container_port}")
        else:
            parts.append(container_port)
    return ", ".join(parts[:4])


def _calc_cpu(stats: dict) -> str:
    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        sys_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        ncpus = stats["cpu_stats"].get("online_cpus", 1)
        pct = (cpu_delta / sys_delta) * ncpus * 100.0 if sys_delta else 0.0
        return f"{pct:.1f}%"
    except (KeyError, ZeroDivisionError):
        return "N/A"


def _fmt_mem(stats: dict) -> str:
    try:
        used = stats["memory_stats"]["usage"]
        limit = stats["memory_stats"]["limit"]
        pct = (used / limit) * 100 if limit else 0
        return f"{_human(used)} / {_human(limit)} ({pct:.0f}%)"
    except KeyError:
        return "N/A"


def _fmt_net(stats: dict) -> str:
    try:
        nets = stats.get("networks", {})
        rx = sum(v["rx_bytes"] for v in nets.values())
        tx = sum(v["tx_bytes"] for v in nets.values())
        return f"{_human(rx)} ↓ / {_human(tx)} ↑"
    except Exception:
        return "N/A"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

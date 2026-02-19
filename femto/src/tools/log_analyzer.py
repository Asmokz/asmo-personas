"""Log analyzer — uses LLM to summarise Docker container logs."""
from __future__ import annotations

import structlog
from asmo_commons.llm.ollama_client import OllamaClient
from asmo_commons.tools.executor import CommandExecutor

logger = structlog.get_logger()

_ANALYSIS_SYSTEM = """Tu es un expert en analyse de logs Docker.
Analyse les logs fournis et synthétise :
1. Les erreurs critiques (ERROR, CRITICAL, FATAL, panic)
2. Les avertissements récurrents (WARNING, WARN)
3. Les anomalies ou patterns suspects
4. Un verdict : 🟢 OK | 🟡 À surveiller | 🔴 Problème détecté

Sois concis. Cite les lignes importantes mot pour mot.
Réponds en français.
"""

_MAX_LOG_CHARS = 8_000  # trim before sending to LLM


class LogAnalyzer:
    """Fetch recent logs and summarise them with the LLM."""

    def __init__(self, executor: CommandExecutor, ollama: OllamaClient) -> None:
        self._exec = executor
        self._ollama = ollama

    async def analyze_logs(self, container: str, hours: int = 24) -> str:
        """Fetch logs for *container* and return an LLM-generated summary.

        Args:
            container: Docker container name or ID.
            hours: How many hours back to look (used as --since parameter).

        Returns:
            Human-readable analysis in French.
        """
        logger.info("analyze_logs_start", container=container, hours=hours)

        # Fetch raw logs
        try:
            raw_logs = await self._exec.run(
                [
                    "docker",
                    "logs",
                    "--since",
                    f"{hours}h",
                    "--tail",
                    "500",
                    "--timestamps",
                    container,
                ],
                timeout=20,
            )
        except Exception as exc:
            return f"❌ Impossible de récupérer les logs de `{container}` : {exc}"

        if not raw_logs.strip():
            return f"📭 Aucun log pour `{container}` dans les {hours} dernières heures."

        # Trim to avoid huge LLM context
        trimmed = raw_logs[-_MAX_LOG_CHARS:]
        if len(raw_logs) > _MAX_LOG_CHARS:
            trimmed = f"[... logs tronqués — {len(raw_logs)} caractères au total]\n" + trimmed

        prompt = (
            f"Voici les logs du conteneur **{container}** "
            f"sur les {hours} dernières heures :\n\n"
            f"```\n{trimmed}\n```\n\n"
            "Fais une analyse concise."
        )

        try:
            analysis = await self._ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=_ANALYSIS_SYSTEM,
            )
            return f"🔍 **Analyse logs `{container}` ({hours}h)**\n\n{analysis}"
        except Exception as exc:
            logger.error("analyze_logs_llm_failed", container=container, error=str(exc))
            return (
                f"⚠️ Analyse LLM échouée pour `{container}` : {exc}\n\n"
                f"**Logs bruts (dernières lignes)** :\n```\n{raw_logs[-2000:]}\n```"
            )

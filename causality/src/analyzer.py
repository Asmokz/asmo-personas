"""Causality — PatternAnalyzer: weekly LLM analysis on failure metadata."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import aiohttp
import structlog

if TYPE_CHECKING:
    from .db.manager import DbManager

logger = structlog.get_logger()

CHANNEL = "asmo.alerts.causality"


class PatternAnalyzer:
    """Runs every Sunday at 20:00 local time. Calls Ollama to analyse failure
    patterns from the past 7 days and publishes the report to Redis."""

    def __init__(
        self,
        db: "DbManager",
        redis_url: str,
        ollama_url: str,
        ollama_model: str,
    ) -> None:
        self._db = db
        self._redis_url = redis_url
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                await _sleep_until_sunday_evening()
                if self._running:
                    await self._run_analysis()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("pattern_analysis_error", error=str(exc))

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------

    async def _run_analysis(self) -> None:
        logger.info("pattern_analysis_started")
        patterns = await self._db.get_failure_patterns(days=7)

        if patterns.get("total_calls", 0) < 10:
            logger.info(
                "pattern_analysis_skipped",
                reason="insufficient data",
                calls=patterns.get("total_calls"),
            )
            return

        prompt = _build_analysis_prompt(patterns)
        try:
            report = await self._call_ollama(prompt)
        except Exception as exc:
            logger.error("pattern_ollama_error", error=str(exc))
            return

        await self._db.save_analysis(report)
        await self._publish(report)
        logger.info("pattern_analysis_complete", report_len=len(report))

    async def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": self._ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._ollama_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:200]}")
                data = await resp.json()
        return data["message"]["content"]

    async def _publish(self, report: str) -> None:
        try:
            from datetime import timezone
            import redis.asyncio as aioredis
            r = aioredis.from_url(self._redis_url)
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "causality",
                "type": "pattern_analysis",
                "data": {"report": report},
            }
            await r.publish(CHANNEL, json.dumps(event))
            await r.aclose()
        except Exception as exc:
            logger.warning("pattern_publish_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_analysis_prompt(patterns: dict) -> str:
    lines = [
        "Tu es un ingénieur LLM Ops. Analyse les données d'usage des 7 derniers jours "
        "et identifie les patterns d'échec. Base-toi uniquement sur les métriques "
        "fournies — n'évalue pas le contenu des réponses.\n",
        f"## Volume global : {patterns['total_calls']} appels LLM, "
        f"{patterns['total_convs']} conversations\n",
        "## Performance par persona",
    ]
    for p in patterns.get("per_persona", []):
        lines.append(
            f"- {p['persona']} / {p['model']} : {p['calls']} appels, "
            f"{p['conv_count']} convs, "
            f"{p['unfinished_rate'] * 100:.0f}% non résolues, "
            f"avg {p['avg_turns']:.1f} tours, "
            f"{p['long_conv_pct'] * 100:.0f}% boucles longues (6+ tours), "
            f"avg {p['tok_s']:.1f} tok/s"
        )

    if patterns.get("tool_failures"):
        lines.append("\n## Taux d'échec par outil (résultats contenant une erreur)")
        for t in patterns["tool_failures"]:
            lines.append(
                f"- {t['tool']} : {t['fail']}/{t['total']} échecs "
                f"({t['rate'] * 100:.0f}%)"
            )

    if patterns.get("loop_correlations"):
        lines.append("\n## Combinaisons d'outils corrélées aux boucles longues (6+ tours)")
        for combo in patterns["loop_correlations"]:
            lines.append(
                f"- [{', '.join(combo['tools'])}] : "
                f"{combo['loop_count']}/{combo['total']} convs en boucle"
            )

    t = patterns.get("trend", {})
    if t:
        lines.append("\n## Tendance (3.5 premiers jours vs 3.5 derniers)")
        lines.append(
            f"- Taux non résolu : "
            f"{t['unfinished_first'] * 100:.0f}% → {t['unfinished_second'] * 100:.0f}%"
        )
        lines.append(
            f"- tok/s moyen : {t['tok_s_first']:.1f} → {t['tok_s_second']:.1f}"
        )

    lines.append(
        "\nFournis :\n"
        "1. Top 3 patterns problématiques identifiés avec cause probable\n"
        "2. Action recommandée pour chaque (formulation d'outil, prompt, limite historique)\n"
        "3. Tendance générale (amélioration / dégradation / stable)\n"
        "Sois concis. Format structuré en français."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sleep helper
# ---------------------------------------------------------------------------

async def _sleep_until_sunday_evening() -> None:
    """Sleep until Sunday 20:00 local time."""
    now = datetime.now()
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 20:
        days_until_sunday = 7  # already past 20h this Sunday, wait for next
    target = (now + timedelta(days=days_until_sunday)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    wait = (target - now).total_seconds()
    logger.info(
        "pattern_analyzer_sleep",
        target=target.isoformat(),
        wait_days=round(wait / 86400, 1),
    )
    await asyncio.sleep(wait)

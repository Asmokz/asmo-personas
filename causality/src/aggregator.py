"""Causality — MetricsAggregator: computes rolling metrics + detects drift."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .db.manager import DbManager

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Thresholds — calibrated from real data (ministral-3:14b baseline ~30 tok/s)
# ---------------------------------------------------------------------------
_THRESHOLDS = {
    "tok_s_floor": 15.0,        # hard minimum regardless of model
    "tok_s_drop_pct": 0.50,     # alert if current < 50% of 24h baseline
    "unfinished_rate": 0.35,    # >35% convs without final text (baseline ~12%)
    "tool_fail_rate": 0.25,     # >25% tool results with error (baseline ~5%)
    "long_conv_rate": 0.40,     # >40% convs with 6+ turns (baseline ~12%)
    "min_convs": 3,             # minimum convs to compute conv-based metrics
    "min_tool_results": 10,     # minimum tool results to compute tool metric
}

COOLDOWN_S = 3600              # 1h between identical alert types
CHANNEL = "asmo.alerts.causality"


class CausalityAggregator:
    """Runs every 10 minutes, computes 2h/24h metrics, publishes drift alerts."""

    def __init__(self, db: "DbManager", redis_url: str) -> None:
        self._db = db
        self._redis_url = redis_url
        self._cooldowns: dict[str, float] = {}
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                await asyncio.sleep(600)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("aggregator_tick_error", error=str(exc))

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        current = await self._db.get_metrics_window(hours=2)
        baseline = await self._db.get_metrics_window(hours=24)

        logger.debug(
            "aggregator_tick",
            calls_2h=current.get("call_count"),
            convs_2h=current.get("conv_count"),
            tok_s=current.get("tok_s_avg"),
        )

        alerts = _check_thresholds(current, baseline)
        for alert in alerts:
            if self._cooldown_ok(alert["alert_type"]):
                await self._publish(alert)
                self._cooldowns[alert["alert_type"]] = time.time()
                logger.info(
                    "drift_alert_fired",
                    alert_type=alert["alert_type"],
                    severity=alert["severity"],
                )

    def _cooldown_ok(self, alert_type: str) -> bool:
        return (time.time() - self._cooldowns.get(alert_type, 0)) >= COOLDOWN_S

    async def _publish(self, alert: dict) -> None:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(self._redis_url)
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "causality",
                "type": "drift_alert",
                "data": alert,
            }
            await r.publish(CHANNEL, json.dumps(event))
            await r.aclose()
        except Exception as exc:
            logger.warning("drift_alert_publish_failed", error=str(exc))

    async def get_summary(self) -> dict:
        """Return current 2h metrics + 24h baseline for the API."""
        current = await self._db.get_metrics_window(hours=2)
        baseline = await self._db.get_metrics_window(hours=24)
        alerts = _check_thresholds(current, baseline)
        status = "nominal"
        if any(a["severity"] == "critical" for a in alerts):
            status = "critical"
        elif alerts:
            status = "degraded"
        return {
            "window_2h": current,
            "baseline_24h": baseline,
            "status": status,
            "active_alerts": alerts,
        }


# ---------------------------------------------------------------------------
# Threshold checking (pure function — easy to test)
# ---------------------------------------------------------------------------

def _check_thresholds(current: dict, baseline: dict) -> list[dict]:
    alerts: list[dict] = []
    conv_count = current.get("conv_count", 0)

    # --- tok/s hard floor (independent of conv count) ---
    tok_s = current.get("tok_s_avg")
    if tok_s is not None:
        if tok_s < _THRESHOLDS["tok_s_floor"]:
            alerts.append({
                "alert_type": "tok_s_floor",
                "severity": "critical",
                "message": (
                    f"tok/s critique : {tok_s:.1f} tok/s "
                    f"(plancher : {_THRESHOLDS['tok_s_floor']})"
                ),
                "value": tok_s,
                "threshold": _THRESHOLDS["tok_s_floor"],
            })
        else:
            baseline_tok_s = baseline.get("tok_s_avg")
            if (baseline_tok_s and
                    tok_s < baseline_tok_s * (1 - _THRESHOLDS["tok_s_drop_pct"])):
                drop = (1 - tok_s / baseline_tok_s) * 100
                alerts.append({
                    "alert_type": "tok_s_degraded",
                    "severity": "warning",
                    "message": (
                        f"tok/s dégradé : {tok_s:.1f} vs baseline {baseline_tok_s:.1f} "
                        f"(−{drop:.0f}%)"
                    ),
                    "value": tok_s,
                    "baseline": baseline_tok_s,
                })

    # --- conv-based metrics need minimum volume ---
    if conv_count < _THRESHOLDS["min_convs"]:
        return alerts

    unfinished_rate = current.get("unfinished_rate")
    if (unfinished_rate is not None
            and unfinished_rate > _THRESHOLDS["unfinished_rate"]):
        alerts.append({
            "alert_type": "unfinished_rate",
            "severity": "warning",
            "message": (
                f"{unfinished_rate * 100:.0f}% des conversations sans réponse finale "
                f"sur 2h (seuil : {_THRESHOLDS['unfinished_rate'] * 100:.0f}%)"
            ),
            "value": unfinished_rate,
            "threshold": _THRESHOLDS["unfinished_rate"],
        })

    long_conv_rate = current.get("long_conv_rate")
    if (long_conv_rate is not None
            and long_conv_rate > _THRESHOLDS["long_conv_rate"]):
        alerts.append({
            "alert_type": "long_conv_rate",
            "severity": "warning",
            "message": (
                f"{long_conv_rate * 100:.0f}% des conversations avec 6+ tours "
                f"(seuil : {_THRESHOLDS['long_conv_rate'] * 100:.0f}%) — boucle probable"
            ),
            "value": long_conv_rate,
            "threshold": _THRESHOLDS["long_conv_rate"],
        })

    tool_fail_rate = current.get("tool_fail_rate")
    tool_total = (current.get("tool_ok", 0) or 0) + (current.get("tool_fail", 0) or 0)
    if (tool_fail_rate is not None
            and tool_total >= _THRESHOLDS["min_tool_results"]
            and tool_fail_rate > _THRESHOLDS["tool_fail_rate"]):
        alerts.append({
            "alert_type": "tool_fail_rate",
            "severity": "warning",
            "message": (
                f"{tool_fail_rate * 100:.0f}% d'échecs d'outils "
                f"({current.get('tool_fail')}/{tool_total}) "
                f"— seuil : {_THRESHOLDS['tool_fail_rate'] * 100:.0f}%"
            ),
            "value": tool_fail_rate,
            "threshold": _THRESHOLDS["tool_fail_rate"],
        })

    return alerts

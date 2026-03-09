"""Causality — LLM observability service."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import structlog
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .aggregator import CausalityAggregator
from .analyzer import PatternAnalyzer
from .db.manager import DbManager
from .hardware import HardwareSampler
from .subscriber import CausalitySubscriber

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("CAUSALITY_DB_PATH", "/data/causality.db")
REDIS_URL = os.getenv("ASMO_REDIS_URL", "redis://localhost:6379")
RETENTION_DAYS = int(os.getenv("CAUSALITY_RETENTION_DAYS", "7"))
PORT = int(os.getenv("CAUSALITY_PORT", "1966"))
LOG_LEVEL = os.getenv("ASMO_LOG_LEVEL", "INFO")
LOG_JSON = os.getenv("ASMO_LOG_JSON", "false").lower() == "true"
OLLAMA_BASE_URL = os.getenv("ASMO_OLLAMA_BASE_URL", "http://host.docker.internal:11434")
ANALYSIS_MODEL = os.getenv("CAUSALITY_ANALYSIS_MODEL", "ministral-3:14b")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
processors = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.JSONRenderer() if LOG_JSON else structlog.dev.ConsoleRenderer(),
]
structlog.configure(
    processors=processors,
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
db = DbManager(DB_PATH)
hw = HardwareSampler()
subscriber = CausalitySubscriber(db, hw, REDIS_URL)
aggregator = CausalityAggregator(db, REDIS_URL)
analyzer = PatternAnalyzer(db, REDIS_URL, OLLAMA_BASE_URL, ANALYSIS_MODEL)

_tasks: list[asyncio.Task] = []


async def _daily_cleanup() -> None:
    while True:
        await asyncio.sleep(86400)
        await db.cleanup_old(RETENTION_DAYS)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tasks
    await db.init()
    await db.cleanup_old(RETENTION_DAYS)
    _tasks = [
        asyncio.create_task(subscriber.run(), name="causality-subscriber"),
        asyncio.create_task(_daily_cleanup(), name="causality-cleanup"),
        asyncio.create_task(aggregator.run(), name="causality-aggregator"),
        asyncio.create_task(analyzer.run(), name="causality-analyzer"),
    ]
    logger.info(
        "causality_started",
        port=PORT,
        retention_days=RETENTION_DAYS,
        analysis_model=ANALYSIS_MODEL,
    )
    yield
    await subscriber.stop()
    await aggregator.stop()
    await analyzer.stop()
    for t in _tasks:
        if not t.done():
            t.cancel()
    await db.close()
    logger.info("causality_stopped")


app = FastAPI(title="Causality", lifespan=lifespan, docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/exchanges")
async def get_exchanges(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    persona: Optional[str] = Query(default=None),
):
    rows = await db.list_exchanges(limit, offset, persona)
    return JSONResponse(rows)


@app.get("/api/metrics/summary")
async def get_metrics_summary():
    """Return current 2h metrics, 24h baseline, and active drift alerts."""
    summary = await aggregator.get_summary()
    return JSONResponse(summary)


@app.get("/api/analysis/latest")
async def get_latest_analysis():
    """Return the most recent weekly PatternAnalyzer report."""
    result = await db.get_latest_analysis()
    if not result:
        return JSONResponse({"report": None, "created_at": None})
    return JSONResponse(result)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning", access_log=False)

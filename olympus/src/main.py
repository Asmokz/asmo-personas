"""Olympus — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Logging setup (must happen before app creation)
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    import logging
    log_level = os.environ.get("ASMO_LOG_LEVEL", "INFO").upper()
    log_json = os.environ.get("ASMO_LOG_JSON", "true").lower() == "true"

    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    if log_json:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ]
        )
    else:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="%H:%M:%S"),
                structlog.dev.ConsoleRenderer(),
            ]
        )


_configure_logging()


# ---------------------------------------------------------------------------
# Lifespan — startup/shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- OlympusDB ---
    from olympus.src.db.manager import OlympusDB
    db_path = os.environ.get("OLYMPUS_DB_PATH", "/data/olympus.db")
    db = OlympusDB(db_path)
    await db.init()
    app.state.db = db

    # --- Personas ---
    personas = {}
    await _init_personas(personas)
    app.state.personas = personas

    # --- STT ---
    stt: Optional[object] = None
    whisper_model = os.environ.get("WHISPER_MODEL", "small")
    if whisper_model.lower() not in ("disabled", "none", ""):
        try:
            from olympus.src.stt.whisper import WhisperSTT
            stt = WhisperSTT(model_size=whisper_model)
            logger.info("stt_ready", model=whisper_model)
        except Exception as exc:
            logger.warning("stt_init_failed", error=str(exc))
    app.state.stt = stt

    logger.info("olympus_ready", personas=list(personas.keys()))
    yield

    logger.info("olympus_shutdown")


async def _init_personas(personas: dict) -> None:
    """Initialise all configured personas, ignoring individual failures."""
    from asmo_commons.config.settings import AlitaSettings, FemtoSettings, GiorgioSettings

    # --- Alita ---
    try:
        settings = AlitaSettings()
        from olympus.src.personas.alita import AlitaPersona
        persona = AlitaPersona(settings)
        await persona.init()
        personas["alita"] = persona
        logger.info("persona_ready", id="alita")
    except Exception as exc:
        logger.warning("persona_init_failed", id="alita", error=str(exc))

    # --- Femto ---
    try:
        settings = FemtoSettings()
        from olympus.src.personas.femto import FemtoPersona
        persona = FemtoPersona(settings)
        personas["femto"] = persona
        logger.info("persona_ready", id="femto")
    except Exception as exc:
        logger.warning("persona_init_failed", id="femto", error=str(exc))

    # --- Giorgio ---
    try:
        settings = GiorgioSettings()
        from olympus.src.personas.giorgio import GiorgioPersona
        persona = GiorgioPersona(settings)
        await persona.init()
        asyncio.create_task(_sync_giorgio_library(persona))
        personas["giorgio"] = persona
        logger.info("persona_ready", id="giorgio")
    except Exception as exc:
        logger.warning("persona_init_failed", id="giorgio", error=str(exc))


async def _sync_giorgio_library(persona) -> None:
    """Background task to sync Giorgio's Jellyfin library index."""
    try:
        await persona.library_index.sync()
        logger.info("giorgio_library_synced")
    except Exception as exc:
        logger.warning("giorgio_library_sync_failed", error=str(exc))


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Olympus API",
    version="0.2.0",
    description="HTTP/WebSocket gateway for ASMO personas",
    lifespan=lifespan,
)

# CORS — allow all in dev; restrict in prod via reverse proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from olympus.src.routers import chat, conversations, feedback, personas, portfolio, voice
app.include_router(personas.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(feedback.router)
app.include_router(portfolio.router)
app.include_router(voice.router)


@app.get("/health")
async def health():
    return {"status": "ok", "personas": list(app.state.personas.keys()) if hasattr(app.state, "personas") else []}


# Serve Vue.js frontend (built assets) — only if dist/ exists
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("OLYMPUS_PORT", 8484))
    uvicorn.run(
        "olympus.src.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_config=None,
    )

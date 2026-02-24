"""ALITA entry point — Discord bot + FastAPI (Spotify OAuth callback)."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

import structlog

from asmo_commons.config.settings import AlitaSettings
from .bot import AlitaBot


def configure_logging(log_level: str, json_logs: bool) -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _create_spotify_app(bot: AlitaBot):
    """Create a minimal FastAPI app for the Spotify OAuth callback."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
    except ImportError:
        return None

    app = FastAPI(title="Alita Spotify Auth", docs_url=None, redoc_url=None)

    @app.get("/spotify/callback")
    async def spotify_callback(code: Optional[str] = None, error: Optional[str] = None):
        if error:
            return HTMLResponse(f"<h1>❌ Erreur : {error}</h1>")
        if not code:
            return HTMLResponse("<h1>❌ Code OAuth manquant</h1>")
        result = await bot.spotify.handle_oauth_callback(code)
        return HTMLResponse(f"<h1>{result}</h1><p>Tu peux fermer cet onglet.</p>")

    @app.get("/health")
    async def health():
        return {"status": "ok", "bot": str(bot.user)}

    return app


async def main() -> None:
    settings = AlitaSettings()
    configure_logging(settings.asmo_log_level, settings.asmo_log_json)
    logger = structlog.get_logger()

    bot = AlitaBot(settings)
    loop = asyncio.get_running_loop()

    # Only start the FastAPI server if Spotify is configured
    coroutines = [bot.start(settings.alita_discord_token)]
    server = None

    if settings.alita_spotify_client_id:
        app = _create_spotify_app(bot)
        if app is not None:
            try:
                import uvicorn
                uv_config = uvicorn.Config(
                    app,
                    host="0.0.0.0",
                    port=settings.alita_spotify_port,
                    log_level="warning",
                    access_log=False,
                )
                server = uvicorn.Server(uv_config)
                coroutines.append(server.serve())
                logger.info("spotify_oauth_server_starting", port=settings.alita_spotify_port)
            except ImportError:
                logger.warning("uvicorn_not_installed_spotify_auth_disabled")

    async def _shutdown() -> None:
        logger.info("alita_stopping")
        if server:
            server.should_exit = True
        if not bot.is_closed():
            await bot.close()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.create_task(_shutdown()))

    logger.info("alita_starting", model=settings.alita_ollama_model)

    try:
        await asyncio.gather(*coroutines)
    except Exception as exc:
        logger.error("alita_crashed", error=str(exc))
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Pydantic-settings configuration for all ASMO services."""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAsmoSettings(BaseSettings):
    """Common settings shared by all ASMO services.

    All env vars are prefixed with ASMO_ for shared ones.
    Each service adds its own prefixed vars.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Ollama ---
    asmo_ollama_base_url: str = "http://host.docker.internal:11434"
    asmo_ollama_model: str = "mistral:7b"
    asmo_ollama_timeout: int = 120
    asmo_ollama_max_retries: int = 3
    asmo_ollama_retry_min_wait: float = 1.0
    asmo_ollama_retry_max_wait: float = 10.0

    # --- Redis ---
    asmo_redis_url: str = "redis://redis:6379"

    # --- Logging ---
    asmo_log_level: str = "INFO"
    asmo_log_json: bool = True  # JSON logs in prod, False for dev console renderer


class FemtoSettings(BaseAsmoSettings):
    """Settings for the FEMTO monitoring bot."""

    # Discord
    femto_discord_token: str
    femto_report_channel_id: Optional[int] = None

    # Persistence
    femto_metrics_file: str = "/data/metrics.json"
    femto_metrics_retention_hours: int = 24

    # Operational
    femto_max_log_lines: int = 50
    femto_cmd_timeout: int = 10
    femto_history_report_hour: int = 9  # daily report at 9h00


class AlitaSettings(BaseAsmoSettings):
    """Settings for the ALITA briefing bot."""

    alita_discord_token: str
    alita_briefing_channel_id: Optional[int] = None
    alita_briefing_hour: int = 9

    alita_weather_api_key: Optional[str] = None
    alita_weather_city: str = "Paris"


class GiorgioSettings(BaseAsmoSettings):
    """Settings for the GIORGIO media bot."""

    giorgio_discord_token: str
    giorgio_recommendation_channel_id: Optional[int] = None

    giorgio_jellyfin_url: Optional[str] = None
    giorgio_jellyfin_api_key: Optional[str] = None
    giorgio_jellyfin_user_id: Optional[str] = None

"""Pydantic-settings configuration for all ASMO services."""
from __future__ import annotations

from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAsmoSettings(BaseSettings):
    """Common settings shared by all ASMO services.

    All env vars are prefixed with ASMO_ for shared ones.
    Each service adds its own prefixed vars.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_str_to_none(cls, data: dict) -> dict:
        """Convert empty-string env vars to None for all Optional fields."""
        if isinstance(data, dict):
            return {k: (None if v == "" else v) for k, v in data.items()}
        return data

    # --- Ollama ---
    asmo_ollama_base_url: str = "http://host.docker.internal:11434"
    asmo_ollama_model: str = "ministral-3:14b"
    asmo_ollama_timeout: int = 240
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

    # LLM — falls back to ASMO_OLLAMA_MODEL if not set in .env
    femto_ollama_model: Optional[str] = None

    @model_validator(mode="after")
    def _model_fallback(self) -> "FemtoSettings":
        if not self.femto_ollama_model:
            self.femto_ollama_model = self.asmo_ollama_model
        return self

    # Discord
    femto_discord_token: str
    femto_report_channel_id: Optional[int] = None
    femto_chat_channel_id: Optional[int] = None  # responds to all messages without mention

    # NAS disk for SMART monitoring
    femto_nas_device: str = "/dev/sda"
    femto_nas_smart_type: str = "sat"  # -d flag for smartctl (sat, ata, auto…)

    # Persistence
    femto_metrics_file: str = "/data/metrics.json"
    femto_metrics_retention_hours: int = 24

    # Operational
    femto_max_log_lines: int = 50
    femto_cmd_timeout: int = 10
    femto_history_report_hour: int = 9  # daily report at 9h00


class AlitaSettings(BaseAsmoSettings):
    """Settings for the ALITA personal assistant bot."""

    # Discord
    alita_discord_token: str
    alita_discord_channel_id: Optional[int] = None  # dedicated channel (responds to all messages)
    alita_briefing_channel_id: Optional[int] = None
    alita_briefing_hour: int = 7
    alita_briefing_weekdays_only: bool = True  # skip Sat/Sun

    # LLM — falls back to ASMO_OLLAMA_MODEL if not set in .env
    alita_ollama_model: Optional[str] = None

    @model_validator(mode="after")
    def _model_fallback(self) -> "AlitaSettings":
        if not self.alita_ollama_model:
            self.alita_ollama_model = self.asmo_ollama_model
        return self

    # Weather
    alita_weather_api_key: Optional[str] = None
    alita_weather_city: str = "Marseille,FR"

    # Stocks — JSON array: [{"symbol":"AAPL","shares":10,"avg_price":150.0}, ...]
    alita_portfolio: str = "[]"

    # Home Assistant
    alita_ha_url: str = "http://homeassistant:8123"
    alita_ha_token: Optional[str] = None

    # Spotify OAuth
    alita_spotify_client_id: Optional[str] = None
    alita_spotify_client_secret: Optional[str] = None
    alita_spotify_redirect_uri: str = "http://localhost:8888/spotify/callback"
    alita_spotify_port: int = 8888

    # SearXNG
    alita_searxng_url: str = "http://searxng:8080"

    # Database
    alita_db_path: str = "/data/alita.db"

    # Long-term memory (RAG)
    alita_embed_model: str = "nomic-embed-text"

    # Training data collection
    alita_training_db_path: str = "/data/alita_training.db"

    # Anytype self-hosted
    alita_anytype_url: str = "http://127.0.0.1:31012"
    alita_anytype_api_key: Optional[str] = None
    alita_anytype_space_id: Optional[str] = None


class GiorgioSettings(BaseAsmoSettings):
    """Settings for the GIORGIO media bot."""

    # LLM — falls back to ASMO_OLLAMA_MODEL if not set in .env
    giorgio_ollama_model: Optional[str] = None

    @model_validator(mode="after")
    def _model_fallback(self) -> "GiorgioSettings":
        if not self.giorgio_ollama_model:
            self.giorgio_ollama_model = self.asmo_ollama_model
        return self

    # Discord
    giorgio_discord_token: str
    giorgio_channel_id: int  # Channel for rating notifications
    giorgio_recommendation_channel_id: Optional[int] = None

    # Jellyfin
    giorgio_jellyfin_url: str = ""
    giorgio_jellyfin_api_key: str = ""
    giorgio_jellyfin_user_id: str = ""
    giorgio_sync_interval_hours: int = 6

    # MariaDB (existing container via shared Docker network)
    giorgio_db_host: str = "giorgio-db"
    giorgio_db_port: int = 3306
    giorgio_db_name: str = "giorgio"
    giorgio_db_user: str = "giorgio"
    giorgio_db_password: str = ""

    # SearXNG
    giorgio_searxng_url: str = "http://searxng:8080"

    # Embedding model for semantic library index (RAG)
    giorgio_embed_model: str = "nomic-embed-text"
    giorgio_vector_db_path: str = "/data/giorgio_vectors.db"

    # Webhook API
    giorgio_api_port: int = 5555

    # Comma-separated Jellyfin usernames that receive Discord rating prompts
    giorgio_notification_users: str = "asmo"

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.giorgio_db_user}:{self.giorgio_db_password}"
            f"@{self.giorgio_db_host}:{self.giorgio_db_port}/{self.giorgio_db_name}"
        )

    @property
    def notification_users_list(self) -> list[str]:
        return [u.strip().lower() for u in self.giorgio_notification_users.split(",") if u.strip()]

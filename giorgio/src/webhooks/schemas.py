"""Jellyfin webhook payload schema."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JellyfinWebhook(BaseModel):
    NotificationType: str
    ItemId: str
    ItemType: str
    Name: str
    UserId: str
    NotificationUsername: str
    Timestamp: datetime

    # Episodes only
    SeriesName: Optional[str] = None
    SeasonNumber: Optional[int] = None
    EpisodeNumber: Optional[int] = None

    # Optional fields
    PlayedToCompletion: Optional[bool] = None
    Year: Optional[int] = None
    Provider_tmdb: Optional[str] = None
    Genres: Optional[str] = None  # raw comma-separated string

    def get_genres_list(self) -> list[str]:
        if not self.Genres:
            return []
        return [g.strip() for g in self.Genres.split(",") if g.strip()]

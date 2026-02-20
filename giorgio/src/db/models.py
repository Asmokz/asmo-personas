"""SQLAlchemy ORM — mirrors the existing Giorgio MariaDB schema exactly."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """Jellyfin user tracked by Giorgio."""

    __tablename__ = "users"

    jellyfin_id = Column(String(36), primary_key=True)
    username = Column(String(100), nullable=False)
    discord_id = Column(String(20), nullable=True)

    watchlogs = relationship("Watchlog", back_populates="user")


class Content(Base):
    """Movie or episode in the catalogue."""

    __tablename__ = "contents"

    id = Column(String(36), primary_key=True)  # Jellyfin UUID
    title = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False)  # 'movie' | 'episode'
    year = Column(Integer, nullable=True)
    genres = Column(JSON, nullable=True)  # ["Action", "Sci-Fi"]
    tmdb_id = Column(String(20), nullable=True)
    length = Column(Integer, nullable=True)  # minutes

    watchlogs = relationship("Watchlog", back_populates="content")


class Watchlog(Base):
    """Watch event with optional rating."""

    __tablename__ = "watchlogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.jellyfin_id"), nullable=False)
    content_id = Column(String(36), ForeignKey("contents.id"), nullable=False)
    rating = Column(Integer, nullable=True)  # 1-10
    watched_at = Column(DateTime, default=datetime.utcnow)
    rated_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="watchlogs")
    content = relationship("Content", back_populates="watchlogs")

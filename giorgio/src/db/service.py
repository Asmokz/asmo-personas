"""Database service — synchronous SQLAlchemy wrapped for Giorgio.

All public functions use SessionLocal() with explicit close in finally blocks,
mirroring the original Giorgio pattern. Sync calls from async contexts are
acceptable here because the DB is on a local Docker network (< 5ms latency).

Key fix over original: GROUP BY now includes all non-aggregated SELECT columns
to comply with MySQL strict mode. get_most_watched() also aggregates episodes
by series name extracted from their titles.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from .models import Base, Content, User, Watchlog

logger = structlog.get_logger()

_engine = None
_SessionLocal = None


def init_db(db_url: str) -> None:
    """Initialise the SQLAlchemy engine. Call once at startup."""
    global _engine, _SessionLocal
    _engine = create_engine(db_url, pool_pre_ping=True, echo=False)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    # Do NOT call Base.metadata.create_all() — the existing DB already has the schema.
    logger.info("db_engine_created")


def _session():
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _SessionLocal()


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------


def get_or_create_user(jellyfin_id: str, username: str) -> User:
    db = _session()
    try:
        user = db.query(User).filter(User.jellyfin_id == jellyfin_id).first()
        if not user:
            user = User(jellyfin_id=jellyfin_id, username=username)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("user_created", username=username)
        return user
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Content operations
# ---------------------------------------------------------------------------


def get_or_create_content(
    content_id: str,
    title: str,
    content_type: str,
    year: Optional[int] = None,
    genres: Optional[list] = None,
    tmdb_id: Optional[str] = None,
    length: Optional[int] = None,
) -> Content:
    db = _session()
    try:
        content = db.query(Content).filter(Content.id == content_id).first()
        if not content:
            content = Content(
                id=content_id,
                title=title,
                type=content_type,
                year=year,
                genres=genres,
                tmdb_id=tmdb_id,
                length=length,
            )
            db.add(content)
            db.commit()
            db.refresh(content)
            logger.info("content_created", title=title, type=content_type)
        return content
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Watchlog operations
# ---------------------------------------------------------------------------


def create_watchlog(user_id: str, content_id: str) -> Watchlog:
    db = _session()
    try:
        watchlog = Watchlog(
            user_id=user_id,
            content_id=content_id,
            watched_at=datetime.utcnow(),
        )
        db.add(watchlog)
        db.commit()
        db.refresh(watchlog)
        logger.info("watchlog_created", user_id=user_id, content_id=content_id)
        return watchlog
    finally:
        db.close()


def update_rating(watchlog_id: int, rating: int) -> Optional[Watchlog]:
    db = _session()
    try:
        watchlog = db.query(Watchlog).filter(Watchlog.id == watchlog_id).first()
        if watchlog:
            watchlog.rating = rating
            watchlog.rated_at = datetime.utcnow()
            db.commit()
            db.refresh(watchlog)
            logger.info("rating_updated", watchlog_id=watchlog_id, rating=rating)
        return watchlog
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Stats queries
# ---------------------------------------------------------------------------


def get_most_watched(limit: int = 10) -> list[dict]:
    """Return the most-watched films and series.

    Fix vs original:
    - GROUP BY includes ALL non-aggregated columns (MySQL strict mode compliant).
    - Episodes are aggregated by series name extracted from their title
      (format: "Series Name S01E01"), so a series shows as one entry.
    """
    db = _session()
    try:
        rows = (
            db.query(
                Content.id,
                Content.title,
                Content.type,
                Content.year,
                func.count(Watchlog.id).label("watch_count"),
                func.avg(Watchlog.rating).label("avg_rating"),
            )
            .join(Watchlog, Content.id == Watchlog.content_id)
            .group_by(Content.id, Content.title, Content.type, Content.year)
            .order_by(func.count(Watchlog.id).desc())
            .all()
        )
    finally:
        db.close()

    movies: list[dict] = []
    series: dict[str, dict] = {}

    for r in rows:
        if r.type == "episode":
            # Extract series name from "Series Name S01E01" pattern
            m = re.match(r"^(.+?)\s+S\d+E\d+", r.title)
            series_name = m.group(1) if m else r.title
            if series_name not in series:
                series[series_name] = {
                    "title": series_name,
                    "type": "series",
                    "year": r.year,
                    "watch_count": 0,
                    "ratings": [],
                }
            series[series_name]["watch_count"] += r.watch_count
            if r.avg_rating is not None:
                series[series_name]["ratings"].append(float(r.avg_rating))
        else:
            movies.append(
                {
                    "title": r.title,
                    "type": r.type,
                    "year": r.year,
                    "watch_count": r.watch_count,
                    "avg_rating": round(float(r.avg_rating), 1) if r.avg_rating else None,
                }
            )

    series_list = []
    for s in series.values():
        avg = sum(s["ratings"]) / len(s["ratings"]) if s["ratings"] else None
        series_list.append(
            {
                "title": s["title"],
                "type": "series",
                "year": s["year"],
                "watch_count": s["watch_count"],
                "avg_rating": round(avg, 1) if avg else None,
            }
        )

    combined = movies + series_list
    combined.sort(key=lambda x: x["watch_count"], reverse=True)
    return combined[:limit]


def get_top_rated(limit: int = 10, min_ratings: int = 1) -> list[dict]:
    """Return top-rated content (movies and individual episodes/series)."""
    db = _session()
    try:
        rows = (
            db.query(
                Content.id,
                Content.title,
                Content.type,
                Content.year,
                func.avg(Watchlog.rating).label("avg_rating"),
                func.count(Watchlog.rating).label("rating_count"),
            )
            .join(Watchlog, Content.id == Watchlog.content_id)
            .filter(Watchlog.rating.isnot(None))
            .group_by(Content.id, Content.title, Content.type, Content.year)
            .having(func.count(Watchlog.rating) >= min_ratings)
            .order_by(func.avg(Watchlog.rating).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "title": r.title,
                "type": r.type,
                "year": r.year,
                "avg_rating": round(float(r.avg_rating), 1),
                "rating_count": r.rating_count,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_user_stats(user_id: str) -> Optional[dict]:
    """Return watch/rating stats for a given Jellyfin user ID."""
    db = _session()
    try:
        user = db.query(User).filter(User.jellyfin_id == user_id).first()
        if not user:
            return None

        total_watched = (
            db.query(func.count(Watchlog.id))
            .filter(Watchlog.user_id == user_id)
            .scalar()
        )
        total_rated = (
            db.query(func.count(Watchlog.id))
            .filter(Watchlog.user_id == user_id, Watchlog.rating.isnot(None))
            .scalar()
        )
        avg_rating = (
            db.query(func.avg(Watchlog.rating))
            .filter(Watchlog.user_id == user_id, Watchlog.rating.isnot(None))
            .scalar()
        )
        movies_watched = (
            db.query(func.count(Watchlog.id))
            .join(Content, Watchlog.content_id == Content.id)
            .filter(Watchlog.user_id == user_id, Content.type == "movie")
            .scalar()
        )
        episodes_watched = (
            db.query(func.count(Watchlog.id))
            .join(Content, Watchlog.content_id == Content.id)
            .filter(Watchlog.user_id == user_id, Content.type == "episode")
            .scalar()
        )
        return {
            "user_id": user_id,
            "username": user.username,
            "total_watched": total_watched,
            "total_rated": total_rated,
            "avg_rating_given": round(float(avg_rating), 1) if avg_rating else None,
            "movies_watched": movies_watched,
            "episodes_watched": episodes_watched,
        }
    finally:
        db.close()


def get_global_stats() -> dict:
    """Return catalogue-wide statistics."""
    db = _session()
    try:
        total_users = db.query(func.count(User.jellyfin_id)).scalar()
        total_contents = db.query(func.count(Content.id)).scalar()
        total_movies = db.query(func.count(Content.id)).filter(Content.type == "movie").scalar()
        total_episodes = db.query(func.count(Content.id)).filter(Content.type == "episode").scalar()
        total_watchlogs = db.query(func.count(Watchlog.id)).scalar()
        total_ratings = (
            db.query(func.count(Watchlog.id)).filter(Watchlog.rating.isnot(None)).scalar()
        )
        avg_rating = (
            db.query(func.avg(Watchlog.rating)).filter(Watchlog.rating.isnot(None)).scalar()
        )
        return {
            "users": total_users,
            "catalog": {
                "total": total_contents,
                "movies": total_movies,
                "episodes": total_episodes,
            },
            "activity": {
                "total_watches": total_watchlogs,
                "total_ratings": total_ratings,
                "avg_rating": round(float(avg_rating), 1) if avg_rating else None,
            },
        }
    finally:
        db.close()


def get_genre_taste_profile() -> dict[str, dict]:
    """Return per-genre taste profile aggregated from all rated content.

    Iterates rated watchlogs in Python (JSON unnesting is simpler here than
    in MariaDB). Returns a dict keyed by genre with avg_rating and count.
    Only genres with at least 2 rated entries are included to avoid noise.
    """
    db = _session()
    try:
        rows = (
            db.query(Content.genres, Watchlog.rating)
            .join(Watchlog, Content.id == Watchlog.content_id)
            .filter(Watchlog.rating.isnot(None), Content.genres.isnot(None))
            .all()
        )
    finally:
        db.close()

    genre_ratings: dict[str, list[float]] = {}
    for genres, rating in rows:
        if not genres:
            continue
        for genre in genres:
            genre_ratings.setdefault(genre, []).append(float(rating))

    return {
        genre: {
            "avg_rating": round(sum(ratings) / len(ratings), 1),
            "count": len(ratings),
        }
        for genre, ratings in genre_ratings.items()
        if len(ratings) >= 2
    }


def get_top_rated_by_genre(genre: str, limit: int = 5) -> list[dict]:
    """Return top-rated content whose genres JSON contains the requested genre.

    Filtering is done in Python after a broad query to avoid complex JSON SQL.
    """
    db = _session()
    try:
        rows = (
            db.query(
                Content.id,
                Content.title,
                Content.type,
                Content.year,
                Content.genres,
                func.avg(Watchlog.rating).label("avg_rating"),
                func.count(Watchlog.rating).label("rating_count"),
            )
            .join(Watchlog, Content.id == Watchlog.content_id)
            .filter(Watchlog.rating.isnot(None), Content.genres.isnot(None))
            .group_by(Content.id, Content.title, Content.type, Content.year, Content.genres)
            .order_by(func.avg(Watchlog.rating).desc())
            .all()
        )
    finally:
        db.close()

    genre_lower = genre.lower()
    results = []
    for r in rows:
        if not r.genres:
            continue
        if any(g.lower() == genre_lower for g in r.genres):
            results.append({
                "title": r.title,
                "type": r.type,
                "year": r.year,
                "genres": r.genres,
                "avg_rating": round(float(r.avg_rating), 1),
                "rating_count": r.rating_count,
            })
        if len(results) >= limit:
            break
    return results


def get_recent_activity(limit: int = 10) -> list[dict]:
    """Return the most recent watch events."""
    db = _session()
    try:
        rows = (
            db.query(Watchlog, User, Content)
            .join(User, Watchlog.user_id == User.jellyfin_id)
            .join(Content, Watchlog.content_id == Content.id)
            .order_by(Watchlog.watched_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "username": user.username,
                "content_title": content.title,
                "content_type": content.type,
                "rating": watchlog.rating,
                "watched_at": watchlog.watched_at.isoformat(),
                "rated_at": watchlog.rated_at.isoformat() if watchlog.rated_at else None,
            }
            for watchlog, user, content in rows
        ]
    finally:
        db.close()

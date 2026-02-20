"""LLM-callable stats tools for GIORGIO — formatted text responses."""
from __future__ import annotations

from ..db import service as db


async def get_top_rated_contents(limit: int = 10) -> str:
    """Return top-rated films/series as human-readable text for the LLM."""
    results = db.get_top_rated(limit=limit, min_ratings=1)
    if not results:
        return "Aucun contenu noté pour l'instant, *caro*."
    lines = ["🏆 **Top contenus notés** :"]
    for i, r in enumerate(results, 1):
        year = f" ({r['year']})" if r.get("year") else ""
        label = f"{r['type'].upper()}"
        lines.append(
            f"{i}. **{r['title']}**{year} [{label}]"
            f" — {r['avg_rating']}/10 ({r['rating_count']} note(s))"
        )
    return "\n".join(lines)


async def get_most_watched_contents(limit: int = 10) -> str:
    """Return most-watched content as human-readable text for the LLM."""
    results = db.get_most_watched(limit=limit)
    if not results:
        return "Aucune activité de visionnage enregistrée."
    lines = ["📊 **Contenus les plus vus** :"]
    for i, r in enumerate(results, 1):
        year = f" ({r['year']})" if r.get("year") else ""
        rating = f" | moy. {r['avg_rating']}/10" if r.get("avg_rating") else ""
        label = r["type"].upper()
        lines.append(
            f"{i}. **{r['title']}**{year} [{label}]"
            f" — {r['watch_count']} visionnage(s){rating}"
        )
    return "\n".join(lines)


async def get_recent_watches(limit: int = 10) -> str:
    """Return recent watch activity as human-readable text for the LLM."""
    results = db.get_recent_activity(limit=limit)
    if not results:
        return "Aucune activité récente."
    lines = ["🕐 **Activité récente** :"]
    for r in results:
        rating = f" — {r['rating']}/10" if r.get("rating") else " — non noté"
        date = r["watched_at"][:10]
        lines.append(f"• **{r['username']}** : {r['content_title']}{rating} ({date})")
    return "\n".join(lines)


async def get_global_statistics() -> str:
    """Return global catalogue statistics as human-readable text for the LLM."""
    s = db.get_global_stats()
    avg = s["activity"]["avg_rating"]
    return (
        f"📈 **Statistiques GIORGIO**\n"
        f"Utilisateurs : {s['users']}\n"
        f"Catalogue : {s['catalog']['total']} contenus"
        f" ({s['catalog']['movies']} films, {s['catalog']['episodes']} épisodes)\n"
        f"Visionnages : {s['activity']['total_watches']}\n"
        f"Notes données : {s['activity']['total_ratings']}\n"
        f"Note moyenne : {avg if avg else 'N/A'}/10"
    )

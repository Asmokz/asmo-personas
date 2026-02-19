"""Jellyfin API client (read-only)."""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()


class JellyfinClient:
    """Read-only client for the Jellyfin media server API."""

    def __init__(
        self,
        base_url: Optional[str],
        api_key: Optional[str],
        user_id: Optional[str],
    ) -> None:
        self._base = (base_url or "").rstrip("/")
        self._api_key = api_key
        self._user_id = user_id

    def _configured(self) -> bool:
        return bool(self._base and self._api_key and self._user_id)

    def _headers(self) -> dict:
        return {
            "X-Emby-Authorization": (
                f'MediaBrowser Client="GIORGIO", '
                f'Token="{self._api_key}"'
            )
        }

    async def get_recent_items(self, limit: int = 10) -> str:
        """Return recently added items."""
        if not self._configured():
            return "⚠️ Jellyfin non configuré (GIORGIO_JELLYFIN_URL, _API_KEY, _USER_ID)"

        url = f"{self._base}/Users/{self._user_id}/Items/Latest"
        params = {"Limit": limit, "Fields": "Overview,Genres,ProductionYear"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Jellyfin HTTP {resp.status}"
                    items = await resp.json()
            return _format_items(items, "Ajouts récents")
        except Exception as exc:
            return f"❌ Jellyfin indisponible : {exc}"

    async def search_media(self, query: str) -> str:
        """Search for media by name."""
        if not self._configured():
            return "⚠️ Jellyfin non configuré"

        url = f"{self._base}/Items"
        params = {
            "UserId": self._user_id,
            "SearchTerm": query,
            "IncludeItemTypes": "Movie,Series",
            "Recursive": "true",
            "Fields": "Overview,Genres,ProductionYear",
            "Limit": 5,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            items = data.get("Items", [])
            return _format_items(items, f'Résultats pour "{query}"')
        except Exception as exc:
            return f"❌ Recherche échouée : {exc}"

    async def get_libraries(self) -> str:
        """Return available media libraries."""
        if not self._configured():
            return "⚠️ Jellyfin non configuré"

        url = f"{self._base}/Users/{self._user_id}/Views"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            items = data.get("Items", [])
            return "\n".join(
                f"📁 {it['Name']} ({it.get('CollectionType', 'mixed')})"
                for it in items
            )
        except Exception as exc:
            return f"❌ Librairies indisponibles : {exc}"


def _format_items(items: list[dict], title: str) -> str:
    if not items:
        return f"_{title} : aucun résultat_"
    lines = [f"🎬 **{title}**"]
    for it in items:
        name = it.get("Name", "?")
        year = it.get("ProductionYear", "")
        genres = ", ".join(it.get("Genres", [])[:3])
        overview = (it.get("Overview") or "")[:100]
        meta = " | ".join(filter(None, [str(year), genres]))
        lines.append(f"**{name}** ({meta})")
        if overview:
            lines.append(f"  _{overview}_")
    return "\n".join(lines)

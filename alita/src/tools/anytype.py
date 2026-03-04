"""Anytype tool — REST API integration for notes and project tracking."""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()

_TIMEOUT = aiohttp.ClientTimeout(total=15)


class AnytypeTool:
    """Interact with a self-hosted Anytype instance via its REST API."""

    def __init__(self, base_url: str, api_key: Optional[str], space_id: Optional[str]) -> None:
        self._url = base_url.rstrip("/")
        self._api_key = api_key
        self._space_id = space_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _available(self) -> bool:
        return bool(self._api_key and self._space_id)

    def _objects_url(self, path: str = "") -> str:
        return f"{self._url}/v1/spaces/{self._space_id}/objects{path}"

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def create_note(self, title: str, body: str = "", type_key: str = "page") -> str:
        """Create a new page/note in Anytype."""
        if not self._available():
            return "⚠️ Anytype non configuré (ALITA_ANYTYPE_API_KEY ou ALITA_ANYTYPE_SPACE_ID manquant)"
        payload: dict = {"name": title, "type_key": type_key}
        if body:
            payload["body"] = body
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._objects_url(),
                    headers=self._headers(),
                    json=payload,
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        return f"❌ Erreur Anytype {resp.status} : {text[:200]}"
                    data = await resp.json()
            obj = data.get("object", {})
            obj_id = obj.get("id", "?")
            return (
                f"✅ Note créée dans Anytype : **{title}**\n"
                f"🔑 ID : `{obj_id}`"
            )
        except Exception as exc:
            logger.error("anytype_create_error", error=str(exc))
            return f"❌ Anytype indisponible : {exc}"

    async def search(self, query: str, limit: int = 10) -> str:
        """Full-text search across all objects in the space."""
        if not self._available():
            return "⚠️ Anytype non configuré"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/v1/spaces/{self._space_id}/search",
                    headers=self._headers(),
                    json={"query": query, "limit": limit},
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur recherche Anytype {resp.status}"
                    data = await resp.json()
            objects = data.get("data", [])
            if not objects:
                return f"📭 Aucun résultat dans Anytype pour « {query} »"
            lines = [f"🔍 **Anytype — {len(objects)} résultat(s) pour « {query} »**"]
            for obj in objects:
                name = obj.get("name") or "Sans titre"
                obj_id = obj.get("id", "?")
                snippet = (obj.get("snippet") or "")[:100]
                type_name = obj.get("type", {}).get("name", "?")
                lines.append(f"• **{name}** ({type_name}) — `{obj_id}`")
                if snippet:
                    lines.append(f"  _{snippet}_")
            return "\n".join(lines)
        except Exception as exc:
            logger.error("anytype_search_error", error=str(exc))
            return f"❌ Erreur recherche Anytype : {exc}"

    async def get_object(self, object_id: str) -> str:
        """Fetch and return the full content of an Anytype object."""
        if not self._available():
            return "⚠️ Anytype non configuré"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._objects_url(f"/{object_id}"),
                    headers=self._headers(),
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 404:
                        return f"❌ Objet `{object_id}` introuvable dans Anytype"
                    if resp.status != 200:
                        return f"❌ Erreur Anytype {resp.status}"
                    data = await resp.json()
            obj = data.get("object", data)
            name = obj.get("name") or "Sans titre"
            type_name = obj.get("type", {}).get("name", "?")
            snippet = obj.get("snippet", "")
            markdown = obj.get("markdown", "")
            lines = [f"📄 **{name}** ({type_name})"]
            if snippet and not markdown:
                lines.append(f"_{snippet}_")
            if markdown:
                lines.append("")
                # Truncate to avoid Discord 2000-char limit downstream
                lines.append(markdown[:1800])
            return "\n".join(lines)
        except Exception as exc:
            logger.error("anytype_get_error", error=str(exc))
            return f"❌ Erreur lecture Anytype : {exc}"

    async def update_object(self, object_id: str, body: Optional[str] = None, title: Optional[str] = None) -> str:
        """Update the content and/or title of an existing Anytype object.

        The Anytype API returns content as 'markdown' on GET but may expect a
        different field on PATCH. We try both 'body' and 'markdown' to cover
        both API versions, and log the full response for debugging.
        """
        if not self._available():
            return "⚠️ Anytype non configuré"
        if not body and not title:
            return "❌ Fournis au moins body ou title pour mettre à jour l'objet."
        payload: dict = {}
        if title:
            payload["name"] = title
        if body:
            # The GET endpoint returns content as 'markdown'; try both field names
            payload["body"] = body
            payload["markdown"] = body
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    self._objects_url(f"/{object_id}"),
                    headers=self._headers(),
                    json=payload,
                    timeout=_TIMEOUT,
                ) as resp:
                    raw = await resp.text()
                    logger.debug(
                        "anytype_update_response",
                        status=resp.status,
                        object_id=object_id,
                        payload_keys=list(payload.keys()),
                        response=raw[:500],
                    )
                    if resp.status == 404:
                        return f"❌ Objet `{object_id}` introuvable dans Anytype."
                    if resp.status not in (200, 201, 204):
                        return f"❌ Erreur Anytype {resp.status} : {raw[:300]}"
                    try:
                        data = __import__("json").loads(raw) if raw.strip() else {}
                    except Exception:
                        data = {}
            obj = data.get("object", {})
            name = obj.get("name") or title or object_id
            return f"✅ Objet Anytype mis à jour : **{name}** (`{object_id}`)"
        except Exception as exc:
            logger.error("anytype_update_error", error=str(exc))
            return f"❌ Erreur mise à jour Anytype : {exc}"

    async def list_objects(self, limit: int = 20) -> str:
        """List the most recent objects in the space, grouped by type."""
        if not self._available():
            return "⚠️ Anytype non configuré"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._objects_url(f"?limit={limit}"),
                    headers=self._headers(),
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur Anytype {resp.status}"
                    data = await resp.json()
            objects = data.get("data", [])
            if not objects:
                return "📭 Aucune note ou projet dans Anytype pour l'instant."
            by_type: dict[str, list] = {}
            for obj in objects:
                type_name = obj.get("type", {}).get("name") or "Autre"
                by_type.setdefault(type_name, []).append(obj)
            total = sum(len(v) for v in by_type.values())
            lines = [f"📚 **Anytype — {total} objet(s)**"]
            for type_name, items in by_type.items():
                lines.append(f"\n**{type_name}s**")
                for obj in items:
                    name = obj.get("name") or "Sans titre"
                    obj_id = obj.get("id", "?")
                    snippet = (obj.get("snippet") or "")[:80]
                    lines.append(f"• **{name}** — `{obj_id}`")
                    if snippet:
                        lines.append(f"  _{snippet}_")
            return "\n".join(lines)
        except Exception as exc:
            logger.error("anytype_list_error", error=str(exc))
            return f"❌ Erreur liste Anytype : {exc}"

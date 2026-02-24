"""Memory tool — LLM-accessible wrapper around AlitaDbManager."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..db.manager import AlitaDbManager

logger = structlog.get_logger()


class MemoryTool:
    """Exposes remember/recall/list/reminder operations to the LLM."""

    def __init__(self, db: "AlitaDbManager") -> None:
        self._db = db

    async def remember(self, key: str, value: str) -> str:
        try:
            await self._db.set_preference(key, value)
            return f"✅ Mémorisé : **{key}** = {value}"
        except Exception as exc:
            logger.error("memory_remember_error", key=key, error=str(exc))
            return f"❌ Erreur lors de la mémorisation : {exc}"

    async def recall(self, key: str) -> str:
        try:
            value = await self._db.get_preference(key)
            if value is None:
                return f"🤷 Aucune préférence trouvée pour **{key}**"
            return f"**{key}** : {value}"
        except Exception as exc:
            return f"❌ Erreur lors de la récupération : {exc}"

    async def list_preferences(self) -> str:
        try:
            prefs = await self._db.list_preferences()
            if not prefs:
                return "📭 Aucune préférence enregistrée."
            lines = ["📋 **Préférences enregistrées :**"]
            for k, v in prefs.items():
                lines.append(f"• **{k}** : {v}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur : {exc}"

    async def add_reminder(self, content: str, due_at: str | None = None) -> str:
        try:
            rid = await self._db.add_reminder(content, due_at)
            due_str = f" pour le {due_at}" if due_at else ""
            return f"✅ Rappel #{rid} créé{due_str} : {content}"
        except Exception as exc:
            return f"❌ Erreur création rappel : {exc}"

    async def get_reminders(self) -> str:
        try:
            reminders = await self._db.get_pending_reminders()
            if not reminders:
                return "📭 Aucun rappel en attente."
            lines = ["📌 **Rappels en attente :**"]
            for r in reminders:
                due = f" → {r['due_at']}" if r["due_at"] else ""
                lines.append(f"• #{r['id']}{due} : {r['content']}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur : {exc}"

    async def complete_reminder(self, reminder_id: int) -> str:
        try:
            ok = await self._db.complete_reminder(reminder_id)
            if ok:
                return f"✅ Rappel #{reminder_id} marqué comme terminé."
            return f"⚠️ Rappel #{reminder_id} introuvable."
        except Exception as exc:
            return f"❌ Erreur : {exc}"

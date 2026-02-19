"""Calendar tool — skeleton for future integration (Google Calendar, Nextcloud, etc.)."""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


class CalendarTool:
    """Fetch upcoming calendar events.

    TODO: implement with a real calendar backend
    (Google Calendar API, Nextcloud CalDAV, etc.).
    """

    async def get_today_events(self) -> str:
        """Return today's events."""
        return "📅 Calendrier non encore configuré. TODO: intégrer Google Calendar ou Nextcloud CalDAV."

    async def get_upcoming_events(self, days: int = 7) -> str:
        """Return events for the next *days* days."""
        return f"📅 Calendrier non encore configuré (prochains {days} jours)."

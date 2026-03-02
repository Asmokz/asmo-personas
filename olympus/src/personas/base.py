"""OlympusPersona — base class adapting APIEngine for the Olympus service."""
from __future__ import annotations

from asmo_commons.api.engine import APIEngine


class OlympusPersona(APIEngine):
    """Adapts APIEngine for Olympus — adds persona metadata."""

    PERSONA_ID: str = ""
    PERSONA_NAME: str = ""
    PERSONA_DESCRIPTION: str = ""
    PERSONA_COLOR: str = "#888888"

    @classmethod
    def get_info(cls) -> dict:
        return {
            "id": cls.PERSONA_ID,
            "name": cls.PERSONA_NAME,
            "description": cls.PERSONA_DESCRIPTION,
            "color": cls.PERSONA_COLOR,
            "avatar_url": f"/assets/personas/{cls.PERSONA_ID}.png",
        }

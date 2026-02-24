"""Home Assistant tool — REST API integration."""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()

HA_ALLOWED_DOMAINS = {
    "light", "switch", "scene", "climate",
    "input_boolean", "script", "automation",
}


class HomeAssistantTool:
    """Interact with Home Assistant via its REST API."""

    def __init__(self, ha_url: str, ha_token: Optional[str]) -> None:
        self._url = ha_url.rstrip("/")
        self._token = ha_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _available(self) -> bool:
        return bool(self._token)

    async def get_ha_states(self, domain: Optional[str] = None) -> str:
        """List entity states, optionally filtered by domain."""
        if not self._available():
            return "⚠️ Home Assistant non configuré (HA_TOKEN manquant)"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._url}/api/states",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur HA HTTP {resp.status}"
                    entities = await resp.json()

            if domain:
                entities = [e for e in entities if e["entity_id"].startswith(f"{domain}.")]

            if not entities:
                target = f"domaine '{domain}'" if domain else "Home Assistant"
                return f"📭 Aucune entité trouvée pour {target}"

            lines = [f"🏠 **Entités HA** ({len(entities)})"]
            for e in entities[:30]:
                eid = e["entity_id"]
                state = e["state"]
                friendly = e.get("attributes", {}).get("friendly_name", eid)
                lines.append(f"• **{friendly}** ({eid}) : {state}")
            if len(entities) > 30:
                lines.append(f"_... et {len(entities) - 30} de plus._")
            return "\n".join(lines)
        except Exception as exc:
            logger.error("ha_states_error", error=str(exc))
            return f"❌ Home Assistant indisponible : {exc}"

    async def get_ha_entity(self, entity_id: str) -> str:
        """Get detailed state for a specific entity."""
        if not self._available():
            return "⚠️ Home Assistant non configuré"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._url}/api/states/{entity_id}",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 404:
                        return f"❌ Entité '{entity_id}' introuvable"
                    if resp.status != 200:
                        return f"❌ Erreur HA HTTP {resp.status}"
                    data = await resp.json()
            state = data["state"]
            attrs = data.get("attributes", {})
            friendly = attrs.get("friendly_name", entity_id)
            lines = [f"🏠 **{friendly}** ({entity_id})", f"État : **{state}**"]
            for k, v in list(attrs.items())[:10]:
                if k != "friendly_name":
                    lines.append(f"  • {k} : {v}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur HA : {exc}"

    async def call_ha_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: Optional[dict] = None,
    ) -> str:
        """Call a HA service (turn_on, turn_off, toggle, etc.)."""
        if not self._available():
            return "⚠️ Home Assistant non configuré"
        if domain not in HA_ALLOWED_DOMAINS:
            allowed = ", ".join(sorted(HA_ALLOWED_DOMAINS))
            return f"❌ Domaine '{domain}' non autorisé. Domaines acceptés : {allowed}"
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/api/services/{domain}/{service}",
                    headers=self._headers(),
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status not in (200, 201):
                        return f"❌ Erreur HA HTTP {resp.status}"
            return f"✅ Service **{domain}.{service}** appelé sur **{entity_id}**"
        except Exception as exc:
            logger.error("ha_service_error", domain=domain, service=service, error=str(exc))
            return f"❌ Erreur appel service HA : {exc}"

    async def get_ha_sensors_summary(self) -> str:
        """Return a summary of key sensors (temperature, humidity, energy)."""
        if not self._available():
            return "⚠️ Home Assistant non configuré"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._url}/api/states",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur HA HTTP {resp.status}"
                    entities = await resp.json()

            sensors = [e for e in entities if e["entity_id"].startswith("sensor.")]
            keywords = {"temperature", "humidity", "energy", "power", "temp", "hum"}
            interesting = [
                s for s in sensors
                if any(kw in s["entity_id"].lower() for kw in keywords)
            ]

            if not interesting:
                return "📭 Aucun capteur température/humidité/énergie trouvé."

            lines = [f"🌡️ **Capteurs clés HA** ({len(interesting)})"]
            for s in interesting[:20]:
                friendly = s.get("attributes", {}).get("friendly_name", s["entity_id"])
                unit = s.get("attributes", {}).get("unit_of_measurement", "")
                state = s["state"]
                lines.append(f"• {friendly} : **{state}** {unit}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur capteurs HA : {exc}"

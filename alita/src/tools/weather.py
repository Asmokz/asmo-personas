"""Weather tool — OpenWeatherMap integration (skeleton)."""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()

OWM_BASE = "https://api.openweathermap.org/data/2.5"


class WeatherTool:
    """Fetch current weather and forecast via OpenWeatherMap API."""

    def __init__(self, api_key: Optional[str], default_city: str = "Paris") -> None:
        self._api_key = api_key
        self._default_city = default_city

    async def get_current_weather(self, city: Optional[str] = None) -> str:
        """Return current weather for *city* (falls back to default)."""
        if not self._api_key:
            return "⚠️ Clé API météo non configurée (ALITA_WEATHER_API_KEY)"

        target = city or self._default_city
        url = f"{OWM_BASE}/weather"
        params = {"q": target, "appid": self._api_key, "units": "metric", "lang": "fr"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur météo HTTP {resp.status}"
                    data = await resp.json()
            return _format_current(data, target)
        except Exception as exc:
            logger.error("weather_error", error=str(exc))
            return f"❌ Météo indisponible : {exc}"

    async def get_forecast(self, city: Optional[str] = None, days: int = 3) -> str:
        """Return a short forecast for *city*."""
        if not self._api_key:
            return "⚠️ Clé API météo non configurée"

        target = city or self._default_city
        url = f"{OWM_BASE}/forecast"
        params = {
            "q": target,
            "appid": self._api_key,
            "units": "metric",
            "lang": "fr",
            "cnt": days * 8,  # 8 slots per day (every 3h)
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return f"❌ Erreur prévisions HTTP {resp.status}"
                    data = await resp.json()
            return _format_forecast(data, target, days)
        except Exception as exc:
            return f"❌ Prévisions indisponibles : {exc}"


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_current(data: dict, city: str) -> str:
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    desc = data["weather"][0]["description"].capitalize()
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    return (
        f"🌤️ **Météo à {city}**\n"
        f"{desc} | {temp:.1f}°C (ressenti {feels:.1f}°C)\n"
        f"💧 Humidité : {humidity}% | 💨 Vent : {wind} m/s"
    )


def _format_forecast(data: dict, city: str, days: int) -> str:
    from datetime import datetime

    lines = [f"📅 **Prévisions {city} ({days}j)**"]
    seen_days: set[str] = set()

    for item in data.get("list", []):
        dt = datetime.fromtimestamp(item["dt"])
        day_str = dt.strftime("%A %d/%m")
        if day_str in seen_days:
            continue
        seen_days.add(day_str)
        temp_min = item["main"]["temp_min"]
        temp_max = item["main"]["temp_max"]
        desc = item["weather"][0]["description"].capitalize()
        lines.append(f"**{day_str}** : {desc}, {temp_min:.0f}–{temp_max:.0f}°C")
        if len(seen_days) >= days:
            break

    return "\n".join(lines)

"""Weather tool — OpenWeatherMap + moto riding score."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()

OWM_BASE = "https://api.openweathermap.org/data/2.5"


class WeatherTool:
    """Fetch weather via OpenWeatherMap and compute a moto riding score."""

    def __init__(self, api_key: Optional[str], default_city: str = "Marseille,FR") -> None:
        self._api_key = api_key
        self._default_city = default_city

    # ------------------------------------------------------------------
    # Public tool methods
    # ------------------------------------------------------------------

    async def get_current_weather(self, city: Optional[str] = None) -> str:
        if not self._api_key:
            return "⚠️ Clé API météo non configurée (ALITA_WEATHER_API_KEY)"
        target = city or self._default_city
        try:
            data = await self._fetch_current(target)
            return _format_current(data, target)
        except Exception as exc:
            logger.error("weather_current_error", city=target, error=str(exc))
            return f"❌ Météo indisponible : {exc}"

    async def get_forecast(self, city: Optional[str] = None, days: int = 3) -> str:
        if not self._api_key:
            return "⚠️ Clé API météo non configurée"
        target = city or self._default_city
        try:
            data = await self._fetch_forecast(target, days * 8)
            return _format_forecast(data, target, days)
        except Exception as exc:
            return f"❌ Prévisions indisponibles : {exc}"

    async def should_i_ride(self, city: Optional[str] = None) -> str:
        """Analyse si les conditions sont favorables à la moto (8h–19h)."""
        if not self._api_key:
            return "⚠️ Clé API météo non configurée"
        target = city or self._default_city
        try:
            forecast_data = await self._fetch_forecast(target, cnt=16)
            hourly = _parse_hourly(forecast_data)
            result = _compute_moto_score(hourly)
            return _format_moto_score(result)
        except Exception as exc:
            logger.error("moto_score_error", error=str(exc))
            return f"❌ Impossible de calculer le score moto : {exc}"

    async def get_hourly_raw(self, city: Optional[str] = None) -> list[dict]:
        """Return raw hourly slots (for briefing use)."""
        if not self._api_key:
            return []
        target = city or self._default_city
        try:
            data = await self._fetch_forecast(target, cnt=16)
            return _parse_hourly(data)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch_current(self, city: str) -> dict:
        params = {"q": city, "appid": self._api_key, "units": "metric", "lang": "fr"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OWM_BASE}/weather", params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                return await resp.json()

    async def _fetch_forecast(self, city: str, cnt: int = 24) -> dict:
        params = {
            "q": city, "appid": self._api_key, "units": "metric",
            "lang": "fr", "cnt": cnt,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OWM_BASE}/forecast", params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                return await resp.json()


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_current(data: dict, city: str) -> str:
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    desc = data["weather"][0]["description"].capitalize()
    humidity = data["main"]["humidity"]
    wind_kmh = data["wind"]["speed"] * 3.6
    rain_1h = data.get("rain", {}).get("1h", 0)
    rain_str = f" | 🌧️ {rain_1h:.1f} mm/h" if rain_1h > 0 else ""
    return (
        f"🌤️ **Météo à {city}**\n"
        f"{desc} | {temp:.1f}°C (ressenti {feels:.1f}°C)\n"
        f"💧 Humidité : {humidity}% | 💨 Vent : {wind_kmh:.0f} km/h{rain_str}"
    )


def _format_forecast(data: dict, city: str, days: int) -> str:
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
        pop = item.get("pop", 0) * 100
        pop_str = f" | 🌧️ {pop:.0f}%" if pop > 10 else ""
        lines.append(f"**{day_str}** : {desc}, {temp_min:.0f}–{temp_max:.0f}°C{pop_str}")
        if len(seen_days) >= days:
            break
    return "\n".join(lines)


def _parse_hourly(data: dict) -> list[dict]:
    slots = []
    for item in data.get("list", []):
        dt_txt = item.get("dt_txt", "")
        try:
            hour = datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S").hour if dt_txt else -1
        except ValueError:
            hour = -1
        slots.append({
            "hour": hour,
            "dt_txt": dt_txt,
            "temperature": item["main"]["temp"],
            "wind_kmh": item["wind"]["speed"] * 3.6,
            "pop": item.get("pop", 0),
            "rain_3h": item.get("rain", {}).get("3h", 0),
            "visibility": item.get("visibility", 10000),
        })
    return slots


def _compute_moto_score(hourly: list[dict]) -> dict:
    """Compute a moto riding score (0-10) based on 8h-19h worst conditions."""
    work_slots = [s for s in hourly if 8 <= s["hour"] <= 19]
    if not work_slots:
        work_slots = hourly

    pluie_max = max((s["rain_3h"] for s in work_slots), default=0)
    pop_max = max((s["pop"] for s in work_slots), default=0) * 100
    vent_max = max((s["wind_kmh"] for s in work_slots), default=0)
    temp_min = min((s["temperature"] for s in work_slots), default=20)
    temp_max = max((s["temperature"] for s in work_slots), default=20)
    visi_min = min((s["visibility"] for s in work_slots), default=10000)

    if pluie_max > 0.5 or pop_max > 40:
        reasons = []
        if pluie_max > 0.5:
            reasons.append(f"{pluie_max:.1f} mm")
        if pop_max > 40:
            reasons.append(f"{pop_max:.0f}% probabilité")
        return {
            "score": 0,
            "details": [f"☔ PLUIE prévue ({', '.join(reasons)}) — condition rédhibitoire"],
            "verdict": "🚫 NON — Conditions dangereuses",
        }

    score = 10
    details: list[str] = []

    if vent_max > 40:
        score -= 4
        details.append(f"💨 Vent très fort ({vent_max:.0f} km/h) : -4")
    elif vent_max > 25:
        score -= 2
        details.append(f"💨 Vent fort ({vent_max:.0f} km/h) : -2")

    if temp_min < 3:
        score -= 3
        details.append(f"🥶 Risque verglas ({temp_min:.0f}°C) : -3")
    elif temp_min < 8:
        score -= 1
        details.append(f"🥶 Froid ({temp_min:.0f}°C) : -1")

    if temp_max > 35:
        score -= 1
        details.append(f"🥵 Forte chaleur ({temp_max:.0f}°C) : -1")

    if visi_min < 1000:
        score -= 2
        details.append(f"🌫️ Brouillard (visibilité {visi_min}m) : -2")

    score = max(0, min(10, score))

    if score == 0:
        verdict = "🚫 NON — Conditions dangereuses"
    elif score <= 3:
        verdict = "⚠️ DÉCONSEILLÉ — Risques élevés"
    elif score <= 6:
        verdict = "🤔 MITIGÉ — À toi de voir"
    elif score <= 8:
        verdict = "✅ OK — Conditions correctes"
    else:
        verdict = "🌟 PARFAIT — Fonce !"

    if not details:
        details.append("✅ Aucune pénalité, conditions parfaites !")

    return {"score": score, "details": details, "verdict": verdict}


def _format_moto_score(result: dict) -> str:
    score = result["score"]
    verdict = result["verdict"]
    details = result["details"]
    bar = "🟩" * score + "⬜" * (10 - score)
    lines = [f"🏍️ **Score moto : {score}/10**", bar, f"**{verdict}**"]
    if details:
        lines.append("")
        lines.extend(f"  • {d}" for d in details)
    return "\n".join(lines)

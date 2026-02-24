"""Spotify tool — OAuth2 + playback control via spotipy."""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..db.manager import AlitaDbManager

logger = structlog.get_logger()

PREF_REFRESH_TOKEN = "spotify_refresh_token"
SPOTIFY_SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-recently-played"
)


class SpotifyTool:
    """Control Spotify playback. OAuth tokens stored in SQLite preferences."""

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        redirect_uri: str,
        db: "AlitaDbManager",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._db = db
        self._sp = None  # lazy-initialised after token obtained

    def _configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def get_auth_url(self) -> str:
        """Return the Spotify OAuth2 authorization URL."""
        if not self._configured():
            return "⚠️ Spotify non configuré (SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET manquants)"
        from spotipy.oauth2 import SpotifyOAuth
        auth = SpotifyOAuth(
            client_id=self._client_id,
            client_secret=self._client_secret,
            redirect_uri=self._redirect_uri,
            scope=SPOTIFY_SCOPE,
            open_browser=False,
        )
        return auth.get_authorize_url()

    async def handle_oauth_callback(self, code: str) -> str:
        """Exchange OAuth code for tokens and persist the refresh token."""
        if not self._configured():
            return "⚠️ Spotify non configuré"
        from spotipy.oauth2 import SpotifyOAuth
        try:
            auth = SpotifyOAuth(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=self._redirect_uri,
                scope=SPOTIFY_SCOPE,
            )
            token_info = auth.get_access_token(code, as_dict=True)
            refresh_token = token_info.get("refresh_token", "")
            if not refresh_token:
                return "❌ Pas de refresh_token dans la réponse Spotify"
            await self._db.set_preference(PREF_REFRESH_TOKEN, refresh_token)
            self._sp = None  # force re-init with new token
            logger.info("spotify_token_saved")
            return "✅ Spotify authentifié avec succès !"
        except Exception as exc:
            logger.error("spotify_oauth_error", error=str(exc))
            return f"❌ Erreur OAuth Spotify : {exc}"

    async def _get_client(self):
        """Return an authenticated spotipy client, refreshing token as needed."""
        if not self._configured():
            return None
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        if self._sp is not None:
            return self._sp
        refresh_token = await self._db.get_preference(PREF_REFRESH_TOKEN)
        if not refresh_token:
            return None
        auth = SpotifyOAuth(
            client_id=self._client_id,
            client_secret=self._client_secret,
            redirect_uri=self._redirect_uri,
            scope=SPOTIFY_SCOPE,
        )
        token_info = auth.refresh_access_token(refresh_token)
        self._sp = spotipy.Spotify(auth=token_info["access_token"])
        return self._sp

    def _not_connected_msg(self) -> str:
        return "⚠️ Spotify non connecté — utilise `!spotify-auth` pour t'authentifier"

    async def get_now_playing(self) -> str:
        sp = await self._get_client()
        if not sp:
            return self._not_connected_msg()
        try:
            playback = sp.current_playback()
            if not playback or not playback.get("is_playing"):
                return "⏸️ Rien en cours de lecture sur Spotify."
            item = playback.get("item", {})
            track = item.get("name", "?")
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            album = item.get("album", {}).get("name", "?")
            progress_ms = playback.get("progress_ms", 0)
            duration_ms = item.get("duration_ms", 1)
            pct = int(progress_ms / duration_ms * 100)
            return (
                f"🎵 **{track}**\n"
                f"👤 {artists} | 💿 {album}\n"
                f"⏱️ {_ms_to_min(progress_ms)} / {_ms_to_min(duration_ms)} ({pct}%)"
            )
        except Exception as exc:
            logger.error("spotify_now_playing_error", error=str(exc))
            return f"❌ Erreur Spotify : {exc}"

    async def control_playback(self, action: str) -> str:
        sp = await self._get_client()
        if not sp:
            return self._not_connected_msg()
        action = action.lower().strip()
        try:
            if action == "play":
                sp.start_playback()
            elif action == "pause":
                sp.pause_playback()
            elif action == "next":
                sp.next_track()
            elif action == "previous":
                sp.previous_track()
            else:
                return f"❌ Action inconnue : {action}. Valeurs valides : play, pause, next, previous"
            return f"✅ Spotify : **{action}** exécuté."
        except Exception as exc:
            return f"❌ Erreur contrôle Spotify : {exc}"

    async def search_spotify(self, query: str, search_type: str = "track") -> str:
        sp = await self._get_client()
        if not sp:
            return self._not_connected_msg()
        try:
            results = sp.search(q=query, type=search_type, limit=5)
            key = f"{search_type}s"
            items = results.get(key, {}).get("items", [])
            if not items:
                return f"📭 Aucun résultat pour « {query} »"
            lines = [f"🔍 **Spotify — {query}**"]
            for item in items:
                if search_type == "track":
                    artists = ", ".join(a["name"] for a in item.get("artists", []))
                    lines.append(f"• **{item['name']}** — {artists} (`{item['uri']}`)")
                else:
                    lines.append(f"• **{item['name']}** (`{item['uri']}`)")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur recherche Spotify : {exc}"

    async def get_recent_tracks(self, limit: int = 10) -> str:
        sp = await self._get_client()
        if not sp:
            return self._not_connected_msg()
        try:
            recent = sp.current_user_recently_played(limit=limit)
            items = recent.get("items", [])
            if not items:
                return "📭 Aucune écoute récente."
            lines = ["🕐 **Récemment écouté sur Spotify**"]
            for entry in items:
                track = entry["track"]
                artists = ", ".join(a["name"] for a in track.get("artists", []))
                lines.append(f"• **{track['name']}** — {artists}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ Erreur historique Spotify : {exc}"

    async def add_to_queue(self, track_uri: str) -> str:
        sp = await self._get_client()
        if not sp:
            return self._not_connected_msg()
        try:
            sp.add_to_queue(track_uri)
            return f"✅ Ajouté à la file : {track_uri}"
        except Exception as exc:
            return f"❌ Erreur ajout queue : {exc}"


def _ms_to_min(ms: int) -> str:
    secs = ms // 1000
    return f"{secs // 60}:{secs % 60:02d}"

"""Fetch and convert a URL's content to readable markdown.

Uses Jina.ai Reader (r.jina.ai) as primary method — it returns clean,
LLM-optimised markdown for any URL including GitHub repos, articles, docs.
Falls back to a direct HTTP GET + html2text conversion if Jina is unavailable.
"""
from __future__ import annotations

import aiohttp
import structlog

logger = structlog.get_logger()

_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_LEN = 4000
_JINA_BASE = "https://r.jina.ai/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlitaBot/1.0)"}
_JINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AlitaBot/1.0)",
    "Accept": "text/plain",
}


class FetchUrlTool:
    """HTTP fetch via Jina.ai Reader with direct-GET fallback."""

    async def fetch(self, url: str) -> str:
        # Primary: Jina.ai Reader — returns clean markdown for any URL
        result = await self._fetch_jina(url)
        if result:
            return result

        # Fallback: direct GET + html2text
        return await self._fetch_direct(url)

    async def _fetch_jina(self, url: str) -> str:
        """Fetch via https://r.jina.ai/{url} — returns clean markdown."""
        jina_url = f"{_JINA_BASE}{url}"
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.get(jina_url, headers=_JINA_HEADERS) as resp:
                    if resp.status != 200:
                        logger.debug("jina_fetch_failed", status=resp.status, url=url)
                        return ""
                    text = await resp.text(errors="replace")

            text = text.strip()
            if len(text) > _MAX_LEN:
                text = text[:_MAX_LEN] + "\n\n…[contenu tronqué]"

            logger.debug("fetch_url_jina_ok", url=url, content_len=len(text))
            return text

        except Exception as exc:
            logger.debug("jina_fetch_error", url=url, error=str(exc))
            return ""

    async def _fetch_direct(self, url: str) -> str:
        """Direct HTTP GET + html2text conversion."""
        try:
            import html2text

            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.get(url, headers=_HEADERS, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return f"❌ HTTP {resp.status} en accédant à {url}"
                    content_type = resp.headers.get("Content-Type", "")
                    raw = await resp.text(errors="replace")

            if "html" in content_type or raw.lstrip().startswith("<"):
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = True
                h.body_width = 0
                text = h.handle(raw)
            else:
                text = raw

            text = text.strip()
            if len(text) > _MAX_LEN:
                text = text[:_MAX_LEN] + "\n\n…[contenu tronqué]"

            logger.debug("fetch_url_direct_ok", url=url, content_len=len(text))
            return text

        except Exception as exc:
            logger.warning("fetch_url_failed", url=url, error=str(exc))
            return f"❌ Impossible de récupérer {url} : {exc}"

"""Fetch and convert a URL's content to readable text.

Used when the user shares a link (GitHub repo, doc, article…) and asks
Alita to read, summarize or analyse it.
"""
from __future__ import annotations

import aiohttp
import structlog

logger = structlog.get_logger()

_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_LEN = 4000
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlitaBot/1.0)"}


class FetchUrlTool:
    """HTTP fetch + HTML-to-markdown conversion."""

    async def fetch(self, url: str) -> str:
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

            logger.debug("fetch_url_ok", url=url, content_len=len(text))
            return text

        except Exception as exc:
            logger.warning("fetch_url_failed", url=url, error=str(exc))
            return f"❌ Impossible de récupérer {url} : {exc}"

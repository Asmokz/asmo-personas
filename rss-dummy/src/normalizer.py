import hashlib
from datetime import datetime, timezone

import structlog
from bs4 import BeautifulSoup

from .models import FeedItem

log = structlog.get_logger()


def _strip_html(text: str) -> str:
    plain = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return " ".join(plain.split())


def _extract_summary(entry) -> str:
    """Extract raw summary text using fallback chain."""
    raw = None

    if hasattr(entry, "content") and entry.content:
        c = entry.content[0]
        raw = c.get("value") if isinstance(c, dict) else getattr(c, "value", None)
    if not raw and hasattr(entry, "summary_detail") and entry.summary_detail:
        raw = entry.summary_detail.get("value")
    if not raw and hasattr(entry, "summary"):
        raw = entry.summary
    if not raw:
        raw = getattr(entry, "title", "")

    return raw or ""


def _make_guid(entry) -> str:
    key = entry.get("id") or entry.get("link") or getattr(entry, "title", "")
    return hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()


def _parse_published(entry) -> str:
    if entry.get("published_parsed"):
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    return datetime.now(timezone.utc).isoformat()


def normalize(feed_cfg: dict, entries: list, max_summary_chars: int) -> list[FeedItem]:
    items = []
    for entry in entries:
        try:
            raw_summary = _extract_summary(entry)
            plain = _strip_html(raw_summary).strip()
            summary = plain[:max_summary_chars] if len(plain) > max_summary_chars else plain

            item = FeedItem(
                guid=_make_guid(entry),
                title=_strip_html(getattr(entry, "title", "")).strip(),
                summary=summary,
                url=entry.get("link") or "",
                published_at=_parse_published(entry),
                source_name=feed_cfg["name"],
                tag=feed_cfg["tag"],
                targets=feed_cfg["targets"],
            )
            items.append(item)
        except Exception as e:
            log.warning("normalize_entry_error", feed=feed_cfg["name"], error=str(e))

    return items

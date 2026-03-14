import sys
import os
import time
import hashlib
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.normalizer import normalize, _strip_html, _make_guid, _parse_published
from src.models import FeedItem


def _entry(**kwargs) -> SimpleNamespace:
    """Build a minimal feedparser-like entry."""
    defaults = {
        "id": None,
        "link": "https://example.com/article",
        "title": "Test Title",
        "summary": "Test summary text.",
        "published_parsed": time.strptime("2025-03-14T10:00:00", "%Y-%m-%dT%H:%M:%S"),
        "content": None,
        "summary_detail": None,
    }
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    # Allow dict-style .get() on the namespace
    ns.get = lambda key, default=None: getattr(ns, key, default)
    return ns


FEED_CFG = {"name": "Test Feed", "tag": "ai", "targets": ["alita"]}


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_plain_text_unchanged(self):
        assert _strip_html("No HTML here.") == "No HTML here."

    def test_empty(self):
        assert _strip_html("") == ""

    def test_separator(self):
        result = _strip_html("<p>Para 1</p><p>Para 2</p>")
        assert "Para 1" in result and "Para 2" in result


class TestMakeGuid:
    def test_uses_id_field(self):
        entry = _entry(id="unique-id-123")
        guid = _make_guid(entry)
        assert guid == hashlib.sha1("unique-id-123".encode()).hexdigest()

    def test_falls_back_to_link(self):
        entry = _entry(id=None, link="https://example.com/art")
        guid = _make_guid(entry)
        assert guid == hashlib.sha1("https://example.com/art".encode()).hexdigest()

    def test_falls_back_to_title(self):
        entry = _entry(id=None, link=None, title="My Article")
        guid = _make_guid(entry)
        assert guid == hashlib.sha1("My Article".encode()).hexdigest()

    def test_deterministic(self):
        entry = _entry(id="same-id")
        assert _make_guid(entry) == _make_guid(entry)


class TestParsePublished:
    def test_parses_published_parsed(self):
        entry = _entry(published_parsed=time.strptime("2025-01-15T12:00:00", "%Y-%m-%dT%H:%M:%S"))
        result = _parse_published(entry)
        assert "2025-01-15" in result

    def test_falls_back_to_now(self):
        entry = _entry(published_parsed=None)
        result = _parse_published(entry)
        assert "2025" in result or "2026" in result  # reasonable year range


class TestNormalize:
    def test_returns_feed_items(self):
        entries = [_entry()]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        assert len(items) == 1
        assert isinstance(items[0], FeedItem)

    def test_summary_truncated(self):
        long_text = "A" * 600
        entries = [_entry(summary=long_text)]
        items = normalize(FEED_CFG, entries, max_summary_chars=100)
        assert len(items[0].summary) == 100

    def test_summary_not_over_truncated(self):
        short_text = "Short summary."
        entries = [_entry(summary=short_text)]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        assert items[0].summary == short_text

    def test_html_stripped_from_summary(self):
        entries = [_entry(summary="<p>Hello <b>world</b></p>")]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        assert "<" not in items[0].summary
        assert "Hello" in items[0].summary

    def test_metadata_mapped(self):
        entries = [_entry(link="https://example.com/x", title="My Title")]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        item = items[0]
        assert item.url == "https://example.com/x"
        assert item.title == "My Title"
        assert item.source_name == "Test Feed"
        assert item.tag == "ai"
        assert item.targets == ["alita"]

    def test_content_preferred_over_summary(self):
        content_ns = {"value": "<p>Full content</p>"}
        entries = [_entry(content=[content_ns], summary="Short summary")]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        assert "Full content" in items[0].summary

    def test_bad_entry_skipped(self):
        bad_entry = SimpleNamespace()  # missing everything
        bad_entry.get = lambda key, default=None: default
        entries = [bad_entry, _entry()]
        items = normalize(FEED_CFG, entries, max_summary_chars=500)
        # At least the valid entry normalizes correctly
        assert len(items) >= 1

    def test_empty_entries(self):
        items = normalize(FEED_CFG, [], max_summary_chars=500)
        assert items == []

    def test_multi_target(self):
        cfg = {"name": "Multi Feed", "tag": "homelab", "targets": ["alita", "femto"]}
        entries = [_entry()]
        items = normalize(cfg, entries, max_summary_chars=500)
        assert items[0].targets == ["alita", "femto"]

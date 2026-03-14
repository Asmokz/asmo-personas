import feedparser
import requests
import structlog
import yaml
from pathlib import Path

log = structlog.get_logger()

CONFIG_PATH = Path("/app/config/feeds.yml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_all(config: dict) -> list[tuple[dict, list]]:
    """Fetch all configured feeds sequentially.

    Returns a list of (feed_config, entries) tuples.
    Errors on individual feeds are logged and skipped.
    """
    timeout = config["settings"]["request_timeout_seconds"]
    results = []

    for feed_cfg in config["feeds"]:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": "rss-dummy/1.0"})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            entries = parsed.entries or []
            log.info("feed_fetched", feed=name, entries=len(entries))
            results.append((feed_cfg, entries))
        except requests.exceptions.Timeout:
            log.warning("feed_timeout", feed=name, url=url)
        except requests.exceptions.RequestException as e:
            log.warning("feed_fetch_error", feed=name, url=url, error=str(e))
        except Exception as e:
            log.error("feed_unexpected_error", feed=name, url=url, error=str(e))

    return results

from dataclasses import dataclass, field


@dataclass
class FeedItem:
    guid: str           # SHA1(url ou id natif du feed) — clé de dédup
    title: str
    summary: str        # texte brut, HTML strippé, tronqué à max_summary_chars
    url: str            # lien vers l'article original
    published_at: str   # ISO 8601
    source_name: str    # nom lisible du feed (ex: "Anthropic Blog")
    tag: str            # ai | news | linux | homelab
    targets: list[str] = field(default_factory=list)  # [alita] ou [femto] ou [alita, femto]

"""Core data structures shared across the pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Panel:
    """One horizontal strip in a card — a single series announcement."""
    title: str                       # e.g. "Attack on Titan"
    subtitle: str = ""               # e.g. the Japanese title "進撃の巨人"
    tag_main: str = "SEASON 1"       # left pill, e.g. "SEASON 4" / "MOVIE" / "NEW ARC"
    tag_sub: str = "NEW INFO"        # right pill, e.g. "NEW INFO" / "PRE-LAUNCH"
    date_text: str = ""              # big right-side date, e.g. "JULY 3"
    verb: str = ""                   # verb-forward hero word, e.g. "RETURNS" / "RETURNING"
    badges: list = field(default_factory=list)  # confidence chips, e.g. ["LEAK","UNCONFIRMED"]
    accent: str = ""                 # hex pill colour; "" -> theme/auto
    theme: str = "auto"              # background gradient theme when no art
    logo_style: str = "auto"         # auto | sans | serif | heavy
    query: str = ""                  # image search query; "" -> derived from title
    image_path: str = ""             # resolved local art file (filled by pipeline)
    image_url: str = ""              # optional explicit art URL (skips search)
    logo_path: str = ""              # transparent PNG logo to overlay instead of text
    logo_scale: float = 1.0          # multiplier on the auto-fit logo size
    focus_x: float = 0.6             # image pan X within the frame (0=left .. 1=right)
    focus_y: float = 0.4             # image pan Y (0=top .. 1=bottom)
    zoom: float = 1.0                # image zoom (1.0=fit the frame, >1 zooms in)

    def search_query(self) -> str:
        return (self.query or f"{self.title} anime key visual").strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Panel":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        out = {k: v for k, v in d.items() if k in allowed}
        b = out.get("badges")
        if isinstance(b, str):       # the UI sends a comma string -> a list
            out["badges"] = [x.strip() for x in re.split(r"[,/|]+", b) if x.strip()]
        return cls(**out)


@dataclass
class BrandConfig:
    """Account / event branding shown on every card."""
    event_name: str = ""        # right-side event wordmark; BLANK = don't show one
    event_badge: str = ""       # small badge before the wordmark, e.g. "AX"
    watermark: str = "ANIME INSIDER"
    accent: str = "#F5A623"
    default_tag_sub: str = "NEW INFO"


@dataclass
class CardSpec:
    """Global render settings for a batch of panels."""
    width: int = 1080
    height: int = 1350
    panels_per_card: int = 4
    divider: bool = True
    variant: str = "classic"         # classic | centered | banner
    style: object = None             # a styles.Style (None -> classic default)
    brand: BrandConfig = field(default_factory=BrandConfig)
    themes: dict = field(default_factory=dict)


@dataclass
class NewsPost:
    """A single-story news post (the IG/FB anime-news format)."""
    headline: str                    # the news statement (a sentence)
    body: str = ""                   # optional sub-text
    category: str = "NEWS"           # NEWS / BREAKING / RELEASE DATE / RANKING / TRAILER
    source: str = ""                 # source / handle, e.g. "@AnimeNews"
    date_text: str = ""              # short date
    accent: str = ""                 # hex; "" -> theme/auto
    theme: str = "auto"
    query: str = ""                  # image search query
    image_path: str = ""
    image_url: str = ""
    items: list = field(default_factory=list)   # for list / ranking posts
    focus_x: float = 0.5             # image pan X (0=left .. 1=right)
    focus_y: float = 0.4             # image pan Y (0=top .. 1=bottom)
    zoom: float = 1.0                # image zoom (1.0=fit, >1 zooms in)

    def search_query(self) -> str:
        return (self.query or f"{self.headline} anime key visual").strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NewsPost":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class RankEntry:
    """One row of a ranking list (rank + character/title + show + image)."""
    rank: int = 0
    name: str = ""
    source: str = ""                 # the show / sub-line
    image_path: str = ""
    image_url: str = ""
    query: str = ""
    focus_x: float = 0.5
    focus_y: float = 0.32            # bias the crop a little higher (faces sit up top)
    zoom: float = 1.0

    def search_query(self) -> str:
        return (self.query or f"{self.name} {self.source} anime").strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RankEntry":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class RankingList:
    """A ranked-list graphic (Top-N), Anime-Corner style."""
    title: str = "TOP 10"
    subtitle: str = ""
    entries: list = field(default_factory=list)   # list[RankEntry]
    accent: str = ""
    logo_path: str = ""              # optional header badge logo (favicon); "" -> text initials

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entries"] = [e.to_dict() if isinstance(e, RankEntry) else e for e in self.entries]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RankingList":
        entries = [RankEntry.from_dict(e) for e in d.get("entries", []) if isinstance(e, dict)]
        allowed = {f for f in cls.__dataclass_fields__} - {"entries"}  # type: ignore[attr-defined]
        base = {k: v for k, v in d.items() if k in allowed}
        return cls(entries=entries, **base)

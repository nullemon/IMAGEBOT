"""Core data structures shared across the pipeline."""
from __future__ import annotations

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
    accent: str = ""                 # hex pill colour; "" -> theme/auto
    theme: str = "auto"              # background gradient theme when no art
    logo_style: str = "auto"         # auto | sans | serif | heavy
    query: str = ""                  # image search query; "" -> derived from title
    image_path: str = ""             # resolved local art file (filled by pipeline)
    image_url: str = ""              # optional explicit art URL (skips search)
    logo_path: str = ""              # transparent PNG logo to overlay instead of text
    logo_scale: float = 1.0          # multiplier on the auto-fit logo size

    def search_query(self) -> str:
        return (self.query or f"{self.title} anime key visual").strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Panel":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class BrandConfig:
    """Account / event branding shown on every card."""
    event_name: str = "ANIME EXPO"
    event_badge: str = "AX"
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

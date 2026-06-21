"""Curated visual styles for the news cards.

A `Style` is a bag of knobs the compositor reads to render the same panels in a
very different look. `STYLE_PRESETS` is the gallery the user picks from.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Style:
    key: str
    name: str
    # ---- background -----------------------------------------------------
    bg: str = "art_full"        # art_full | art_cutout | art_blur_cutout | art_duotone | gradient | solid
    solid: str = ""             # hex for bg=solid (else theme)
    blur: int = 0               # blur radius for the background copy
    grayscale: bool = False
    duotone: tuple | None = None  # (dark_hex, light_hex) for bg=art_duotone
    # ---- scrims / tint --------------------------------------------------
    scrim_left: int = 215       # alpha at the left edge (logo/tag legibility)
    scrim_right: int = 150      # alpha at the right edge (behind the date)
    scrim_bottom: int = 0       # bottom gradient bar alpha
    darken: int = 38            # overall darken
    tint: str = ""              # accent/colour wash over the art (hex)
    tint_alpha: int = 60
    # ---- effects --------------------------------------------------------
    grain: float = 0.0          # 0..1 film grain
    vignette: float = 0.0       # 0..1 edge darkening
    glow: bool = False          # soft glow behind a cutout subject
    bars: int = 0               # cinematic letterbox bar height (px, full card)
    # ---- layout ---------------------------------------------------------
    # how the words are arranged:
    # classic | center | mirror | sidebar | bottombar | lowerthird | badge
    layout: str = "classic"
    logo_align: str = "left"    # (legacy, unused by the layout system)
    date_pos: str = "right"
    pill_pos: str = "under"
    # ---- type / colour --------------------------------------------------
    title_role: str = "auto"    # auto (use panel.logo_style) | sans | serif | heavy
    accent_mode: str = "theme"  # theme | series | fixed
    accent: str = ""            # hex for accent_mode=fixed
    pill_light: tuple = (245, 245, 248)  # secondary pill colour
    divider: tuple = (0, 0, 0, 220)


# ---------------------------------------------------------------------------
# 16 curated presets — deterministic, distinct, all production-ready.
# ---------------------------------------------------------------------------
STYLE_PRESETS: list[Style] = [
    Style("classic", "Classic Expo", layout="classic"),
    Style("spotlight", "Cutout Spotlight", layout="lowerthird", bg="art_cutout",
          darken=20, scrim_left=120, scrim_bottom=120, glow=True, vignette=0.3,
          accent_mode="series"),
    Style("blur_focus", "Soft Focus", layout="center", bg="art_blur_cutout",
          blur=18, scrim_bottom=140, vignette=0.3, accent_mode="series"),
    Style("duotone", "Duotone Punch", layout="mirror", bg="art_duotone",
          duotone=("#10121f", "#ff5b6e"), grain=0.10, accent="#ff5b6e",
          accent_mode="fixed", scrim_left=120, scrim_right=120),
    Style("neon", "Neon Night", layout="badge", darken=55, tint="#5b2bff",
          tint_alpha=55, glow=True, accent="#39e0ff", accent_mode="fixed",
          scrim_left=150, title_role="heavy"),
    Style("noir", "Noir", layout="sidebar", grayscale=True, darken=20,
          scrim_left=0, accent="#f5f5f5", accent_mode="fixed", title_role="serif",
          pill_light=(20, 20, 22), vignette=0.35),
    Style("magazine", "Magazine", layout="center", scrim_bottom=150,
          scrim_left=90, title_role="serif", accent_mode="series"),
    Style("cinematic", "Cinematic Bars", layout="bottombar", bars=46, darken=30,
          scrim_left=0, grain=0.06, accent_mode="theme"),
    Style("vaporwave", "Vaporwave", layout="badge", bg="art_duotone",
          duotone=("#241048", "#46f0d0"), tint="#ff39a8", tint_alpha=40,
          grain=0.12, accent="#ff39a8", accent_mode="fixed", scrim_left=150),
    Style("mono", "Minimal Mono", layout="lowerthird", darken=46, scrim_left=120,
          scrim_bottom=120, accent="#ffffff", accent_mode="fixed",
          pill_light=(20, 20, 22), title_role="sans"),
    Style("pop", "Comic Pop", layout="bottombar", accent="#ffd23f",
          accent_mode="fixed", title_role="heavy", scrim_left=0,
          divider=(0, 0, 0, 255)),
    Style("sunset", "Sunset", layout="mirror", tint="#ff7a3c", tint_alpha=70,
          scrim_left=110, scrim_right=110, accent="#ffd23f", accent_mode="fixed",
          title_role="serif"),
    Style("midnight", "Midnight", layout="sidebar", tint="#1d4ed8", tint_alpha=55,
          darken=30, scrim_left=0, accent="#7cc0ff", accent_mode="fixed"),
    Style("poster", "Poster Center", layout="center", scrim_bottom=170,
          title_role="heavy", accent_mode="series"),
    Style("grunge", "Grunge", layout="classic", grain=0.16, vignette=0.42,
          darken=46, title_role="heavy", accent="#e23b4e", accent_mode="fixed",
          scrim_left=180),
    Style("festival", "Festival", layout="bottombar", accent_mode="series",
          scrim_left=0, title_role="sans"),
    # --- extra looks that lean into the distinct layouts ---
    Style("editorial", "Editorial", layout="sidebar", scrim_left=0,
          title_role="serif", accent_mode="series"),
    Style("headline", "Headline", layout="bottombar", scrim_left=0,
          title_role="heavy", accent="#ff4d5e", accent_mode="fixed"),
    Style("sticker", "Sticker", layout="badge", scrim_left=160,
          accent="#19c37d", accent_mode="fixed", title_role="heavy"),
    Style("split", "Split", layout="mirror", bg="art_duotone",
          duotone=("#101225", "#ffb020"), scrim_left=120, scrim_right=120,
          accent="#ffb020", accent_mode="fixed"),
    # --- new layouts ---
    Style("stamp", "Date Stamp", layout="medallion", darken=42,
          accent_mode="series", scrim_left=0),
    Style("vertical", "Vertical", layout="vertical", scrim_left=170,
          accent="#39e0ff", accent_mode="fixed", title_role="heavy"),
    Style("ticket", "Ticket", layout="ticket", scrim_left=150,
          accent="#f5a623", accent_mode="fixed"),
    Style("ribbon", "Ribbon", layout="ribbon", darken=30, scrim_bottom=120,
          accent="#e23b4e", accent_mode="fixed", title_role="heavy"),
    Style("diagonal", "Diagonal", layout="diagonal", scrim_left=0,
          accent_mode="series"),
    Style("halfsplit", "Half Split", layout="halfsplit", scrim_left=0,
          title_role="serif", accent_mode="series"),
]

_BY_KEY = {s.key: s for s in STYLE_PRESETS}
DEFAULT_STYLE = STYLE_PRESETS[0]


def get_style(key: str | None) -> Style:
    return _BY_KEY.get((key or "").lower(), DEFAULT_STYLE)


def all_styles() -> list[Style]:
    return list(STYLE_PRESETS)

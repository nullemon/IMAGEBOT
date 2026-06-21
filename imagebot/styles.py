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
    logo_align: str = "left"    # left | center
    date_pos: str = "right"     # right | bottom | corner | none
    pill_pos: str = "under"     # under | top
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
    Style("classic", "Classic Expo"),
    Style("spotlight", "Cutout Spotlight", bg="art_cutout", darken=20,
          scrim_left=120, glow=True, vignette=0.35, accent_mode="series"),
    Style("blur_focus", "Soft Focus", bg="art_blur_cutout", blur=18,
          scrim_left=120, vignette=0.3, accent_mode="series"),
    Style("duotone", "Duotone Punch", bg="art_duotone", duotone=("#10121f", "#ff5b6e"),
          grain=0.10, accent="#ff5b6e", accent_mode="fixed", scrim_left=160),
    Style("neon", "Neon Night", darken=55, tint="#5b2bff", tint_alpha=55,
          glow=True, accent="#39e0ff", accent_mode="fixed", scrim_bottom=120,
          title_role="heavy"),
    Style("noir", "Noir", grayscale=True, darken=46, scrim_left=200,
          accent="#f5f5f5", accent_mode="fixed", title_role="serif",
          pill_light=(20, 20, 22), vignette=0.4),
    Style("magazine", "Magazine", logo_align="center", date_pos="bottom",
          pill_pos="top", scrim_bottom=150, scrim_left=90, title_role="serif",
          accent_mode="series"),
    Style("cinematic", "Cinematic Bars", bars=46, darken=42, scrim_left=140,
          logo_align="center", grain=0.06, accent_mode="theme"),
    Style("vaporwave", "Vaporwave", bg="art_duotone", duotone=("#241048", "#46f0d0"),
          tint="#ff39a8", tint_alpha=40, grain=0.12, accent="#ff39a8",
          accent_mode="fixed", scrim_left=150),
    Style("mono", "Minimal Mono", darken=58, scrim_left=120, date_pos="corner",
          accent="#ffffff", accent_mode="fixed", pill_light=(20, 20, 22),
          title_role="sans"),
    Style("pop", "Comic Pop", accent="#ffd23f", accent_mode="fixed",
          title_role="heavy", scrim_left=170, divider=(0, 0, 0, 255)),
    Style("sunset", "Sunset", tint="#ff7a3c", tint_alpha=70, scrim_bottom=120,
          accent="#ffd23f", accent_mode="fixed", title_role="serif"),
    Style("midnight", "Midnight", tint="#1d4ed8", tint_alpha=55, darken=46,
          scrim_bottom=110, accent="#7cc0ff", accent_mode="fixed"),
    Style("poster", "Poster Center", logo_align="center", date_pos="bottom",
          pill_pos="top", scrim_bottom=170, title_role="heavy",
          accent_mode="series"),
    Style("grunge", "Grunge", grain=0.16, vignette=0.42, darken=46,
          title_role="heavy", accent="#e23b4e", accent_mode="fixed",
          scrim_left=180),
    Style("festival", "Festival", accent_mode="series", scrim_bottom=140,
          date_pos="bottom", pill_pos="top", tint="", title_role="sans"),
]

_BY_KEY = {s.key: s for s in STYLE_PRESETS}
DEFAULT_STYLE = STYLE_PRESETS[0]


def get_style(key: str | None) -> Style:
    return _BY_KEY.get((key or "").lower(), DEFAULT_STYLE)


def all_styles() -> list[Style]:
    return list(STYLE_PRESETS)

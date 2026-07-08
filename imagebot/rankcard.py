"""Ranked-list graphics (Top-N) — the Anime-Corner style leaderboard card.

A header band (brand + "TOP 10 ..." title + subtitle) over N rows; each row =
a coloured rank block + the character/show image + a name panel (bold name +
the show it's from). One renderer, several colour themes (the red Anime-Corner
look, dark, minimal, magazine, neon, gradient) so the same list can be
re-skinned instantly — exactly like the line-up / news modes.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .fonts import FontBook
from .models import RankingList, RankEntry, CardSpec
from .compositor import (WHITE, NEAR_BLACK, hex_to_rgb, vertical_gradient,
                         cover_resize, draw_text, readable_text_color,
                         apply_vignette)


# --------------------------------------------------------------------------
# themes — a template is just a bag of colours + treatment knobs fed to the
# single renderer below. "accent" as a value means "use the resolved accent".
# --------------------------------------------------------------------------
def _T(**kw):
    base = dict(
        page=("solid", "#ffffff"),     # ("solid",hex) | ("gradient",top,bottom)
        header_split=True,             # corner-style two-tone header (brand block + title)
        brand_block="#e0152b",         # left brand block colour (header_split)
        header_bg="#17171d",           # header background (right side / full width)
        title_color="#ffffff",
        subtitle_color="#f4a9b0",
        brand_color="#ffffff",
        accent="#e0152b",              # default accent (overridable per list)
        rank_top="#e0152b",            # rank block colour, ranks 1-3
        rank_rest="#f4a9b0",           # rank block colour, ranks 4+
        rank_shape="block",            # block | chip | plain
        rank_text="#ffffff",           # "accent"/"auto" allowed
        row_bg="#ffffff",              # name-panel background (None -> transparent)
        row_bg_alpha=255,
        row_alt=None,                  # alternate-row background (None -> none)
        name_color="#e0152b",          # "accent" allowed
        source_color="#5a5a64",
        name_role="ui",                # ui | logo_serif | logo_heavy
        divider=None,                  # hairline colour between rows, or None
        img_border=None,               # thin border around each thumbnail, or None
        vignette=0.0,
    )
    base.update(kw)
    return base


RANK_THEMES = {
    # the reference look: red brand block, dark title bar, red/pink rank blocks,
    # white name panels with red names.
    "corner": _T(),
    "dark": _T(page=("solid", "#0d0e13"), header_split=False, header_bg="#13141c",
               subtitle_color="#8a90a6", brand_color="#ffffff", accent="#ff3b5c",
               rank_top="accent", rank_rest="#262a39", rank_text="#ffffff",
               row_bg="#171a26", row_bg_alpha=255, row_alt="#1c2030",
               name_color="#ffffff", source_color="#99a1b8", divider=None),
    "minimal": _T(page=("solid", "#ffffff"), header_split=False, header_bg="#ffffff",
                  title_color="#121212", subtitle_color="#6b6b6b", brand_color="#121212",
                  accent="#e0152b", rank_shape="plain", rank_top="accent",
                  rank_rest="#c2c4cc", rank_text="accent", row_bg=None,
                  name_color="#121212", source_color="#6b6b6b", divider="#ececf0"),
    "gradient": _T(page=("gradient", "#180f2e", "#3a1c5c"), header_split=False,
                   header_bg=None, title_color="#ffffff", subtitle_color="#d9c6ff",
                   brand_color="#ffffff", accent="#b07cff", rank_shape="chip",
                   rank_top="accent", rank_rest="#5a3f86", rank_text="#ffffff",
                   row_bg="#000000", row_bg_alpha=70, name_color="#ffffff",
                   source_color="#cdbcec", divider=None),
    "magazine": _T(page=("solid", "#f4f1ea"), header_split=False, header_bg="#f4f1ea",
                   title_color="#1a1a1a", subtitle_color="#7a5c22", brand_color="#1a1a1a",
                   accent="#b8862a", rank_shape="plain", rank_top="accent",
                   rank_rest="#b3a587", rank_text="accent", name_role="logo_serif",
                   row_bg=None, name_color="#1a1a1a", source_color="#6a5a3a",
                   divider="#dcd4c3", img_border="#1a1a1a"),
    "neon": _T(page=("solid", "#07070c"), header_split=False, header_bg="#07070c",
               title_color="#ffffff", subtitle_color="#37e6c2", brand_color="#37e6c2",
               accent="#00e6c0", rank_shape="chip", rank_top="accent",
               rank_rest="#14313a", rank_text="#07070c", row_bg="#0f131c",
               row_alt="#0b0e15", name_color="#ffffff", source_color="#37e6c2",
               divider=None, vignette=0.4, img_border="#00e6c0"),
}

RANK_TEMPLATES = [
    ("corner", "Anime Corner"),
    ("dark", "Dark Mode"),
    ("minimal", "Minimal"),
    ("gradient", "Gradient"),
    ("magazine", "Magazine"),
    ("neon", "Neon"),
]
_RANK_BY_KEY = dict(RANK_TEMPLATES)
DEFAULT_RANK = RANK_TEMPLATES[0][0]


def rank_templates() -> list[dict]:
    return [{"key": k, "name": n} for k, n in RANK_TEMPLATES]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _col(value, accent):
    """Resolve a theme colour value to an RGB tuple (or None)."""
    if value is None:
        return None
    if value == "accent" or value == "auto":
        return accent
    return hex_to_rgb(value)


def _initials(text: str) -> str:
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _measure(draw, text, font):
    if not text:
        return (0, 0)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return (r - l, b - t)


def _draw_in(draw, box, text, font, fill, align="left", valign="center", shadow=False):
    """Draw a single line inside a box (x0,y0,x1,y1)."""
    if not text:
        return
    x0, y0, x1, y1 = box
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    if align == "center":
        x = x0 + (x1 - x0 - tw) // 2
    elif align == "right":
        x = x1 - tw
    else:
        x = x0
    if valign == "center":
        y = y0 + (y1 - y0 - th) // 2
    elif valign == "bottom":
        y = y1 - th
    else:
        y = y0
    draw_text(draw, (x - l, y - t), text, font, fill, shadow=shadow)


def _open(entry: RankEntry):
    if entry.image_path and Path(entry.image_path).exists():
        try:
            return Image.open(entry.image_path).convert("RGB")
        except Exception:
            return None
    return None


def _thumb(entry: RankEntry, w: int, h: int, accent, fonts: FontBook) -> Image.Image:
    """Cover-cropped thumbnail honouring focus/zoom, or an accent placeholder."""
    art = _open(entry)
    if art is not None:
        return cover_resize(art, w, h, entry.focus_x, entry.focus_y, entry.zoom)
    # placeholder: soft accent gradient + the name's initial
    a = accent
    dark = tuple(max(0, int(c * 0.45)) for c in a)
    base = vertical_gradient(w, h, a, dark)
    d = ImageDraw.Draw(base)
    ini = _initials(entry.name or entry.source)
    f = fonts.font("logo_heavy", int(h * 0.5))
    _draw_in(d, (0, 0, w, h), ini, f, readable_text_color(a), "center", "center")
    return base


def _background(W, H, theme, accent) -> Image.Image:
    kind = theme["page"]
    if kind[0] == "gradient":
        return vertical_gradient(W, H, hex_to_rgb(kind[1]), hex_to_rgb(kind[2]))
    return Image.new("RGBA", (W, H), hex_to_rgb(kind[1]) + (255,))


def _circle_logo(logo_path: str, d: int):
    """Load a logo and mask it into a clean circle of diameter d, or None."""
    if not (logo_path and Path(logo_path).exists()):
        return None
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return None
    # cover-fit the logo into a d x d square, then circular-mask it
    iw, ih = logo.size
    scale = max(d / iw, d / ih)
    logo = logo.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
    left, top = (logo.width - d) // 2, (logo.height - d) // 2
    logo = logo.crop((left, top, left + d, top + d))
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(logo, (0, 0), mask)
    return out


def _brand_badge(base, draw, x, cy, r, ring, fg, initials, font, logo_path=""):
    """A clean circular brand mark: an uploaded logo (favicon) if given,
    otherwise a filled disc with centred initials. Always perfectly round."""
    d = 2 * r
    logo = _circle_logo(logo_path, d)
    if logo is not None:
        base.alpha_composite(logo, (x, cy - r))
        draw.ellipse([x, cy - r, x + d, cy + r], outline=ring, width=max(2, r // 10))
        return
    draw.ellipse([x, cy - r, x + d, cy + r], fill=fg, outline=ring, width=max(2, r // 11))
    _draw_in(draw, (x, cy - r, x + d, cy + r), initials, font, ring, "center", "center")


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------
def _draw_header(base, draw, rl, theme, accent, fonts, W, header_h, brand_text, logo_path=""):
    pad = int(W * 0.03)
    title = (rl.title or "TOP 10").upper()
    subtitle = (rl.subtitle or "").upper()
    brand_text = (brand_text or "").upper()
    cy = header_h // 2

    if theme["header_split"]:
        bw = int(W * 0.31)
        block = _col(theme["brand_block"], accent)
        hb = _col(theme["header_bg"], accent)
        draw.rectangle([0, 0, bw, header_h], fill=block)
        if hb is not None:
            draw.rectangle([bw, 0, W, header_h], fill=hb)
        # brand: circle badge + wordmark, vertically centred in the block
        bfg = readable_text_color(block)
        r = int(header_h * 0.27)
        bx = pad
        _brand_badge(base, draw, bx, cy, r, bfg, block,
                     _initials(brand_text), fonts.font("logo_heavy", int(r * 0.85)),
                     logo_path=logo_path)
        name_x = bx + 2 * r + int(W * 0.02)
        nf = fonts.fit(draw, brand_text, "ui", bw - name_x - pad,
                       int(header_h * 0.32), start=int(header_h * 0.3))
        _draw_in(draw, (name_x, 0, bw - pad, header_h), brand_text, nf, bfg, "left", "center")
        tx0 = bw + pad
        tfg = _col(theme["title_color"], accent)
        sfg = _col(theme["subtitle_color"], accent)
        if subtitle:
            tf = fonts.fit(draw, title, "date", W - tx0 - pad, int(header_h * 0.46),
                           start=int(header_h * 0.5))
            _draw_in(draw, (tx0, int(header_h * 0.15), W - pad, int(header_h * 0.6)),
                     title, tf, tfg, "left", "center")
            sf = fonts.fit(draw, subtitle, "ui", W - tx0 - pad, int(header_h * 0.18),
                           start=int(header_h * 0.18))
            _draw_in(draw, (tx0, int(header_h * 0.63), W - pad, header_h - int(header_h * 0.1)),
                     subtitle, sf, sfg, "left", "center")
        else:
            tf = fonts.fit(draw, title, "date", W - tx0 - pad, int(header_h * 0.58),
                           start=int(header_h * 0.62))
            _draw_in(draw, (tx0, 0, W - pad, header_h), title, tf, tfg, "left", "center")
        return

    # full-width header: circular brand badge + wordmark on the left, big title,
    # subtitle. The title is right-of / below the brand depending on room.
    hb = _col(theme["header_bg"], accent)
    if hb is not None:
        draw.rectangle([0, 0, W, header_h], fill=hb)
    bfg = _col(theme["brand_color"], accent)
    tfg = _col(theme["title_color"], accent)
    sfg = _col(theme["subtitle_color"], accent)

    # brand mark, top band
    r = int(header_h * 0.16)
    by = int(header_h * 0.1) + r
    _brand_badge(base, draw, pad, by, r, accent,
                 hb or hex_to_rgb(theme["accent"]), _initials(brand_text),
                 fonts.font("logo_heavy", int(r * 0.85)), logo_path=logo_path)
    brf = fonts.font("ui", max(13, int(r * 1.05)))
    _draw_in(draw, (pad + 2 * r + int(W * 0.015), by - r, W - pad, by + r),
             brand_text, brf, bfg, "left", "center")
    # title (big), centred in the lower portion
    ty0 = int(header_h * 0.42)
    if subtitle:
        tf = fonts.fit(draw, title, "date", W - 2 * pad, int(header_h * 0.34),
                       start=int(header_h * 0.4))
        _draw_in(draw, (pad, ty0, W - pad, int(header_h * 0.78)), title, tf, tfg, "left", "center")
        sf = fonts.font("ui", max(12, int(header_h * 0.1)))
        _draw_in(draw, (pad, int(header_h * 0.8), W - pad, header_h - int(header_h * 0.03)),
                 subtitle, sf, sfg, "left", "center")
    else:
        tf = fonts.fit(draw, title, "date", W - 2 * pad, int(header_h * 0.44),
                       start=int(header_h * 0.5))
        _draw_in(draw, (pad, ty0, W - pad, header_h - int(header_h * 0.08)),
                 title, tf, tfg, "left", "center")


# --------------------------------------------------------------------------
# a single row
# --------------------------------------------------------------------------
def _draw_row(base, draw, entry, rank, theme, accent, fonts, W, y0, row_h, idx):
    g = max(2, int(row_h * 0.07))
    iy0, iy1 = y0 + g // 2, y0 + row_h - (g + 1) // 2
    ih = iy1 - iy0
    rank_w = int(W * 0.135)
    img_w = int(W * 0.255)

    # alternate-row wash (drawn full width behind everything)
    alt = _col(theme["row_alt"], accent)
    if alt is not None and idx % 2 == 1:
        draw.rectangle([0, y0, W, y0 + row_h], fill=alt)

    # ---- rank block ----
    rcol = _col(theme["rank_top"] if rank <= 3 else theme["rank_rest"], accent)
    if theme["rank_text"] == "auto":         # per-block contrast, not accent
        rtext = readable_text_color(rcol) if rcol is not None else WHITE
    else:
        rtext = _col(theme["rank_text"], accent)
    shape = theme["rank_shape"]
    rbox = (0, iy0, rank_w, iy1)
    if shape == "block" and rcol is not None:
        draw.rectangle([0, iy0, rank_w, iy1], fill=rcol)
    elif shape == "chip" and rcol is not None:
        cw = int(rank_w * 0.74)
        cx = (rank_w - cw) // 2
        ch = int(ih * 0.82)
        cyy = iy0 + (ih - ch) // 2
        draw.rounded_rectangle([cx, cyy, cx + cw, cyy + ch], radius=int(ch * 0.26), fill=rcol)
        rbox = (cx, cyy, cx + cw, cyy + ch)
    nf = fonts.fit(draw, str(rank), "date", int(rank_w * 0.8), int(ih * 0.74),
                   start=int(ih * 0.8))
    _draw_in(draw, rbox, str(rank), nf, rtext, "center", "center")

    # ---- thumbnail ----
    ix0 = rank_w
    thumb = _thumb(entry, img_w, ih, accent, fonts)
    base.alpha_composite(thumb.convert("RGBA"), (ix0, iy0))
    border = _col(theme["img_border"], accent)
    if border is not None:
        draw.rectangle([ix0, iy0, ix0 + img_w - 1, iy1 - 1], outline=border, width=2)

    # ---- name panel ----
    px0 = ix0 + img_w
    rb = _col(theme["row_bg"], accent)
    if rb is not None:
        a = theme["row_bg_alpha"]
        if a >= 255:
            draw.rectangle([px0, iy0, W, iy1], fill=rb)
        else:
            base.alpha_composite(Image.new("RGBA", (W - px0, ih), rb + (a,)), (px0, iy0))

    tx0 = px0 + int(W * 0.022)
    tmax = W - tx0 - int(W * 0.022)
    name = (entry.name or "").strip() or "—"
    source = (entry.source or "").strip()
    name_col = _col(theme["name_color"], accent)
    src_col = _col(theme["source_color"], accent)

    if source:
        nf2 = fonts.fit(draw, name, theme["name_role"], tmax, int(ih * 0.46),
                        start=int(ih * 0.5))
        sf2 = fonts.fit(draw, source, "ui_regular", tmax, int(ih * 0.24),
                        start=int(ih * 0.26))
        nh = _measure(draw, name, nf2)[1]
        sh = _measure(draw, source, sf2)[1]
        gap = int(ih * 0.1)
        total = nh + gap + sh
        ty = iy0 + (ih - total) // 2
        _draw_in(draw, (tx0, ty, W, ty + nh), name, nf2, name_col, "left", "top")
        _draw_in(draw, (tx0, ty + nh + gap, W, ty + nh + gap + sh), source, sf2, src_col, "left", "top")
    else:
        nf2 = fonts.fit(draw, name, theme["name_role"], tmax, int(ih * 0.6),
                        start=int(ih * 0.62))
        _draw_in(draw, (tx0, iy0, W, iy1), name, nf2, name_col, "left", "center")

    # ---- divider ----
    dv = _col(theme["divider"], accent)
    if dv is not None and idx > 0:
        draw.line([(0, y0), (W, y0)], fill=dv, width=1)


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def _header_h(width: int, height: int) -> int:
    return int(min(max(height * 0.11, 128), height * 0.17))


def rank_capacity(width: int, height: int, n_entries: int) -> int:
    """How many rows actually render at this size: the comfortable cap, relaxed
    toward a hard legibility floor when the list explicitly has more entries."""
    hh = _header_h(width, height)
    pref = max(46, int(height * 0.045), int(width * 0.065))   # aspect-aware floor
    cap_pref = max(1, (height - hh) // pref)
    if n_entries <= cap_pref:
        return cap_pref
    hard = max(1, (height - hh) // max(40, int(height * 0.038)))
    return min(n_entries, hard) if hard > cap_pref else cap_pref


def render_ranking(rl: RankingList, template_key: str, spec: CardSpec,
                   fonts: FontBook | None = None) -> Image.Image:
    fonts = fonts or FontBook()
    W, H = spec.width, spec.height
    theme = RANK_THEMES.get(template_key, RANK_THEMES[DEFAULT_RANK])
    accent = hex_to_rgb(rl.accent) if rl.accent else hex_to_rgb(theme["accent"])
    brand_text = (spec.brand.watermark or "ANIME LIST").strip()

    header_h = _header_h(W, H)
    entries = list(rl.entries)[:rank_capacity(W, H, len(rl.entries))]
    n = max(1, len(entries))

    base = _background(W, H, theme, accent)
    draw = ImageDraw.Draw(base)

    rows_top = header_h
    avail = H - rows_top
    row_h = avail // n
    for i, entry in enumerate(entries):
        try:
            rank = int(float(entry.rank)) or (i + 1)
        except (TypeError, ValueError):
            rank = i + 1
        y0 = rows_top + i * row_h
        rh = (H - y0) if i == n - 1 else row_h
        _draw_row(base, draw, entry, rank, theme, accent, fonts, W, y0, rh, i)

    _draw_header(base, draw, rl, theme, accent, fonts, W, header_h, brand_text,
                 logo_path=getattr(rl, "logo_path", ""))

    if theme["vignette"]:
        apply_vignette(base, theme["vignette"])
    return base


def save_ranking(card: Image.Image, out_dir: str, prefix: str = "ranking") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{prefix}.png"
    card.convert("RGB").save(p, "PNG")
    return [str(p)]

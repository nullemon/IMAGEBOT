"""Single-story "news post" cards — the IG/FB anime-news format.

16 templates: a key visual + a wrapped headline + category badge + source/date,
the way popular anime-news pages post breaking news, release dates, rankings,
quotes, etc. Reuses the compositor's primitives; adds headline word-wrapping.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .fonts import FontBook
from .models import NewsPost, CardSpec
from .compositor import (WHITE, NEAR_BLACK, hex_to_rgb, vertical_gradient,
                         cover_resize, _alpha_scrim, _vertical_alpha, draw_text,
                         draw_pill, readable_text_color, vibrant_color,
                         apply_vignette, apply_grain)


# --------------------------------------------------------------------------
class NewsCtx:
    __slots__ = ("draw", "base", "post", "fonts", "accent", "brand", "W", "H", "ml")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ---- text wrapping --------------------------------------------------------
def wrap_lines(draw, text, font, max_w):
    out, cur = [], ""
    for word in (text or "").split():
        t = (cur + " " + word).strip()
        if not cur or draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def fit_wrapped(ctx, text, role, max_w, max_h, max_lines, start, minimum=24, gap=1.06):
    size = start
    while size >= minimum:
        f = ctx.fonts.font(role, size)
        lines = wrap_lines(ctx.draw, text, f, max_w)
        l, t, r, b = f.getbbox("Ay")
        lh = int((b - t) * gap)
        if len(lines) <= max_lines and lh * len(lines) <= max_h:
            return f, lines, lh
        size -= 3
    f = ctx.fonts.font(role, minimum)
    lines = wrap_lines(ctx.draw, text, f, max_w)[:max_lines]
    l, t, r, b = f.getbbox("Ay")
    return f, lines, int((b - t) * gap)


def draw_wrapped(ctx, lines, x, y, font, lh, fill, align="left", anchor=None, shadow=True):
    for i, line in enumerate(lines):
        if align == "center":
            lx = (anchor if anchor is not None else ctx.W // 2) - ctx.draw.textlength(line, font=font) / 2
        elif align == "right":
            lx = (anchor if anchor is not None else ctx.W - ctx.ml) - ctx.draw.textlength(line, font=font)
        else:
            lx = x
        draw_text(ctx.draw, (int(lx), y + i * lh), line, font, fill, shadow=shadow)
    return y + len(lines) * lh


# ---- shared furniture -----------------------------------------------------
def _scrim_bottom(ctx, frac=0.6, a=235):
    h = int(ctx.H * frac)
    ctx.base.alpha_composite(_vertical_alpha(ctx.W, h, (0, 0, 0), 0, a), (0, ctx.H - h))


def _scrim_top(ctx, frac=0.5, a=210):
    h = int(ctx.H * frac)
    ctx.base.alpha_composite(_vertical_alpha(ctx.W, h, (0, 0, 0), a, 0))


def _darken(ctx, a):
    ctx.base.alpha_composite(Image.new("RGBA", (ctx.W, ctx.H), (0, 0, 0, a)))


def _category(ctx, x, y, align="left", text=None, bg=None):
    txt = (text or ctx.post.category or "NEWS").upper()
    bg = bg or ctx.accent
    f = ctx.fonts.font("ui", int(ctx.W * 0.032))
    tw = ctx.draw.textlength(txt, font=f)
    padx, pady = int(ctx.W * 0.022), int(ctx.W * 0.016)
    rw = int(tw) + 2 * padx
    bx = {"center": x - rw // 2, "right": x - rw}.get(align, x)
    draw_pill(ctx.draw, (bx, y), txt, f, bg, readable_text_color(bg),
              pad_x=padx, pad_y=pady, radius=int(ctx.W * 0.01))
    l, t, r, b = ctx.draw.textbbox((0, 0), txt, font=f)
    return rw, (b - t) + 2 * pady


def _source(ctx, x, y, align="left", fill=(225, 225, 230)):
    s = (ctx.post.source or ("@" + ctx.brand.watermark.replace(" ", "").lower()
                             if ctx.brand.watermark else "")).strip()
    if not s:
        return
    f = ctx.fonts.font("ui", int(ctx.W * 0.026))
    tw = ctx.draw.textlength(s, font=f)
    lx = {"center": x - tw / 2, "right": x - tw}.get(align, x)
    draw_text(ctx.draw, (int(lx), y), s, f, fill, shadow=True)


def _wordmark_corner(ctx):
    brand = ctx.brand
    f = ctx.fonts.font("ui", int(ctx.W * 0.03))
    txt = (brand.event_badge + " " if brand.event_badge else "") + brand.event_name.upper()
    tw = ctx.draw.textlength(txt, font=f)
    draw_text(ctx.draw, (int(ctx.W - ctx.ml - tw), ctx.ml), txt, f, WHITE)


def _date_corner(ctx):
    d = (ctx.post.date_text or "").strip().upper()
    if not d:
        return
    f = ctx.fonts.font("ui", int(ctx.W * 0.03))
    draw_text(ctx.draw, (ctx.ml, ctx.ml), d, f, WHITE)


def _headline_role(serif=False, heavy=False):
    return "logo_serif" if serif else ("logo_heavy" if heavy else "logo_sans")


# --------------------------------------------------------------------------
# the 16 templates  (each draws onto ctx.base which already holds the cover art)
# --------------------------------------------------------------------------
def _t_bottom(ctx):
    _scrim_bottom(ctx, 0.62, 240)
    ml, W, H = ctx.ml, ctx.W, ctx.H
    _wordmark_corner(ctx)
    _date_corner(ctx)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.34), 4, int(W * 0.105))
    by = H - int(H * 0.07) - len(lines) * lh
    _category(ctx, ml, by - int(H * 0.07), "left")
    draw_wrapped(ctx, lines, ml, by, f, lh, WHITE, "left")
    _source(ctx, ml, by + len(lines) * lh + int(H * 0.012), "left")


def _t_breaking(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _darken(ctx, 90)
    barh = int(H * 0.1)
    ctx.draw.rectangle([0, 0, W, barh], fill=(226, 40, 56, 255))
    bf = ctx.fonts.font("ui", int(barh * 0.42))
    draw_text(ctx.draw, (ml, int(barh * 0.28)), "BREAKING NEWS", bf, WHITE, shadow=False)
    _date_corner_in_bar(ctx, barh)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(heavy=False),
                               W - 2 * ml, int(H * 0.4), 4, int(W * 0.1))
    y = int(H * 0.5) - (len(lines) * lh) // 2
    draw_wrapped(ctx, lines, ml, y, f, lh, WHITE, "left")
    _source(ctx, ml, H - int(H * 0.06), "left")


def _date_corner_in_bar(ctx, barh):
    d = (ctx.post.date_text or "").strip().upper()
    if not d:
        return
    bf = ctx.fonts.font("ui", int(barh * 0.4))
    tw = ctx.draw.textlength(d, font=bf)
    draw_text(ctx.draw, (int(ctx.W - ctx.ml - tw), int(barh * 0.3)), d, bf, WHITE, shadow=False)


def _t_release(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _scrim_bottom(ctx, 0.7, 235)
    _wordmark_corner(ctx)
    cx = W // 2
    _category(ctx, cx, int(H * 0.5), "center", text=ctx.post.category or "RELEASE DATE")
    d = (ctx.post.date_text or "").strip().upper() or "COMING SOON"
    df = ctx.fonts.fit(ctx.draw, d, "date", int(W * 0.86), int(H * 0.18), start=int(W * 0.2))
    l, t, r, b = ctx.draw.textbbox((0, 0), d, font=df)
    draw_text(ctx.draw, (cx - (r - l) // 2, int(H * 0.57)), d, df, WHITE, shadow_off=(3, 4))
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.16), 2, int(W * 0.07))
    draw_wrapped(ctx, lines, cx, int(H * 0.8), f, lh, WHITE, "center", anchor=cx)


def _t_lowerthird(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    bar_y = int(H * 0.66)
    ctx.base.alpha_composite(_vertical_alpha(W, H - bar_y, (0, 0, 0), 120, 245), (0, bar_y))
    ctx.draw.rectangle([0, bar_y, int(W * 0.5), bar_y + int(H * 0.012)], fill=ctx.accent + (255,))
    _wordmark_corner(ctx)
    _category(ctx, ml, bar_y + int(H * 0.03), "left")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.2), 3, int(W * 0.085))
    y = draw_wrapped(ctx, lines, ml, bar_y + int(H * 0.1), f, lh, WHITE, "left")
    _source(ctx, ml, y + int(H * 0.012), "left")


def _t_quote(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _darken(ctx, 120)
    qf = ctx.fonts.font("logo_serif", int(W * 0.3))
    draw_text(ctx.draw, (ml, int(H * 0.16)), "“", qf, ctx.accent)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(serif=True),
                               W - 2 * ml, int(H * 0.4), 5, int(W * 0.08))
    y = int(H * 0.36)
    draw_wrapped(ctx, lines, ml, y, f, lh, WHITE, "left")
    _source(ctx, ml, y + len(lines) * lh + int(H * 0.03), "left", fill=ctx.accent)


def _t_topbar(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    top = int(H * 0.34)
    # solid top block with category + headline, art below
    ctx.base.alpha_composite(Image.new("RGBA", (W, top), (14, 14, 18, 255)))
    ctx.draw.rectangle([0, top, W, top + 6], fill=ctx.accent + (255,))
    _category(ctx, ml, int(H * 0.05), "left")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(top * 0.55), 3, int(W * 0.085))
    draw_wrapped(ctx, lines, ml, int(H * 0.11), f, lh, WHITE, "left")
    _source(ctx, ml, H - int(H * 0.05), "left")


def _t_centered(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _darken(ctx, 130)
    cx = W // 2
    _category(ctx, cx, int(H * 0.3), "center")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), int(W * 0.84),
                               int(H * 0.34), 4, int(W * 0.1))
    y = int(H * 0.42)
    draw_wrapped(ctx, lines, cx, y, f, lh, WHITE, "center", anchor=cx)
    _source(ctx, cx, y + len(lines) * lh + int(H * 0.02), "center")


def _t_magazine(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _scrim_top(ctx, 0.4, 150)
    _scrim_bottom(ctx, 0.5, 220)
    mast = (ctx.brand.event_name or "ANIME NEWS").upper()
    mf = ctx.fonts.font("logo_serif", int(W * 0.075))
    tw = ctx.draw.textlength(mast, font=mf)
    draw_text(ctx.draw, (W // 2 - tw / 2, int(H * 0.05)), mast, mf, WHITE)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(serif=True),
                               W - 2 * ml, int(H * 0.3), 4, int(W * 0.095))
    by = H - int(H * 0.08) - len(lines) * lh
    draw_wrapped(ctx, lines, ml, by, f, lh, WHITE, "left")
    _source(ctx, ml, by + len(lines) * lh + int(H * 0.01), "left")


def _t_splitbottom(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    sy = int(H * 0.58)
    ctx.base.alpha_composite(Image.new("RGBA", (W, H - sy), (14, 14, 18, 255)), (0, sy))
    ctx.draw.rectangle([0, sy, W, sy + 6], fill=ctx.accent + (255,))
    _category(ctx, ml, sy + int(H * 0.04), "left")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.22), 3, int(W * 0.085))
    y = draw_wrapped(ctx, lines, ml, sy + int(H * 0.11), f, lh, WHITE, "left")
    _source(ctx, ml, y + int(H * 0.012), "left")


def _t_minimal(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _scrim_bottom(ctx, 0.5, 200)
    _category(ctx, ml, ml, "left")
    _date_corner_right(ctx)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), int(W * 0.82),
                               int(H * 0.24), 3, int(W * 0.082))
    by = H - int(H * 0.08) - len(lines) * lh
    draw_wrapped(ctx, lines, ml, by, f, lh, WHITE, "left")
    _source(ctx, ml, by + len(lines) * lh + int(H * 0.01), "left")


def _date_corner_right(ctx):
    d = (ctx.post.date_text or "").strip().upper()
    if not d:
        return
    f = ctx.fonts.font("ui", int(ctx.W * 0.03))
    tw = ctx.draw.textlength(d, font=f)
    draw_text(ctx.draw, (int(ctx.W - ctx.ml - tw), ctx.ml), d, f, WHITE)


def _t_sidebar(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    colw = int(W * 0.16)
    ctx.base.alpha_composite(Image.new("RGBA", (colw, H), ctx.accent + (255,)))
    _darken(ctx, 60)
    # vertical category on the bar
    cat = (ctx.post.category or "NEWS").upper()
    cf = ctx.fonts.font("ui", int(colw * 0.34))
    layer = Image.new("RGBA", (int(H * 0.7), int(colw * 0.8)), (0, 0, 0, 0))
    draw_text(ImageDraw.Draw(layer), (0, 0), cat, cf, readable_text_color(ctx.accent), shadow=False)
    layer = layer.rotate(90, expand=True)
    ctx.base.alpha_composite(layer, ((colw - layer.width) // 2, (H - layer.height) // 2))
    x = colw + int(W * 0.04)
    _scrim_bottom(ctx, 0.6, 220)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - x - ml,
                               int(H * 0.34), 4, int(W * 0.1))
    by = H - int(H * 0.08) - len(lines) * lh
    draw_wrapped(ctx, lines, x, by, f, lh, WHITE, "left")
    _source(ctx, x, by + len(lines) * lh + int(H * 0.01), "left")


def _t_ticker(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    barh = int(H * 0.14)
    by = H - barh
    ctx.base.alpha_composite(Image.new("RGBA", (W, barh), ctx.accent + (255,)), (0, by))
    fg = readable_text_color(ctx.accent)
    # date stamp box on the right of the ticker
    d = (ctx.post.date_text or "").strip().upper()
    stub = 0
    if d:
        stub = int(W * 0.26)
        ctx.draw.rectangle([W - stub, by, W, H], fill=(14, 14, 18, 255))
        df = ctx.fonts.fit(ctx.draw, d, "date", stub - 30, int(barh * 0.6), start=int(barh * 0.7))
        l, t, r, b = ctx.draw.textbbox((0, 0), d, font=df)
        draw_text(ctx.draw, (W - stub + (stub - (r - l)) // 2, by + (barh - (b - t)) // 2 - t),
                  d, df, WHITE, shadow=False)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - stub - 2 * ml,
                               int(barh * 0.7), 2, int(barh * 0.5))
    draw_wrapped(ctx, lines, ml, by + (barh - len(lines) * lh) // 2, f, lh, fg, "left", shadow=False)
    _category(ctx, ml, by - int(H * 0.07), "left")


def _t_poster(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _darken(ctx, 120)
    apply_vignette(ctx.base, 0.4)
    cx = W // 2
    _category(ctx, cx, int(H * 0.12), "center")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(heavy=True),
                               int(W * 0.88), int(H * 0.5), 4, int(W * 0.14))
    y = int(H * 0.5) - (len(lines) * lh) // 2
    draw_wrapped(ctx, lines, cx, y, f, lh, WHITE, "center", anchor=cx)
    _source(ctx, cx, H - int(H * 0.07), "center")


def _t_stamp(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _scrim_bottom(ctx, 0.62, 235)
    d = (ctx.post.date_text or "").strip().upper()
    cyc = int(H * 0.22)
    if d:
        R = int(W * 0.13)
        cxc = W - ml - R
        ctx.draw.ellipse([cxc - R, cyc - R, cxc + R, cyc + R], fill=ctx.accent + (255,))
        ctx.draw.ellipse([cxc - R + 7, cyc - R + 7, cxc + R - 7, cyc + R - 7],
                         outline=(255, 255, 255, 220), width=3)
        fg = readable_text_color(ctx.accent)
        parts = d.split()
        if len(parts) >= 2:
            mf = ctx.fonts.font("ui", int(R * 0.36))
            df = ctx.fonts.font("date", int(R * 0.8))
            _ct(ctx, parts[0], mf, cxc, cyc - int(R * 0.5), fg)
            _ct(ctx, " ".join(parts[1:]), df, cxc, cyc - int(R * 0.2), fg)
        else:
            _ct(ctx, d, ctx.fonts.font("date", int(R * 0.55)), cxc, cyc - int(R * 0.3), fg)
    _wordmark_corner(ctx)
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.3), 4, int(W * 0.1))
    by = H - int(H * 0.08) - len(lines) * lh
    _category(ctx, ml, by - int(H * 0.07), "left")
    draw_wrapped(ctx, lines, ml, by, f, lh, WHITE, "left")


def _ct(ctx, text, font, cx, y, fill):
    tw = ctx.draw.textlength(text, font=font)
    draw_text(ctx.draw, (int(cx - tw / 2), y), text, font, fill, shadow=False)


def _t_framed(ctx, _bg_solid=(14, 14, 18)):
    # handled specially in render_news (art is framed); here just text
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _category(ctx, ml, int(H * 0.64), "left")
    f, lines, lh = fit_wrapped(ctx, ctx.post.headline, _headline_role(), W - 2 * ml,
                               int(H * 0.22), 3, int(W * 0.085))
    y = draw_wrapped(ctx, lines, ml, int(H * 0.71), f, lh, WHITE, "left")
    _source(ctx, ml, y + int(H * 0.012), "left")
    _wordmark_corner(ctx)


def _t_list(ctx):
    W, H, ml = ctx.W, ctx.H, ctx.ml
    _darken(ctx, 150)
    _category(ctx, ml, ml, "left")
    _wordmark_corner(ctx)
    hf, hlines, hlh = fit_wrapped(ctx, ctx.post.headline, _headline_role(heavy=True),
                                  W - 2 * ml, int(H * 0.2), 2, int(W * 0.1))
    y = draw_wrapped(ctx, lines=hlines, x=ml, y=int(H * 0.13), font=hf, lh=hlh, fill=WHITE)
    items = ctx.post.items or [x for x in (ctx.post.body or "").split("\n") if x.strip()]
    y += int(H * 0.03)
    nf = ctx.fonts.font("date", int(W * 0.05))
    tf = ctx.fonts.font("ui", int(W * 0.045))
    for i, it in enumerate(items[:8], 1):
        draw_text(ctx.draw, (ml, y), str(i), nf, ctx.accent)
        draw_text(ctx.draw, (ml + int(W * 0.09), y + int(W * 0.005)), str(it).strip(), tf, WHITE)
        y += int(H * 0.072)


NEWS_TEMPLATES = [
    ("bottom", "Bottom Headline", _t_bottom),
    ("breaking", "Breaking News", _t_breaking),
    ("release", "Release Date", _t_release),
    ("lowerthird", "Lower Third", _t_lowerthird),
    ("quote", "Quote", _t_quote),
    ("topbar", "Top Bar", _t_topbar),
    ("centered", "Centered", _t_centered),
    ("magazine", "Magazine", _t_magazine),
    ("splitbottom", "Split", _t_splitbottom),
    ("minimal", "Minimal", _t_minimal),
    ("sidebar", "Side Bar", _t_sidebar),
    ("ticker", "Ticker", _t_ticker),
    ("poster", "Poster", _t_poster),
    ("stamp", "Date Stamp", _t_stamp),
    ("framed", "Framed", _t_framed),
    ("list", "List / Ranking", _t_list),
]
_NEWS_BY_KEY = {k: (n, fn) for k, n, fn in NEWS_TEMPLATES}
DEFAULT_NEWS = NEWS_TEMPLATES[0][0]


def news_templates() -> list[dict]:
    return [{"key": k, "name": n} for k, n, _ in NEWS_TEMPLATES]


# --------------------------------------------------------------------------
def _theme_for(post, spec):
    themes = spec.themes or {}
    if post.theme and post.theme != "auto" and post.theme in themes:
        return themes[post.theme]
    if not themes:
        return {"top": "#16161c", "bottom": "#2a2a36", "accent": spec.brand.accent}
    keys = sorted(themes.keys())
    idx = int(hashlib.md5((post.headline or "x").encode()).hexdigest(), 16) % len(keys)
    return themes[keys[idx]]


def _open_art(post):
    if post.image_path and Path(post.image_path).exists():
        try:
            return Image.open(post.image_path).convert("RGB")
        except Exception:
            return None
    return None


def render_news(post: NewsPost, template_key: str, spec: CardSpec,
                fonts: FontBook | None = None) -> Image.Image:
    fonts = fonts or FontBook()
    W, H = spec.width, spec.height
    theme = _theme_for(post, spec)
    art = _open_art(post)
    if post.accent:
        accent = hex_to_rgb(post.accent)
    elif art is not None:
        from . import palette
        accent = palette.accent_of(art, hex_to_rgb(theme.get("accent", spec.brand.accent)))
    else:
        accent = hex_to_rgb(theme.get("accent", spec.brand.accent))

    name, fn = _NEWS_BY_KEY.get(template_key, _NEWS_BY_KEY[DEFAULT_NEWS])

    if fn is _t_framed:
        base = vertical_gradient(W, H, hex_to_rgb(theme["top"]), hex_to_rgb(theme["bottom"]))
        if art is not None:
            fr_w, fr_h = W - 2 * int(W * 0.07), int(H * 0.5)
            fr = cover_resize(art, fr_w, fr_h)
            rad = int(W * 0.04)
            mask = Image.new("L", (fr_w, fr_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, fr_w, fr_h], radius=rad, fill=255)
            base.paste(fr, (int(W * 0.07), int(H * 0.09)), mask)
    elif art is not None:
        base = cover_resize(art, W, H)
    else:
        base = vertical_gradient(W, H, hex_to_rgb(theme["top"]), hex_to_rgb(theme["bottom"]))

    ctx = NewsCtx(draw=ImageDraw.Draw(base), base=base, post=post, fonts=fonts,
                  accent=accent, brand=spec.brand, W=W, H=H, ml=int(W * 0.06))
    fn(ctx)
    return base


def save_news(card: Image.Image, out_dir: str, prefix: str = "post") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{prefix}.png"
    card.convert("RGB").save(p, "PNG")
    return [str(p)]

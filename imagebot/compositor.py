"""The compositing engine: build the stacked anime-news card with Pillow.

A card is a portrait image (default 1080x1350, Instagram 4:5) made of N stacked
panels. Each panel = background art + treatment (per the chosen Style) + series
logo/title + tag pills + event wordmark + big date, matching the reference look.

The look is driven by a `styles.Style` carried on `CardSpec.style`. The default
("Classic Expo") reproduces the reference cards; other presets restyle the same
panels (cutout, duotone, neon, noir, cinematic, …) so the user can pick.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageFilter

from .fonts import FontBook
from .models import CardSpec, Panel
from .styles import Style, DEFAULT_STYLE

WHITE = (255, 255, 255)
NEAR_BLACK = (20, 20, 22)


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def hex_to_rgb(value: str, default=(40, 40, 44)) -> tuple[int, int, int]:
    if not value:
        return default
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except Exception:
        return default


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def relative_luminance(rgb) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_text_color(bg) -> tuple[int, int, int]:
    return NEAR_BLACK if relative_luminance(bg) > 0.55 else WHITE


def vibrant_color(img: Image.Image, fallback=(245, 166, 35)) -> tuple[int, int, int]:
    """Pick a punchy accent colour from the art (most saturated mid-bright pixel)."""
    try:
        small = img.convert("RGB").resize((40, 40))
        hsv = small.convert("HSV")
        rgb = small.load()
        h = hsv.load()
        best, best_score = fallback, -1.0
        for y in range(40):
            for x in range(40):
                _, s, v = h[x, y]
                if v < 60 or v > 240:
                    continue
                score = (s / 255) * (1 - abs(v - 170) / 170)
                if score > best_score:
                    best_score, best = score, rgb[x, y]
        return best
    except Exception:
        return fallback


# --------------------------------------------------------------------------
# image building blocks
# --------------------------------------------------------------------------
def vertical_gradient(w: int, h: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = (_lerp(top[0], bottom[0], t),
                    _lerp(top[1], bottom[1], t),
                    _lerp(top[2], bottom[2], t))
    return grad.resize((w, h)).convert("RGBA")


def _f(v, default):
    try:
        return float(v)
    except Exception:
        return default


def cover_resize(img: Image.Image, w: int, h: int,
                 focus_x: float = 0.6, focus_y: float = 0.4,
                 zoom: float = 1.0) -> Image.Image:
    """Scale + crop to fill w x h. focus_x/y pan the crop (0..1); zoom (>=1)
    enlarges the art within the frame."""
    img = img.convert("RGBA")
    iw, ih = img.size
    z = max(1.0, _f(zoom, 1.0))
    scale = max(w / iw, h / ih) * z
    nw, nh = max(w, int(iw * scale)), max(h, int(ih * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    fx = min(1.0, max(0.0, _f(focus_x, 0.5)))
    fy = min(1.0, max(0.0, _f(focus_y, 0.4)))
    left, top = int((nw - w) * fx), int((nh - h) * fy)
    return img.crop((left, top, left + w, top + h))


def _alpha_scrim(w: int, h: int, color, a_left: int, a_right: int) -> Image.Image:
    mask = Image.new("L", (w, 1))
    mpx = mask.load()
    for x in range(w):
        mpx[x, 0] = _lerp(a_left, a_right, x / max(w - 1, 1))
    mask = mask.resize((w, h))
    scrim = Image.new("RGBA", (w, h), color + (0,))
    scrim.putalpha(mask)
    return scrim


def _vertical_alpha(w: int, h: int, color, a_top: int, a_bottom: int) -> Image.Image:
    mask = Image.new("L", (1, h))
    mpx = mask.load()
    for y in range(h):
        mpx[0, y] = _lerp(a_top, a_bottom, y / max(h - 1, 1))
    mask = mask.resize((w, h))
    scrim = Image.new("RGBA", (w, h), color + (0,))
    scrim.putalpha(mask)
    return scrim


def duotone(img: Image.Image, dark, light) -> Image.Image:
    gray = img.convert("L")
    return ImageOps.colorize(gray, black=dark, white=light).convert("RGBA")


def apply_vignette(base: Image.Image, amount: float) -> None:
    w, h = base.size
    mask = Image.radial_gradient("L").resize((w, h))  # 0 center -> 255 edge
    mask = mask.point(lambda v: int(v * amount))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.putalpha(mask)
    base.alpha_composite(overlay)


def apply_grain(base: Image.Image, amount: float) -> None:
    w, h = base.size
    noise = Image.effect_noise((w, h), 28).convert("L")
    overlay = Image.merge("RGBA", (noise, noise, noise,
                                   noise.point(lambda v: int(amount * 80))))
    base.alpha_composite(overlay)


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def draw_text(draw, xy, text, font, fill, shadow=True,
              shadow_fill=(0, 0, 0, 170), shadow_off=(2, 3)):
    if not text:
        return (0, 0)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    x, y = xy[0] - l, xy[1] - t
    if shadow:
        draw.text((x + shadow_off[0], y + shadow_off[1]), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)
    return (r - l, b - t)


def draw_pill(draw, xy, text, font, bg, fg=None, pad_x=22, pad_y=12, radius=None):
    fg = fg or readable_text_color(bg)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    rw, rh = tw + 2 * pad_x, th + 2 * pad_y
    x, y = xy
    rad = rh // 2 if radius is None else radius
    draw.rounded_rectangle([x, y, x + rw, y + rh], radius=rad, fill=bg)
    draw.text((x + pad_x - l, y + pad_y - t), text, font=font, fill=fg)
    return (rw, rh)


# --------------------------------------------------------------------------
# theme + art
# --------------------------------------------------------------------------
def pick_theme(panel: Panel, spec: CardSpec) -> dict:
    themes = spec.themes or {}
    if panel.theme and panel.theme != "auto" and panel.theme in themes:
        return themes[panel.theme]
    if not themes:
        return {"top": "#1a1a1f", "bottom": "#33333d", "accent": spec.brand.accent}
    keys = sorted(themes.keys())
    idx = int(hashlib.md5(panel.title.encode("utf-8")).hexdigest(), 16) % len(keys)
    return themes[keys[idx]]


def _open_art(panel: Panel) -> Image.Image | None:
    if panel.image_path and Path(panel.image_path).exists():
        try:
            return Image.open(panel.image_path).convert("RGB")
        except Exception:
            return None
    return None


def _cutout(panel: Panel) -> Image.Image | None:
    """Subject cut-out (RGBA) via the optional local enhance layer (rembg)."""
    if not (panel.image_path and Path(panel.image_path).exists()):
        return None
    try:
        from . import enhance
        return enhance.remove_background(panel.image_path)
    except Exception:
        return None


def _accent(panel, spec, theme, style: Style, art) -> tuple[int, int, int]:
    if panel.accent:
        return hex_to_rgb(panel.accent)
    if style.accent_mode == "fixed" and style.accent:
        return hex_to_rgb(style.accent)
    # otherwise pull a proper, vivid accent straight from the key visual
    if art is not None and style.accent_mode in ("series", "auto", "theme"):
        from . import palette
        return palette.accent_of(art, hex_to_rgb(theme.get("accent", spec.brand.accent)))
    return hex_to_rgb(theme.get("accent") or spec.brand.accent)


def _styled_backdrop(w, h, theme, style) -> Image.Image:
    if style.bg == "solid" and style.solid:
        return Image.new("RGBA", (w, h), hex_to_rgb(style.solid) + (255,))
    top, bottom = hex_to_rgb(theme["top"]), hex_to_rgb(theme["bottom"])
    return vertical_gradient(w, h, top, bottom)


def _build_background(panel, w, h, style: Style, theme, accent) -> Image.Image:
    art = _open_art(panel)

    # cutout-based styles
    if style.bg in ("art_cutout", "art_blur_cutout"):
        cut = _cutout(panel)
        if cut is not None:
            base = _styled_backdrop(w, h, theme, style)
            if style.bg == "art_blur_cutout" and art is not None:
                bg = cover_resize(art, w, h, panel.focus_x, panel.focus_y, panel.zoom).filter(ImageFilter.GaussianBlur(style.blur or 16))
                bg.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, 70)))
                base = bg
            if style.glow:
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                gd = ImageDraw.Draw(glow)
                cx, cy = int(w * 0.6), int(h * 0.55)
                rr = int(h * 0.6)
                gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=accent + (130,))
                base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(h * 0.18))))
            # place subject, anchored bottom-right, ~92% panel height
            ch = int(h * 0.92)
            cw = max(1, int(cut.width * ch / cut.height))
            cut = cut.resize((cw, ch), Image.LANCZOS)
            base.alpha_composite(cut, (int(w * 0.52), h - ch))
            return base
        # no cutout available -> fall through to full-art with extra mood

    if art is not None:
        base = cover_resize(art, w, h, panel.focus_x, panel.focus_y, panel.zoom)
        if style.bg == "art_duotone" and style.duotone:
            base = duotone(base, hex_to_rgb(style.duotone[0]), hex_to_rgb(style.duotone[1]))
        elif style.grayscale:
            base = ImageOps.grayscale(base).convert("RGBA")
        if style.blur:
            base = base.filter(ImageFilter.GaussianBlur(style.blur))
        return base

    return _styled_backdrop(w, h, theme, style)


# --------------------------------------------------------------------------
# logo / title block
# --------------------------------------------------------------------------
def _title_role(style: Style, panel: Panel, fonts: FontBook) -> str:
    if style.title_role and style.title_role != "auto":
        return fonts.logo_role(style.title_role)
    return fonts.logo_role(panel.logo_style)


def _draw_logo_block(draw, base, panel, fonts, style, w, u, top_y, max_w,
                     align="left", left=0, max_h_frac=0.34, center_x=None):
    """Draw the logo image (if any) or the styled title text. Returns bottom y.
    align: left | center | right  (for right, `left` is the right anchor x;
    for center, pass center_x to centre within a region else the full width)."""
    def _x(width):
        if align == "center":
            c = w // 2 if center_x is None else center_x
            return c - width // 2
        if align == "right":
            return left - width
        return left
    # logo image overlay
    if panel.logo_path and Path(panel.logo_path).exists():
        try:
            logo = Image.open(panel.logo_path).convert("RGBA")
            mh = int(u * max_h_frac * max(0.3, panel.logo_scale))
            mw = int(max_w * max(0.3, panel.logo_scale))
            scale = min(mw / logo.width, mh / logo.height)
            logo = logo.resize((max(1, int(logo.width * scale)),
                                max(1, int(logo.height * scale))), Image.LANCZOS)
            base.alpha_composite(logo, (_x(logo.width), top_y))
            return top_y + logo.height
        except Exception:
            pass
    # text title
    title = panel.title.strip() or "UNTITLED"
    role = fonts.role_for_text(title, _title_role(style, panel, fonts)) or _title_role(style, panel, fonts)
    font = fonts.fit(draw, title, role, max_w, int(u * max_h_frac), start=int(u * (max_h_frac + 0.08)))
    l, t, r, b = draw.textbbox((0, 0), title, font=font)
    draw_text(draw, (_x(r - l), top_y), title, font, WHITE)
    return top_y + (b - t)


# --------------------------------------------------------------------------
# panel rendering
# --------------------------------------------------------------------------
def render_panel(panel: Panel, w: int, h: int, fonts: FontBook, spec: CardSpec) -> Image.Image:
    style: Style = spec.style or DEFAULT_STYLE
    theme = pick_theme(panel, spec)
    art_for_accent = _open_art(panel)
    accent = _accent(panel, spec, theme, style, art_for_accent)

    base = _build_background(panel, w, h, style, theme, accent)

    # tint wash
    if style.tint:
        base.alpha_composite(Image.new("RGBA", (w, h), hex_to_rgb(style.tint) + (style.tint_alpha,)))
    # overall darken
    if style.darken:
        base.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, style.darken)))
    # scrims
    if style.scrim_left:
        base.alpha_composite(_alpha_scrim(int(w * 0.66), h, (0, 0, 0), style.scrim_left, 0))
    if style.scrim_right:
        rw = int(w * 0.46)
        base.alpha_composite(_alpha_scrim(rw, h, (0, 0, 0), 0, style.scrim_right), (w - rw, 0))
    if style.scrim_bottom:
        bh = int(h * 0.5)
        base.alpha_composite(_vertical_alpha(w, bh, (0, 0, 0), 0, style.scrim_bottom), (0, h - bh))
    # effects
    if style.vignette:
        apply_vignette(base, style.vignette)
    if style.grain:
        apply_grain(base, style.grain)
    if style.bars:
        bar = min(style.bars, h // 5)
        d0 = ImageDraw.Draw(base)
        d0.rectangle([0, 0, w, bar], fill=(0, 0, 0, 255))
        d0.rectangle([0, h - bar, w, h], fill=(0, 0, 0, 255))

    draw = ImageDraw.Draw(base)
    ml = int(w * 0.045)
    u = min(h, int(w * 0.34))
    cy0 = (h - u) // 2
    ctx = _Ctx(draw=draw, base=base, panel=panel, fonts=fonts, style=style,
               accent=accent, brand=spec.brand, w=w, h=h, u=u, cy0=cy0,
               ml=ml, right_edge=w - ml)
    _LAYOUTS.get(style.layout, _layout_classic)(ctx)
    return base


# --------------------------------------------------------------------------
# layout system — each layout arranges title/pills/date/wordmark differently,
# so styles look structurally distinct (not just recoloured).
# --------------------------------------------------------------------------
class _Ctx:
    __slots__ = ("draw", "base", "panel", "fonts", "style", "accent", "brand",
                 "w", "h", "u", "cy0", "ml", "right_edge")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _wordmark(ctx, anchor_x, off=0.14, small=False, align="right"):
    brand, draw, u = ctx.brand, ctx.draw, ctx.u
    badge = brand.event_badge.strip()
    name = brand.event_name.strip().upper()
    if not (name or badge):          # no event set -> draw nothing
        return
    f = ctx.fonts.font("ui", max(14, int(u * (0.06 if small else 0.085))))
    _, bt, _, bb = draw.textbbox((0, 0), name or badge, font=f)
    name_h = bb - bt
    name_w = (draw.textbbox((0, 0), name, font=f)[2] if name else 0)
    bp = int(name_h * 0.28)
    badge_w = 0
    if badge:
        x0, _, x1, _ = draw.textbbox((0, 0), badge, font=f)
        badge_w = (x1 - x0) + 2 * bp
    gap = int(name_h * 0.4)
    group = badge_w + (gap if (badge_w and name) else 0) + name_w
    gx = {"right": anchor_x - group, "center": anchor_x - group // 2}.get(align, anchor_x)
    gy = ctx.cy0 + int(u * off)
    if badge:
        bh = name_h + 2 * bp
        draw.rounded_rectangle([gx, gy - bp, gx + badge_w, gy - bp + bh],
                               radius=int(bh * 0.18), fill=WHITE)
        draw_text(draw, (gx + bp, gy), badge, f, NEAR_BLACK, shadow=False)
        gx += badge_w + gap
    if name:
        draw_text(draw, (gx, gy), name, f, WHITE)


def _date(ctx, anchor_x, y, align="right", maxw=0.42, maxh=0.5, start=0.62):
    d = (ctx.panel.date_text or "").strip().upper()
    if not d:
        return
    f = ctx.fonts.fit(ctx.draw, d, "date", int(ctx.w * maxw), int(ctx.u * maxh),
                      start=int(ctx.u * start))
    l, t, r, b = ctx.draw.textbbox((0, 0), d, font=f)
    x = {"right": anchor_x - (r - l), "center": anchor_x - (r - l) // 2}.get(align, anchor_x)
    draw_text(ctx.draw, (x, y), d, f, WHITE, shadow_off=(3, 4))


def _subtitle(ctx, x, y, max_w, align="left"):
    sub = ctx.panel.subtitle.strip()
    role = ctx.fonts.role_for_text(sub, "ui_regular") if sub else None
    if not role:
        return y
    f = ctx.fonts.fit(ctx.draw, sub, role, max_w, int(ctx.u * 0.10), start=int(ctx.u * 0.13))
    l, t, r, b = ctx.draw.textbbox((0, 0), sub, font=f)
    sx = {"center": x - (r - l) // 2, "right": x - (r - l)}.get(align, x)
    draw_text(ctx.draw, (sx, y), sub, f, (235, 235, 240))
    return y + (b - t) + int(ctx.u * 0.04)


def _pills(ctx, x, y, align="left"):
    panel, style, draw, w, u = ctx.panel, ctx.style, ctx.draw, ctx.w, ctx.u
    f = ctx.fonts.font("ui", max(14, int(u * 0.05)))
    items = []
    if panel.tag_main.strip():
        items.append((panel.tag_main.upper(), ctx.accent, None))
    if panel.tag_sub.strip():
        items.append((panel.tag_sub.upper(), style.pill_light, readable_text_color(style.pill_light)))
    if not items:
        return y
    padx, pady, gap = int(w * 0.02), int(u * 0.035), int(w * 0.012)
    widths = []
    for txt, _, _ in items:
        l, t, r, b = draw.textbbox((0, 0), txt, font=f)
        widths.append((r - l) + 2 * padx)
    total = sum(widths) + gap * (len(items) - 1)
    sx = {"center": x - total // 2, "right": x - total}.get(align, x)
    px, hh = sx, 0
    for (txt, bg, fg), wd in zip(items, widths):
        _, hh = draw_pill(draw, (px, y), txt, f, bg, fg, pad_x=padx, pad_y=pady)
        px += wd + gap
    return y + hh + int(u * 0.04)


def _logo(ctx, top_y, max_w, align="left", anchor=None, max_h=0.34, center_x=None):
    anchor = ctx.ml if anchor is None else anchor
    return _draw_logo_block(ctx.draw, ctx.base, ctx.panel, ctx.fonts, ctx.style,
                            ctx.w, ctx.u, top_y, max_w, align=align, left=anchor,
                            max_h_frac=max_h, center_x=center_x)


def _center_text(ctx, text, font, cx, top_y, fill, shadow=True):
    if not text:
        return 0
    l, t, r, b = ctx.draw.textbbox((0, 0), text, font=font)
    draw_text(ctx.draw, (cx - (r - l) // 2, top_y), text, font, fill, shadow=shadow)
    return b - t


def _block(ctx, box, alpha=232, edge=False, edge_side="right"):
    x0, y0, x1, y1 = box
    ctx.base.alpha_composite(Image.new("RGBA", (x1 - x0, y1 - y0), (10, 10, 14, alpha)), (x0, y0))
    if edge:
        d = ImageDraw.Draw(ctx.base)
        if edge_side == "right":
            d.rectangle([x1 - 5, y0, x1, y1], fill=ctx.accent + (255,))
        else:
            d.rectangle([x0, y0, x1, y0 + 4], fill=ctx.accent + (255,))


def _layout_classic(ctx):
    u, ml = ctx.u, ctx.ml
    maxw = int(ctx.w * 0.46)
    y = _logo(ctx, ctx.cy0 + int(u * 0.17), maxw, "left", ml) + int(u * 0.04)
    y = _subtitle(ctx, ml, y, maxw, "left")
    _pills(ctx, ml, y, "left")
    _wordmark(ctx, ctx.right_edge, 0.14, align="right")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.38), "right")


def _layout_center(ctx):
    u, cx = ctx.u, ctx.w // 2
    _wordmark(ctx, cx, 0.04, small=True, align="center")
    maxw = int(ctx.w * 0.7)
    y = _logo(ctx, ctx.cy0 + int(u * 0.18), maxw, "center", max_h=0.27) + int(u * 0.035)
    y = _subtitle(ctx, cx, y, maxw, "center")
    _pills(ctx, cx, y, "center")
    _date(ctx, cx, ctx.cy0 + int(u * 0.74), "center", maxw=0.8, maxh=0.28, start=0.46)


def _layout_mirror(ctx):
    u, ml, redge = ctx.u, ctx.ml, ctx.right_edge
    _wordmark(ctx, ml, 0.14, small=True, align="left")
    _date(ctx, ml, ctx.cy0 + int(u * 0.38), "left")
    maxw = int(ctx.w * 0.46)
    y = _logo(ctx, ctx.cy0 + int(u * 0.17), maxw, "right", redge) + int(u * 0.04)
    y = _subtitle(ctx, redge, y, maxw, "right")
    _pills(ctx, redge, y, "right")


def _layout_sidebar(ctx):
    u, w, h = ctx.u, ctx.w, ctx.h
    colw = int(w * 0.46)
    _block(ctx, (0, 0, colw, h), alpha=232, edge=True, edge_side="right")
    pad = int(w * 0.045)
    maxw = colw - 2 * pad
    _wordmark(ctx, pad, 0.06, small=True, align="left")
    y = _logo(ctx, ctx.cy0 + int(u * 0.18), maxw, "left", pad, max_h=0.22) + int(u * 0.03)
    y = _subtitle(ctx, pad, y, maxw, "left")
    y = _pills(ctx, pad, y, "left")
    _date(ctx, pad, y + int(u * 0.01), "left", maxw=0.42, maxh=0.2, start=0.3)


def _layout_bottombar(ctx):
    u, w, h = ctx.u, ctx.w, ctx.h
    barh = int(h * 0.36)
    _block(ctx, (0, h - barh, w, h), alpha=232, edge=True, edge_side="top")
    ml = ctx.ml
    _wordmark(ctx, ctx.right_edge, 0.1, small=True, align="right")
    _pills(ctx, ml, h - barh - int(u * 0.17), "left")
    _logo(ctx, h - barh + int(barh * 0.2), int(w * 0.55), "left", ml, max_h=0.16)
    _date(ctx, ctx.right_edge, h - barh + int(barh * 0.22), "right",
          maxw=0.34, maxh=0.2, start=0.34)


def _layout_lowerthird(ctx):
    u, ml = ctx.u, ctx.ml
    _wordmark(ctx, ml, 0.12, small=True, align="left")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.12), "right", maxw=0.34, maxh=0.26, start=0.32)
    maxw = int(ctx.w * 0.6)
    y = _pills(ctx, ml, ctx.cy0 + int(u * 0.52), "left")
    _logo(ctx, y, maxw, "left", ml, max_h=0.28)


def _layout_badge(ctx):
    u, ml, w = ctx.u, ctx.ml, ctx.w
    d = (ctx.panel.date_text or "").strip().upper()
    if d:
        f = ctx.fonts.fit(ctx.draw, d, "date", int(w * 0.3), int(u * 0.3), start=int(u * 0.36))
        l, t, r, b = ctx.draw.textbbox((0, 0), d, font=f)
        padx, pady = int(w * 0.025), int(u * 0.06)
        bw, bh = (r - l) + 2 * padx, (b - t) + 2 * pady
        bx, by = ctx.right_edge - bw, ctx.cy0 + int(u * 0.12)
        ctx.draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh * 0.28),
                                   fill=ctx.accent + (255,))
        draw_text(ctx.draw, (bx + padx, by + pady), d, f,
                  readable_text_color(ctx.accent), shadow=False)
    maxw = int(w * 0.5)
    y = _logo(ctx, ctx.cy0 + int(u * 0.2), maxw, "left", ml) + int(u * 0.04)
    y = _subtitle(ctx, ml, y, maxw, "left")
    _pills(ctx, ml, y, "left")
    _wordmark(ctx, ml, 0.84, small=True, align="left")


def _layout_diagonal(ctx):
    w, h, u, ml = ctx.w, ctx.h, ctx.u, ctx.ml
    poly = [(0, 0), (int(w * 0.52), 0), (int(w * 0.40), h), (0, h)]
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ov).polygon(poly, fill=(10, 10, 14, 235))
    ctx.base.alpha_composite(ov)
    ImageDraw.Draw(ctx.base).line([(int(w * 0.52), 0), (int(w * 0.40), h)],
                                  fill=ctx.accent + (255,), width=7)
    maxw = int(w * 0.4)
    _wordmark(ctx, ml, 0.1, small=True, align="left")
    y = _logo(ctx, ctx.cy0 + int(u * 0.2), maxw, "left", ml, max_h=0.26) + int(u * 0.04)
    y = _subtitle(ctx, ml, y, maxw, "left")
    _pills(ctx, ml, y, "left")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.38), "right")


def _layout_vertical(ctx):
    w, h, u, ml = ctx.w, ctx.h, ctx.u, ctx.ml
    title = ctx.panel.title.strip() or "UNTITLED"
    role = ctx.fonts.role_for_text(title, _title_role(ctx.style, ctx.panel, ctx.fonts)) \
        or _title_role(ctx.style, ctx.panel, ctx.fonts)
    thick = int(u * 0.26)
    f = ctx.fonts.fit(ctx.draw, title, role, int(h * 0.82), thick, start=thick)
    l, t, r, b = ctx.draw.textbbox((0, 0), title, font=f)
    layer = Image.new("RGBA", (r - l + 10, b - t + 10), (0, 0, 0, 0))
    draw_text(ImageDraw.Draw(layer), (5 - l, 5 - t), title, f, WHITE)
    layer = layer.rotate(90, expand=True)
    ly = (h - layer.height) // 2
    ctx.base.alpha_composite(layer, (ml, ly))
    bar_x = ml + layer.width + 8
    ImageDraw.Draw(ctx.base).rectangle([bar_x, ly, bar_x + 6, ly + layer.height],
                                       fill=ctx.accent + (255,))
    _wordmark(ctx, ctx.right_edge, 0.1, small=True, align="right")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.38), "right")
    _pills(ctx, bar_x + int(w * 0.03), ctx.cy0 + int(u * 0.74), "left")


def _layout_medallion(ctx):
    w, u, ml = ctx.w, ctx.u, ctx.ml
    d = (ctx.panel.date_text or "").strip().upper()
    cxc, cyc, R = int(w * 0.17), ctx.cy0 + ctx.u // 2, int(u * 0.34)
    lx = ml
    if d:
        ctx.draw.ellipse([cxc - R, cyc - R, cxc + R, cyc + R], fill=ctx.accent + (255,))
        ctx.draw.ellipse([cxc - R + 8, cyc - R + 8, cxc + R - 8, cyc + R - 8],
                         outline=(255, 255, 255, 210), width=3)
        fg = readable_text_color(ctx.accent)
        parts = d.split()
        if len(parts) >= 2:
            mf = ctx.fonts.font("ui", int(R * 0.42))
            df = ctx.fonts.font("date", int(R * 0.85))
            _center_text(ctx, parts[0], mf, cxc, cyc - int(R * 0.5), fg, shadow=False)
            _center_text(ctx, " ".join(parts[1:]), df, cxc, cyc - int(R * 0.22), fg, shadow=False)
        else:
            _center_text(ctx, d, ctx.fonts.font("date", int(R * 0.6)), cxc,
                         cyc - int(R * 0.3), fg, shadow=False)
        lx = cxc + R + int(w * 0.03)
    maxw = ctx.right_edge - lx
    y = _logo(ctx, ctx.cy0 + int(u * 0.24), maxw, "left", lx, max_h=0.3) + int(u * 0.04)
    y = _subtitle(ctx, lx, y, maxw, "left")
    _pills(ctx, lx, y, "left")
    _wordmark(ctx, ctx.right_edge, 0.1, small=True, align="right")


def _layout_ticket(ctx):
    w, h, u, ml = ctx.w, ctx.h, ctx.u, ctx.ml
    stubx = int(w * 0.72)
    _block(ctx, (stubx, 0, w, h), alpha=236)
    dd = ImageDraw.Draw(ctx.base)
    dd.line([(stubx, 0), (stubx, h)], fill=ctx.accent + (255,), width=3)
    yy = 8
    while yy < h:
        dd.ellipse([stubx - 5, yy, stubx + 5, yy + 9], fill=(0, 0, 0, 255))
        yy += 24
    _date(ctx, stubx + (w - stubx) // 2, ctx.cy0 + int(u * 0.3), "center",
          maxw=0.24, maxh=0.42, start=0.42)
    maxw = stubx - ml - int(w * 0.03)
    _wordmark(ctx, ml, 0.1, small=True, align="left")
    y = _logo(ctx, ctx.cy0 + int(u * 0.24), maxw, "left", ml, max_h=0.3) + int(u * 0.04)
    y = _subtitle(ctx, ml, y, maxw, "left")
    _pills(ctx, ml, y, "left")


def _layout_ribbon(ctx):
    w, u, ml = ctx.w, ctx.u, ctx.ml
    barh = int(u * 0.2)
    by = ctx.cy0 + int(u * 0.08)
    ImageDraw.Draw(ctx.base).rectangle([0, by, w, by + barh], fill=ctx.accent + (255,))
    fg = readable_text_color(ctx.accent)
    f = ctx.fonts.font("ui", max(13, int(barh * 0.46)))
    draw_text(ctx.draw, (ml, by + int(barh * 0.27)), ctx.brand.event_name.upper(), f, fg, shadow=False)
    d = (ctx.panel.date_text or "").strip().upper()
    if d:
        l, t, r, b = ctx.draw.textbbox((0, 0), d, font=f)
        draw_text(ctx.draw, (ctx.right_edge - (r - l), by + int(barh * 0.27)), d, f, fg, shadow=False)
    maxw = int(w * 0.72)
    y = _logo(ctx, by + barh + int(u * 0.07), maxw, "left", ml, max_h=0.3) + int(u * 0.04)
    _pills(ctx, ml, y, "left")


def _layout_halfsplit(ctx):
    w, h, u = ctx.w, ctx.h, ctx.u
    half = int(w * 0.5)
    cx = half // 2
    _block(ctx, (0, 0, half, h), alpha=245, edge=True, edge_side="right")
    maxw = int(half * 0.84)
    _wordmark(ctx, cx, 0.08, small=True, align="center")
    y = _logo(ctx, ctx.cy0 + int(u * 0.18), maxw, "center", center_x=cx, max_h=0.22) + int(u * 0.035)
    y = _subtitle(ctx, cx, y, maxw, "center")
    _pills(ctx, cx, y, "center")
    _date(ctx, cx, ctx.cy0 + int(u * 0.74), "center", maxw=0.4, maxh=0.2, start=0.32)


def _layout_minimal(ctx):
    u, cx = ctx.u, ctx.w // 2
    _wordmark(ctx, cx, 0.06, small=True, align="center")
    maxw = int(ctx.w * 0.8)
    _logo(ctx, ctx.cy0 + int(u * 0.34), maxw, "center", center_x=cx, max_h=0.24)
    d = (ctx.panel.date_text or "").strip().upper()
    if d:
        _center_text(ctx, d, ctx.fonts.font("ui", max(13, int(u * 0.07))),
                     cx, ctx.cy0 + int(u * 0.66), (235, 235, 240))


def _layout_bigtype(ctx):
    u, ml = ctx.u, ctx.ml
    _wordmark(ctx, ctx.right_edge, 0.1, small=True, align="right")
    _logo(ctx, ctx.cy0 + int(u * 0.18), int(ctx.w * 0.92), "left", ml, max_h=0.46)
    _pills(ctx, ml, ctx.cy0 + int(u * 0.8), "left")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.78), "right",
          maxw=0.3, maxh=0.16, start=0.2)


def _layout_breaking(ctx):
    w, u, ml = ctx.w, ctx.u, ctx.ml
    tag = (ctx.panel.tag_main or "NEWS").upper()
    f = ctx.fonts.font("ui", max(14, int(u * 0.075)))
    l, t, r, b = ctx.draw.textbbox((0, 0), tag, font=f)
    padx, pady = int(w * 0.018), int(u * 0.03)
    bw, bh = (r - l) + 2 * padx, (b - t) + 2 * pady
    by = ctx.cy0 + int(u * 0.14)
    ctx.draw.rectangle([ml, by, ml + bw, by + bh], fill=ctx.accent + (255,))
    draw_text(ctx.draw, (ml + padx, by + pady), tag, f,
              readable_text_color(ctx.accent), shadow=False)
    maxw = int(w * 0.72)
    y = _logo(ctx, by + bh + int(u * 0.06), maxw, "left", ml, max_h=0.3) + int(u * 0.04)
    _subtitle(ctx, ml, y, maxw, "left")
    _wordmark(ctx, ctx.right_edge, 0.1, small=True, align="right")
    _date(ctx, ctx.right_edge, ctx.cy0 + int(u * 0.7), "right", maxw=0.3, maxh=0.2, start=0.28)


def _layout_stack(ctx):
    u, ml = ctx.u, ctx.ml
    _wordmark(ctx, ml, 0.12, small=True, align="left")
    maxw = int(ctx.w * 0.62)
    y = _logo(ctx, ctx.cy0 + int(u * 0.27), maxw, "left", ml, max_h=0.26) + int(u * 0.03)
    y = _subtitle(ctx, ml, y, maxw, "left")
    y = _pills(ctx, ml, y, "left")
    _date(ctx, ml, y + int(u * 0.01), "left", maxw=0.5, maxh=0.18, start=0.28)


def _layout_verbforward(ctx):
    """The 'RETURNS' look: series pill on top, a GIANT action verb as the hero,
    a subtitle line, and an optional confidence badge row (LEAK · UNCONFIRMED).
    Carries its own left→right scrim so the words stay legible over any art."""
    w, h, u, ml = ctx.w, ctx.h, ctx.u, ctx.ml
    panel, draw = ctx.panel, ctx.draw
    # guaranteed legibility scrim — scaled down by whatever the style already
    # applied, so stacked scrims can't crush left-heavy art to black
    applied = int(getattr(ctx.style, "scrim_left", 0) or 0)
    if applied < 160:
        sw = int(w * 0.74)
        ctx.base.alpha_composite(_alpha_scrim(sw, h, (0, 0, 0),
                                              max(80, 210 - applied), 0))

    y = ctx.cy0 + int(u * 0.05)
    # series pill (the small coloured tag on top)
    series = (panel.title or "").strip()
    if series:
        pf = ctx.fonts.font("ui", max(15, int(u * 0.085)))
        maxpw = int(w * 0.6)
        while pf.size > 14 and draw.textlength(series, font=pf) > maxpw:
            pf = ctx.fonts.font("ui", pf.size - 2)
        _, ph = draw_pill(draw, (ml, y), series, pf, ctx.accent,
                          readable_text_color(ctx.accent),
                          pad_x=int(w * 0.022), pad_y=int(u * 0.03),
                          radius=int(u * 0.05))
        y += ph + int(u * 0.045)

    # the giant verb (hero)
    verb = (panel.verb or panel.tag_main or "NEWS").strip().upper()
    vf = ctx.fonts.fit(draw, verb, "logo_heavy", int(w * 0.66), int(u * 0.38),
                       start=int(u * 0.46))
    _, vt, _, vb = draw.textbbox((0, 0), verb, font=vf)
    draw_text(draw, (ml, y), verb, vf, WHITE, shadow_off=(3, 4))
    y += (vb - vt) + int(u * 0.035)

    # subtitle line
    sub = (panel.subtitle or panel.date_text or "").strip()
    if sub:
        sf = ctx.fonts.fit(draw, sub, "ui", int(w * 0.62), int(u * 0.12),
                           start=int(u * 0.11))
        _, st, _, sb = draw.textbbox((0, 0), sub, font=sf)
        draw_text(draw, (ml, y), sub, sf, (240, 240, 245))
        y += (sb - st) + int(u * 0.045)

    # confidence badge row (first = solid accent, rest = solid dark); a date the
    # subtitle doesn't already show gets appended as a final dark chip
    raw = panel.badges
    if isinstance(raw, str):             # robust to a comma string from any caller
        raw = [x for x in re.split(r"[,/|]+", raw)]
    badges = [str(x).strip().upper() for x in (raw or []) if str(x).strip()]
    d_txt = (panel.date_text or "").strip().upper()
    if d_txt and d_txt.lower() not in sub.lower():
        badges = badges[:2] + [d_txt]
    if badges:
        bf = ctx.fonts.font("ui", max(12, int(u * 0.052)))
        padx, pady = int(w * 0.016), int(u * 0.024)
        bx = ml
        for i, bdg in enumerate(badges[:3]):
            bg = ctx.accent if i == 0 else (16, 16, 20)
            fg = readable_text_color(bg) if i == 0 else WHITE
            l0, t0, r0, b0 = draw.textbbox((0, 0), bdg, font=bf)
            bw, bh = (r0 - l0) + 2 * padx, (b0 - t0) + 2 * pady
            draw.rectangle([bx, y, bx + bw, y + bh], fill=bg + (255,))
            draw_text(draw, (bx + padx - l0, y + pady - t0), bdg, bf, fg, shadow=False)
            bx += bw + int(w * 0.012)


_LAYOUTS = {
    "classic": _layout_classic, "center": _layout_center, "mirror": _layout_mirror,
    "sidebar": _layout_sidebar, "bottombar": _layout_bottombar,
    "lowerthird": _layout_lowerthird, "badge": _layout_badge,
    "diagonal": _layout_diagonal, "vertical": _layout_vertical,
    "medallion": _layout_medallion, "ticket": _layout_ticket,
    "ribbon": _layout_ribbon, "halfsplit": _layout_halfsplit,
    "minimal": _layout_minimal, "bigtype": _layout_bigtype,
    "breaking": _layout_breaking, "stack": _layout_stack,
    "verbforward": _layout_verbforward,
}


# --------------------------------------------------------------------------
# card assembly
# --------------------------------------------------------------------------
def render_card(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> Image.Image:
    fonts = fonts or FontBook()
    style = spec.style or DEFAULT_STYLE
    n = max(1, len(panels))
    W, H = spec.width, spec.height
    card = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    base_h = H // n
    y = 0
    for i, panel in enumerate(panels):
        ph = H - y if i == n - 1 else base_h
        card.alpha_composite(render_panel(panel, W, ph, fonts, spec), (0, y))
        if spec.divider and i < n - 1:
            ImageDraw.Draw(card).line([(0, y + ph - 1), (W, y + ph - 1)],
                                              fill=style.divider, width=2)
        y += ph

    if spec.brand.watermark:
        # drawn on a transparent overlay and alpha-composited, so the 27%-alpha
        # mark is a true ghost (ImageDraw alone REPLACES pixels — it would come
        # out solid white); right-aligned to clear verb-forward's pills/badges.
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        wm = spec.brand.watermark.upper()
        f = fonts.font("ui", int(W * 0.034))
        l, t, r, b = od.textbbox((0, 0), wm, font=f)
        if n > 1:
            seams = [H * i // n for i in range(1, n)]
            wy = min(seams, key=lambda s: abs(s - H / 2))
            wx = W - int(W * 0.045) - (r - l)
        else:
            wy = int(H * 0.9)
            wx = (W - (r - l)) // 2
        od.text((wx - l, wy - (b - t) // 2 - t), wm, font=f,
                fill=(255, 255, 255, 70))
        card.alpha_composite(ov)
    return card


def render_cover(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None,
                 title: str = "LINE-UP") -> Image.Image:
    """A carousel cover slide: big event title + the list of series."""
    fonts = fonts or FontBook()
    W, H = spec.width, spec.height
    accent = hex_to_rgb(spec.brand.accent)
    base = vertical_gradient(W, H, (12, 12, 18), (26, 22, 42))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.08, H * 0.04, W * 0.92, H * 0.55],
                                 fill=accent + (90,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(170)))
    apply_vignette(base, 0.35)
    d = ImageDraw.Draw(base)

    # event wordmark, centered near the top (only if an event is set)
    ev = ((spec.brand.event_badge + "  " if spec.brand.event_badge else "")
          + spec.brand.event_name.upper()).strip()
    if ev:
        ev_font = fonts.font("ui", int(W * 0.045))
        l, t, r, b = d.textbbox((0, 0), ev, font=ev_font)
        draw_text(d, ((W - (r - l)) // 2, int(H * 0.12)), ev, ev_font, WHITE)

    # big title
    tf = fonts.fit(d, title.upper(), "date", int(W * 0.86), int(H * 0.2), start=int(H * 0.18))
    l, t, r, b = d.textbbox((0, 0), title.upper(), font=tf)
    draw_text(d, ((W - (r - l)) // 2, int(H * 0.26)), title.upper(), tf, WHITE, shadow_off=(3, 4))

    # accent rule
    ry = int(H * 0.42)
    d.rounded_rectangle([W // 2 - int(W * 0.08), ry, W // 2 + int(W * 0.08), ry + 8],
                        radius=4, fill=accent)

    # series list — sized to the band between the rule and the watermark, so it
    # never runs off the bottom on landscape covers
    names = [p.title.upper() for p in panels[:8]]
    lf = fonts.font("ui", int(min(W, H) * 0.045))
    _, ht, _, hb = d.textbbox((0, 0), "Ay", font=lf)
    band = int(H * 0.4)
    step = min(int((hb - ht) * 1.45), band // max(1, len(names)))
    y = int(H * 0.5)
    for line in names:
        l, t, r, b = d.textbbox((0, 0), line, font=lf)
        draw_text(d, ((W - (r - l)) // 2, y), line, lf, (235, 235, 240))
        y += step

    if spec.brand.watermark:
        wf = fonts.font("ui", int(W * 0.03))
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        l, t, r, b = od.textbbox((0, 0), spec.brand.watermark.upper(), font=wf)
        od.text((((W - (r - l)) // 2) - l, int(H * 0.93) - t), spec.brand.watermark.upper(),
                font=wf, fill=(255, 255, 255, 150))
        base.alpha_composite(ov)
    return base


def render_cards(panels: list[Panel], spec: CardSpec, fonts: FontBook | None = None) -> list[Image.Image]:
    fonts = fonts or FontBook()
    per = max(1, spec.panels_per_card)
    return [render_card(panels[i:i + per], spec, fonts)
            for i in range(0, len(panels), per)]


def save_cards(cards: list[Image.Image], out_dir: str, prefix: str = "card") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, card in enumerate(cards, 1):
        p = out / (f"{prefix}_{i}.png" if len(cards) > 1 else f"{prefix}.png")
        card.convert("RGB").save(p, "PNG")
        paths.append(str(p))
    return paths
